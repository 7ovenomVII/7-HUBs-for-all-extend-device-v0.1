using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Data;
using System.Windows.Input;
using System.Windows.Threading;
using SevenHubs.Models;
using SevenHubs.Services;

namespace SevenHubs;

public partial class MainWindow : Window, INotifyPropertyChanged
{
    private readonly DeviceScanner _scanner = new(new HistoryStore());
    private readonly DispatcherTimer _timer;
    private readonly List<DeviceRecord> _allDevices = new();

    private DeviceRecord? _selectedDevice;
    private string _lastScanText = "准备扫描…";
    private bool _isRefreshing;
    private bool _allowClose;

    public ObservableCollection<DeviceRecord> ConnectedDevices { get; } = new();
    public ObservableCollection<DeviceRecord> DisconnectedDevices { get; } = new();
    public ICollectionView ConnectedView { get; }
    public ICollectionView DisconnectedView { get; }

    public event Action<IReadOnlyList<DeviceRecord>>? DevicesUpdated;
    public event Action? HiddenToTray;

    public MainWindow()
    {
        InitializeComponent();
        ConnectedView = CreateGroupedView(ConnectedDevices);
        DisconnectedView = CreateGroupedView(DisconnectedDevices);
        DataContext = this;

        var workArea = SystemParameters.WorkArea;
        Width = Math.Min(Width, Math.Max(MinWidth, workArea.Width - 24));
        Height = Math.Min(Height, Math.Max(MinHeight, workArea.Height - 24));

        _timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(30) };
        _timer.Tick += async (_, _) => await RefreshAsync();
    }

    public bool AllowClose
    {
        get => _allowClose;
        set => _allowClose = value;
    }

    public DeviceRecord? SelectedDevice
    {
        get => _selectedDevice;
        set
        {
            if (ReferenceEquals(_selectedDevice, value))
                return;

            _selectedDevice = value;
            OnPropertyChanged();
            OnPropertyChanged(nameof(HasSelection));
        }
    }

    public bool HasSelection => SelectedDevice is not null;
    public bool HasNoConnected => ConnectedDevices.Count == 0;
    public bool HasDisconnected => DisconnectedDevices.Count > 0;

    public string ConnectedSummary =>
        $"{ConnectedDevices.Count} 台在线 · {DisconnectedDevices.Count} 台离线";

    public string LastScanText
    {
        get => _lastScanText;
        private set
        {
            if (_lastScanText == value)
                return;

            _lastScanText = value;
            OnPropertyChanged();
        }
    }

    public bool IsRefreshing
    {
        get => _isRefreshing;
        private set
        {
            if (_isRefreshing == value)
                return;

            _isRefreshing = value;
            OnPropertyChanged();
        }
    }

    public async Task RefreshAsync()
    {
        if (IsRefreshing)
            return;

        IsRefreshing = true;
        LastScanText = "正在扫描…";

        try
        {
            var selectedId = SelectedDevice?.Id;
            var devices = await _scanner.ScanAsync();

            _allDevices.Clear();
            _allDevices.AddRange(devices);

            ConnectedDevices.Clear();
            DisconnectedDevices.Clear();

            foreach (var device in devices.Where(d => d.Connected).OrderBy(d => d.Name))
                ConnectedDevices.Add(device);

            foreach (var device in devices.Where(d => !d.Connected).OrderByDescending(d => d.LastSeen))
                DisconnectedDevices.Add(device);

            SelectedDevice = selectedId is null
                ? null
                : _allDevices.FirstOrDefault(d => d.Id == selectedId);

            LastScanText = $"更新于 {DateTime.Now:HH:mm:ss}";
            NotifyListState();
            DevicesUpdated?.Invoke(_allDevices);
        }
        catch (Exception ex)
        {
            LastScanText = $"扫描失败：{ex.Message}";
        }
        finally
        {
            IsRefreshing = false;
        }
    }

    public void ShowFromTray()
    {
        if (!IsVisible)
            Show();

        if (WindowState == WindowState.Minimized)
            WindowState = WindowState.Normal;

        Activate();
        Topmost = true;
        Topmost = false;
    }

    public void ForceClose()
    {
        _allowClose = true;
        Close();
    }

    private async void Window_Loaded(object sender, RoutedEventArgs e)
    {
        _timer.Start();
        await RefreshAsync();
    }

    private async void Refresh_Click(object sender, RoutedEventArgs e)
    {
        await RefreshAsync();
    }

    private void Card_Click(object sender, RoutedEventArgs e)
    {
        if (sender is FrameworkElement { DataContext: DeviceRecord device })
            SelectedDevice = device;
    }

    private void CloseDetail_Click(object sender, RoutedEventArgs e)
        => SelectedDevice = null;

    private void TitleBar_MouseLeftButtonDown(object sender, MouseButtonEventArgs e)
    {
        if (e.ClickCount == 2)
        {
            ToggleMaximize();
            return;
        }

        if (e.LeftButton == MouseButtonState.Pressed)
        {
            try
            {
                DragMove();
            }
            catch (InvalidOperationException)
            {
                // 鼠标已松开时 DragMove 会抛异常，忽略即可。
            }
        }
    }

    private void Minimize_Click(object sender, RoutedEventArgs e)
        => WindowState = WindowState.Minimized;

    private void Maximize_Click(object sender, RoutedEventArgs e)
        => ToggleMaximize();

    private void ToggleMaximize()
        => WindowState = WindowState == WindowState.Maximized
            ? WindowState.Normal
            : WindowState.Maximized;

    private void Close_Click(object sender, RoutedEventArgs e)
        => Close();

    private void Window_Closing(object? sender, CancelEventArgs e)
    {
        if (_allowClose)
            return;

        e.Cancel = true;
        Hide();
        HiddenToTray?.Invoke();
    }

    private void Window_StateChanged(object? sender, EventArgs e)
    {
        // 保留最小化到任务栏的行为；点击关闭按钮才隐藏到托盘。
    }

    private static ICollectionView CreateGroupedView(ObservableCollection<DeviceRecord> items)
    {
        var view = CollectionViewSource.GetDefaultView(items);
        view.GroupDescriptions.Clear();
        view.GroupDescriptions.Add(new PropertyGroupDescription(nameof(DeviceRecord.Kind)));
        view.SortDescriptions.Clear();
        view.SortDescriptions.Add(new SortDescription(nameof(DeviceRecord.KindOrder), ListSortDirection.Ascending));
        view.SortDescriptions.Add(new SortDescription(nameof(DeviceRecord.Name), ListSortDirection.Ascending));
        return view;
    }

    private void NotifyListState()
    {
        OnPropertyChanged(nameof(HasNoConnected));
        OnPropertyChanged(nameof(HasDisconnected));
        OnPropertyChanged(nameof(ConnectedSummary));
    }

    public event PropertyChangedEventHandler? PropertyChanged;

    private void OnPropertyChanged([CallerMemberName] string? name = null)
        => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
}
