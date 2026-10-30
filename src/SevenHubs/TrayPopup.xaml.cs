using System;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Windows;
using SevenHubs.Models;

namespace SevenHubs;

public partial class TrayPopup : Window, INotifyPropertyChanged
{
    public ObservableCollection<DeviceRecord> Devices { get; } = new();

    public string Summary => Devices.Count == 0 ? "等待设备接入" : $"{Devices.Count} 台设备在线";

    public bool HasNoDevices => Devices.Count == 0;

    public event Action? OpenMainRequested;

    public TrayPopup()
    {
        InitializeComponent();
        DataContext = this;
    }

    public void UpdateDevices(IEnumerable<DeviceRecord> devices)
    {
        Devices.Clear();
        foreach (var device in devices.Where(d => d.Connected).OrderBy(d => d.Name))
            Devices.Add(device);
        OnPropertyChanged(nameof(Summary));
        OnPropertyChanged(nameof(HasNoDevices));
    }

    public void ShowNearTray()
    {
        Opacity = 0;
        Show();
        UpdateLayout();

        var area = SystemParameters.WorkArea;
        Left = area.Right - ActualWidth - 8;
        Top = area.Bottom - ActualHeight - 8;
        Opacity = 1;
        Activate();
    }

    private void OpenMain_Click(object sender, RoutedEventArgs e)
    {
        Hide();
        OpenMainRequested?.Invoke();
    }

    private void Window_Deactivated(object? sender, EventArgs e)
    {
        if (IsVisible)
            Hide();
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? name = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}
