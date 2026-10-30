namespace SevenHubs.Services;

public static class KnownDevices
{
    public static readonly IReadOnlyList<Models.KnownDevice> All = new[]
    {
        new Models.KnownDevice
        {
            Key = "mchose-g87-v2",
            Name = "MCHOSE G87 V2",
            Vendor = "MCHOSE",
            Kind = "键盘",
            Glyph = "⌨",
            Accent = "#7C5CFF",
            VendorId = 0x3837,
            ProductIds = new[] { 0x3033 },
            PreferredConnection = Models.ConnectionKind.Wireless24G,
            MatchProduct = "G87",
            IsKeyboard = true
        },
        new Models.KnownDevice
        {
            Key = "atk-a9-air",
            Name = "ATK A9 Air 大师版",
            Vendor = "ATK",
            Kind = "鼠标",
            Glyph = "◉",
            Accent = "#31D0AA",
            VendorId = 0x373B,
            ProductIds = new[] { 0x11D9 },
            PreferredConnection = Models.ConnectionKind.Wireless24G,
            MatchProduct = "Wireless mouse",
            IsMouse = true
        },
        new Models.KnownDevice
        {
            Key = "mchose-v9-pro-2",
            Name = "MCHOSE V9 Pro 2",
            Vendor = "MCHOSE",
            Kind = "耳机",
            Glyph = "◒",
            Accent = "#5AA7FF",
            VendorId = 0x3837,
            ProductIds = new[] { 0x6011 },
            PreferredConnection = Models.ConnectionKind.Usb,
            MatchProduct = "V9",
            IsHeadset = true
        },
        new Models.KnownDevice
        {
            Key = "8bitdo-orion-2",
            Name = "8BitDo 猎户座 2 代",
            Vendor = "8BitDo",
            Kind = "手柄",
            Glyph = "✥",
            Accent = "#FF9F45",
            VendorId = 0x2DC8,
            ProductIds = new[] { 0x3109, 0x310B },
            PreferredConnection = Models.ConnectionKind.Wireless24G,
            MatchProduct = "8BitDo",
            IsController = true
        }
    };

    public static Models.KnownDevice? Find(ushort vendorId, ushort productId)
    {
        return All.FirstOrDefault(k => k.VendorId == vendorId && k.ProductIds.Contains(productId));
    }
}
