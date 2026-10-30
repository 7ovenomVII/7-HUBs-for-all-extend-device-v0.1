using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace SevenHubs.Models;

public enum ConnectionKind
{
    Unknown,
    Usb,
    Wireless24G,
    Bluetooth
}

public static class ConnectionKindText
{
    public static string ToText(this ConnectionKind kind) => kind switch
    {
        ConnectionKind.Usb => "USB",
        ConnectionKind.Wireless24G => "2.4G",
        ConnectionKind.Bluetooth => "蓝牙",
        _ => "未知"
    };
}

public sealed class DeviceRecord
{
    public string Id { get; set; } = "";
    public string Name { get; set; } = "";
    public string Vendor { get; set; } = "";
    public string Kind { get; set; } = "外设";
    public string Glyph { get; set; } = "◈";
    public string Accent { get; set; } = "#7C5CFF";
    public int VendorId { get; set; }
    public int ProductId { get; set; }
    public string Serial { get; set; } = "";
    public string Product { get; set; } = "";
    public string Firmware { get; set; } = "";
    public string HidPath { get; set; } = "";

    public bool Connected { get; set; }
    public ConnectionKind Connection { get; set; }
    public int? Battery { get; set; }
    public bool? Charging { get; set; }
    public int? Dpi { get; set; }
    public int? PollingRate { get; set; }
    public string Sensor { get; set; } = "";

    public DateTime LastSeen { get; set; }
    public DateTime? BatteryUpdatedAt { get; set; }
    public string Note { get; set; } = "";

    [JsonIgnore] public string BatteryText => Battery is null ? "未知" : $"{Battery}%";
    [JsonIgnore] public string ConnectionText => Connection.ToText();
    [JsonIgnore] public string StatusText => Connected ? "已连接" : "未连接";
    [JsonIgnore] public string LastSeenText
    {
        get
        {
            if (LastSeen == default) return "从未连接";
            var span = DateTime.Now - LastSeen;
            if (span.TotalSeconds < 60) return "刚刚";
            if (span.TotalMinutes < 60) return $"{(int)span.TotalMinutes} 分钟前";
            if (span.TotalHours < 24) return $"{(int)span.TotalHours} 小时前";
            if (span.TotalDays < 30) return $"{(int)span.TotalDays} 天前";
            return LastSeen.ToString("yyyy-MM-dd");
        }
    }

    [JsonIgnore] public bool IsMouse => Kind == "鼠标";
    [JsonIgnore] public bool IsKeyboard => Kind == "键盘";
    [JsonIgnore] public bool IsHeadset => Kind == "耳机";
    [JsonIgnore] public bool IsController => Kind == "手柄";
    [JsonIgnore] public bool ShowPolling => IsMouse || IsKeyboard;
    [JsonIgnore] public int KindOrder => Kind switch
    {
        "鼠标" => 0,
        "键盘" => 1,
        "耳机" => 2,
        "手柄" => 3,
        _ => 9
    };

    [JsonIgnore] public string DetailLine
    {
        get
        {
            var parts = new List<string>();
            if (IsMouse && Dpi is int dpi) parts.Add($"{dpi} DPI");
            if (ShowPolling && PollingRate is int hz) parts.Add($"{hz} Hz");
            if (!string.IsNullOrWhiteSpace(Firmware)) parts.Add($"固件 {Firmware}");
            return parts.Count > 0 ? string.Join("  ·  ", parts) : "点击查看详情";
        }
    }

    [JsonIgnore] public bool HasBattery => Battery is not null;

    [JsonIgnore] public string BatteryCaption => Battery is null ? "电量暂不可读" : (Connected ? "当前电量" : "上次电量");

    [JsonIgnore] public string BatterySuffix => Battery is null ? "" : " 电量";

    [JsonIgnore] public string CapabilityNote
    {
        get
        {
            if (Dpi is not null || PollingRate is not null)
                return "";
            return Kind switch
            {
                "鼠标" => "DPI 与回报率需要厂商私有协议，当前型号暂未适配",
                "键盘" => "该键盘暂未开放 DPI / 回报率读取",
                "耳机" => "V9 Pro 2 的电量协议尚未确认，当前仅显示连接状态",
                "手柄" => "手柄通过 XInput 读取电量；当前未上报电量或详细参数",
                _ => "该设备暂未开放详细参数"
            };
        }
    }

    public DeviceRecord Clone() => (DeviceRecord)MemberwiseClone();
}

public sealed class KnownDevice
{
    public required string Key { get; init; }
    public required string Name { get; init; }
    public required string Vendor { get; init; }
    public required string Kind { get; init; }
    public required string Glyph { get; init; }
    public required string Accent { get; init; }
    public required int VendorId { get; init; }
    public required int[] ProductIds { get; init; }
    public ConnectionKind PreferredConnection { get; init; } = ConnectionKind.Usb;
    public string MatchProduct { get; init; } = "";
    public bool IsController { get; init; }
    public bool IsMouse { get; init; }
    public bool IsKeyboard { get; init; }
    public bool IsHeadset { get; init; }
}
