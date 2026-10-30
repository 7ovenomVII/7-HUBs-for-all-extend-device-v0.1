using System.Collections.Generic;
using System.Linq;
using SevenHubs.Models;

namespace SevenHubs.Services;

public sealed record BatteryReadResult(
    int? Battery,
    bool? Charging = null,
    ConnectionKind? Connection = null,
    int? Dpi = null,
    int? PollingRate = null,
    string? Sensor = null);

public static class BatteryReader
{
    public static BatteryReadResult Read(KnownDevice known, IReadOnlyList<HidDeviceInfo> interfaces)
    {
        try
        {
            if (known.IsKeyboard)
                return ReadG87(interfaces);

            if (known.IsMouse)
                return ReadAtk(interfaces);

            if (known.IsController)
                return Read8BitDo();

            return new BatteryReadResult(null);
        }
        catch
        {
            return new BatteryReadResult(null);
        }
    }

    private static BatteryReadResult ReadG87(IReadOnlyList<HidDeviceInfo> interfaces)
    {
        var info = interfaces
            .Where(i => i.OutputReportLength >= 65 && i.InputReportLength >= 65)
            .OrderByDescending(i => i.UsagePage == 0x0001 && i.Usage == 0x0000)
            .FirstOrDefault();

        if (info is null)
            return new BatteryReadResult(null);

        using var connection = HidConnection.Open(info.Path);
        if (connection is null)
            return new BatteryReadResult(null);

        // G87 V2 的 0x04 命令一次返回活动配置：data[1]=回报率，data[32]=电量/充电位。
        var config = ReadG87Config(connection);
        if (config is { Length: > 32 })
        {
            var battery = config[32] & 0x7F;
            var charging = (config[32] & 0x80) != 0;
            var polling = config[1] switch
            {
                1 => 250,
                2 => 500,
                3 => 1000,
                _ => (int?)null
            };

            if (battery is > 0 and <= 100)
                return new BatteryReadResult(battery, charging, ConnectionKind.Wireless24G, null, polling, "MCHOSE");
        }

        var request = new byte[65];
        request[0] = 0x00;
        request[1] = 0x55;
        request[2] = 0x03;
        request[3] = 0x00;
        request[4] = 0x38;
        request[5] = 0x38;

        for (var attempt = 0; attempt < 3; attempt++)
        {
            if (!connection.Write(request, 500))
                continue;

            var response = connection.Read(65, 600);
            if (response is null || response.Length < 10)
                continue;

            // Response starts with report ID 0x00: 00 AA 03 00 38 26 ... 24
            var offset = response[0] == 0x00 && response.Length >= 65 ? 1 : 0;
            var batteryIndex = offset + 8;
            if (response.Length <= batteryIndex)
                continue;

            var battery = response[batteryIndex];
            if (battery is > 0 and <= 100)
                return new BatteryReadResult(battery, false);
        }

        return new BatteryReadResult(null);
    }

    private static byte[]? ReadG87Config(HidConnection connection)
    {
        var request = new byte[65];
        request[0] = 0x00;
        request[1] = 0x55;
        request[2] = 0x04;
        request[3] = 0x00;
        request[4] = 0x38; // checksum = size(56) + offset(0)
        request[5] = 0x38;
        request[6] = 0x00;
        request[7] = 0x00;

        for (var attempt = 0; attempt < 3; attempt++)
        {
            if (!connection.Write(request, 500))
                continue;

            var response = connection.Read(65, 600);
            if (response is null || response.Length < 42)
                continue;

            var offset = response[0] == 0x00 && response.Length >= 65 ? 1 : 0;
            // 负载头为 AA cmd 00 checksum size offset，配置数据从负载下标 8 开始。
            var dataOffset = offset + 8;
            if (dataOffset + 32 >= response.Length)
                continue;

            return response.Skip(dataOffset).ToArray();
        }

        return null;
    }

    private static BatteryReadResult ReadAtk(IReadOnlyList<HidDeviceInfo> interfaces)
    {
        var info = interfaces
            .Where(i => i.OutputReportLength >= 17 && i.InputReportLength >= 17)
            .OrderByDescending(i => i.UsagePage == 0xFF02 && i.Usage == 0x0002)
            .FirstOrDefault();

        if (info is not null)
        {
            using var connection = HidConnection.Open(info.Path);
            if (connection is not null)
            {
                var battery = ReadAtkBattery(connection);
                if (battery is not null)
                {
                    var (percent, wired) = battery.Value;
                    var dpi = ReadAtkDpi(connection);
                    return new BatteryReadResult(
                        percent,
                        null,
                        wired ? ConnectionKind.Usb : ConnectionKind.Wireless24G,
                        dpi.Dpi,
                        dpi.PollingRate,
                        "ATK");
                }
            }
        }

        // Some ATK dongles expose battery as an 8-byte feature report (report 0x06, byte 3).
        var featureInfo = interfaces
            .Where(i => i.FeatureReportLength >= 8)
            .OrderByDescending(i => i.UsagePage == 0xFF04)
            .FirstOrDefault();
        if (featureInfo is not null)
        {
            using var connection = HidConnection.Open(featureInfo.Path);
            var feature = connection?.GetFeature(0x06, Math.Max(8, (int)featureInfo.FeatureReportLength));
            if (feature is { Length: >= 4 } && feature[3] is > 0 and <= 100)
                return new BatteryReadResult(feature[3], null, ConnectionKind.Wireless24G);
        }

        return new BatteryReadResult(null);
    }

    private static (int Percent, bool Wired)? ReadAtkBattery(HidConnection connection)
    {
        for (var attempt = 0; attempt < 3; attempt++)
        {
            var command = BuildAtkCommand(0x04);
            if (!connection.Write(command, 350))
                continue;

            for (var read = 0; read < 3; read++)
            {
                var response = connection.Read(17, 250);
                if (response is null || response.Length < 8)
                    continue;
                if (response[0] != 0x08 || response[1] != 0x04)
                    continue;

                var percent = response[6];
                if (percent is > 0 and <= 100)
                    return (percent, response[7] != 0);
            }
        }

        return null;
    }

    private static (int? Dpi, int? PollingRate) ReadAtkDpi(HidConnection connection)
    {
        try
        {
            var pollingRaw = ReadAtkEeprom(connection, 0x0000, 1);
            var stageCount = ReadAtkEeprom(connection, 0x0002, 1);
            var currentStage = ReadAtkEeprom(connection, 0x0004, 1);

            int? polling = null;
            if (pollingRaw is { Length: >= 1 })
                polling = pollingRaw[0] switch
                {
                    8 => 125,
                    4 => 250,
                    2 => 500,
                    1 => 1000,
                    0x10 => 2000,
                    0x20 => 4000,
                    0x40 => 8000,
                    _ => null
                };

            int? dpi = null;
            if (stageCount is { Length: >= 1 } && currentStage is { Length: >= 1 })
            {
                var count = Math.Clamp((int)stageCount[0], 1, 5);
                var stage = Math.Clamp((int)currentStage[0], 0, count - 1);
                var low = ReadAtkEeprom(connection, (ushort)(0x000C + stage * 4), 1);
                var mult = ReadAtkEeprom(connection, (ushort)(0x000C + stage * 4 + 2), 1);
                if (low is { Length: >= 1 } && mult is { Length: >= 1 })
                    dpi = (low[0] + 1) * 10 * ((mult[0] & 0x0F) + 1);
            }

            return (dpi, polling);
        }
        catch
        {
            return (null, null);
        }
    }

    private static byte[]? ReadAtkEeprom(HidConnection connection, ushort address, byte length)
    {
        for (var attempt = 0; attempt < 2; attempt++)
        {
            var command = BuildAtkCommand(0x08, address, length);
            if (!connection.Write(command, 350))
                continue;

            for (var read = 0; read < 3; read++)
            {
                var response = connection.Read(17, 250);
                if (response is null || response.Length < 6 + length)
                    continue;
                if (response[0] != 0x08 || response[1] != 0x08)
                    continue;

                var data = new byte[length];
                Array.Copy(response, 6, data, 0, length);
                return data;
            }
        }

        return null;
    }

    private static byte[] BuildAtkCommand(byte commandId, ushort address = 0, byte length = 0)
    {
        var report = new byte[17];
        report[0] = 0x08;
        report[1] = commandId;
        report[3] = (byte)(address >> 8);
        report[4] = (byte)address;
        report[5] = length;

        var sum = 0;
        for (var i = 0; i < 16; i++)
            sum += report[i];
        report[16] = (byte)((0x55 - sum) & 0xFF);
        return report;
    }

    private static BatteryReadResult Read8BitDo()
    {
        var battery = XInputBattery.TryRead();
        if (battery is null)
            return new BatteryReadResult(null);

        if (battery.Wired)
            return new BatteryReadResult(null, null, ConnectionKind.Usb);

        return new BatteryReadResult(
            battery.Percent,
            false,
            ConnectionKind.Wireless24G);
    }
}
