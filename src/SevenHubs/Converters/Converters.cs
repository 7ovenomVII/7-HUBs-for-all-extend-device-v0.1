using System.Globalization;
using System.Windows.Data;
using System.Windows.Media;
using SevenHubs.Models;
using MediaBrush = System.Windows.Media.Brush;
using MediaColor = System.Windows.Media.Color;
using MediaColorConverter = System.Windows.Media.ColorConverter;

namespace SevenHubs.Converters;

public sealed class BatteryBrushConverter : IValueConverter
{
    private static readonly MediaBrush Low = Freeze("#FF6B6B");
    private static readonly MediaBrush Mid = Freeze("#FFB454");
    private static readonly MediaBrush Good = Freeze("#4ADE80");
    private static readonly MediaBrush None = Freeze("#6B7280");

    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        if (value is not int battery)
            return None;
        if (battery <= 20)
            return Low;
        if (battery <= 40)
            return Mid;
        return Good;
    }

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
        => throw new NotSupportedException();

    private static MediaBrush Freeze(string hex)
    {
        var brush = new SolidColorBrush((MediaColor)MediaColorConverter.ConvertFromString(hex));
        brush.Freeze();
        return brush;
    }
}

public sealed class ConnectionBrushConverter : IValueConverter
{
    private static readonly MediaBrush Usb = Freeze("#5AA7FF");
    private static readonly MediaBrush Wireless = Freeze("#31D0AA");
    private static readonly MediaBrush Bluetooth = Freeze("#A78BFA");
    private static readonly MediaBrush Unknown = Freeze("#8B93A7");

    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
    {
        return value switch
        {
            ConnectionKind.Usb => Usb,
            ConnectionKind.Wireless24G => Wireless,
            ConnectionKind.Bluetooth => Bluetooth,
            _ => Unknown
        };
    }

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
        => throw new NotSupportedException();

    private static MediaBrush Freeze(string hex)
    {
        var brush = new SolidColorBrush((MediaColor)MediaColorConverter.ConvertFromString(hex));
        brush.Freeze();
        return brush;
    }
}

public sealed class StatusBrushConverter : IValueConverter
{
    private static readonly MediaBrush Online = Freeze("#4ADE80");
    private static readonly MediaBrush Offline = Freeze("#5B6478");

    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
        => value is true ? Online : Offline;

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
        => throw new NotSupportedException();

    private static MediaBrush Freeze(string hex)
    {
        var brush = new SolidColorBrush((MediaColor)MediaColorConverter.ConvertFromString(hex));
        brush.Freeze();
        return brush;
    }
}

public sealed class EmptyStringToVisibilityConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
        => string.IsNullOrWhiteSpace(value as string) ? System.Windows.Visibility.Collapsed : System.Windows.Visibility.Visible;

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
        => throw new NotSupportedException();
}

public sealed class InverseBooleanConverter : IValueConverter
{
    public object Convert(object? value, Type targetType, object? parameter, CultureInfo culture)
        => value is not true;

    public object ConvertBack(object? value, Type targetType, object? parameter, CultureInfo culture)
        => value is not true;
}
