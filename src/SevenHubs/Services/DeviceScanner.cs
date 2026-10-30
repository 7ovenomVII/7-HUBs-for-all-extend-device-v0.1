using System.Collections.Generic;
using System.Linq;
using SevenHubs.Models;

namespace SevenHubs.Services;

public sealed class DeviceScanner
{
    private readonly HistoryStore _history;

    public DeviceScanner(HistoryStore history) => _history = history;

    public Task<List<DeviceRecord>> ScanAsync() => Task.Run(Scan);

    public List<DeviceRecord> Scan()
    {
        var interfaces = HidNative.Enumerate();
        var history = _history.Load();
        var now = DateTime.Now;
        var results = new List<DeviceRecord>();

        foreach (var known in KnownDevices.All)
        {
            var matching = interfaces
                .Where(i => i.VendorId == known.VendorId && known.ProductIds.Contains(i.ProductId))
                .OrderByDescending(i => i.IsVendorDefined)
                .ThenByDescending(i => i.OutputReportLength)
                .ToList();

            DeviceRecord record;
            if (history.TryGetValue(known.Key, out var saved))
            {
                record = saved.Clone();
            }
            else
            {
                record = new DeviceRecord
                {
                    Id = known.Key,
                    Name = known.Name,
                    Vendor = known.Vendor,
                    Kind = known.Kind,
                    Glyph = known.Glyph,
                    Accent = known.Accent,
                    VendorId = known.VendorId,
                    ProductId = known.ProductIds[0],
                    Connection = known.PreferredConnection,
                    Note = DefaultNote(known)
                };
            }

            record.Id = known.Key;
            record.Name = known.Name;
            record.Vendor = known.Vendor;
            record.Kind = known.Kind;
            record.Glyph = known.Glyph;
            record.Accent = known.Accent;
            record.VendorId = known.VendorId;

            if (matching.Count > 0)
            {
                var primary = matching[0];
                record.Connected = true;
                record.LastSeen = now;
                record.Product = matching.Select(i => i.Product).FirstOrDefault(p => !string.IsNullOrWhiteSpace(p)) ?? record.Product;
                record.Serial = matching.Select(i => i.Serial).FirstOrDefault(s => !string.IsNullOrWhiteSpace(s)) ?? record.Serial;
                var version = matching.Select(i => i.Version).FirstOrDefault(v => v != 0);
                if (version != 0)
                    record.Firmware = version.ToString("X4");
                record.HidPath = primary.Path;
                record.ProductId = primary.ProductId;
                record.Connection = DetectConnection(known, matching);

                var battery = BatteryReader.Read(known, matching);
                if (battery.Battery is int percent)
                {
                    record.Battery = percent;
                    record.BatteryUpdatedAt = now;
                }
                else if (known.IsController)
                {
                    // XInput 在部分接收器/模式下会报告“已连接但电量未知”，
                    // 不能沿用历史里的假 100%，宁可显示“电量暂不可读”。
                    record.Battery = null;
                    record.Charging = null;
                    record.BatteryUpdatedAt = null;
                }
                if (battery.Charging is bool charging)
                    record.Charging = charging;
                if (battery.Connection is ConnectionKind connection)
                    record.Connection = connection;
                if (battery.Dpi is int dpi)
                    record.Dpi = dpi;
                if (battery.PollingRate is int rate)
                    record.PollingRate = rate;
                if (!string.IsNullOrWhiteSpace(battery.Sensor))
                    record.Sensor = battery.Sensor!;
            }
            else
            {
                record.Connected = false;
                if (record.LastSeen == default)
                    record.Connection = known.PreferredConnection;
            }

            results.Add(record);
        }

        _history.Save(results);
        return results;
    }

    private static ConnectionKind DetectConnection(KnownDevice known, IReadOnlyList<HidDeviceInfo> interfaces)
    {
        var product = string.Join(" ", interfaces.Select(i => i.Product));
        var path = string.Join(" ", interfaces.Select(i => i.Path));

        if (path.Contains("bth", StringComparison.OrdinalIgnoreCase) ||
            product.Contains("Bluetooth", StringComparison.OrdinalIgnoreCase))
            return ConnectionKind.Bluetooth;

        if (product.Contains("2.4G", StringComparison.OrdinalIgnoreCase) ||
            product.Contains("Wireless", StringComparison.OrdinalIgnoreCase) ||
            product.Contains("dongle", StringComparison.OrdinalIgnoreCase) ||
            product.Contains("Receiver", StringComparison.OrdinalIgnoreCase) ||
            product.Contains("UM 2", StringComparison.OrdinalIgnoreCase))
            return ConnectionKind.Wireless24G;

        return known.PreferredConnection;
    }

    private static string DefaultNote(KnownDevice known) => known.Key switch
    {
        "mchose-g87-v2" => "电量通过 MCHOSE 64 字节厂商通道读取",
        "atk-a9-air" => "电量优先走 ATK 私有协议，失败时使用 feature report 兜底",
        "mchose-v9-pro-2" => "连接状态可读，电量协议待适配",
        "8bitdo-orion-2" => "电量通过 XInput 读取",
        _ => ""
    };
}
