using System.Runtime.InteropServices;

namespace SevenHubs.Services;

public sealed record XInputBatteryResult(int Percent, bool Wired, int Slot);

public static class XInputBattery
{
    private const byte BatteryDevTypeGamepad = 0;

    [StructLayout(LayoutKind.Sequential)]
    private struct XINPUT_BATTERY_INFORMATION
    {
        public byte BatteryType;
        public byte BatteryLevel;
    }

    [DllImport("xinput1_4.dll")]
    private static extern int XInputGetBatteryInformation(uint userIndex, byte deviceType, out XINPUT_BATTERY_INFORMATION batteryInformation);

    public static XInputBatteryResult? TryRead()
    {
        for (uint slot = 0; slot < 4; slot++)
        {
            try
            {
                if (XInputGetBatteryInformation(slot, BatteryDevTypeGamepad, out var info) != 0)
                    continue;

                // 0 = disconnected, 1 = wired, 2 = alkaline, 3 = NiMH, 4 = lithium.
                if (info.BatteryType == 0)
                    continue;

                var wired = info.BatteryType == 1;
                var percent = wired ? 100 : info.BatteryLevel switch
                {
                    0 => 5,
                    1 => 20,
                    2 => 60,
                    3 => 100,
                    _ => 50
                };
                return new XInputBatteryResult(percent, wired, (int)slot);
            }
            catch
            {
                return null;
            }
        }

        return null;
    }
}
