using System;
using System.IO;
using System.Linq;
using System.Windows;
using System.Windows.Threading;
using SevenHubs.Services;

namespace SevenHubs;

public partial class App : System.Windows.Application
{
    private MainWindow? _mainWindow;
    private TrayIconService? _tray;

    public App()
    {
        AppDomain.CurrentDomain.UnhandledException += (_, args) =>
            WriteStartupError(args.ExceptionObject as Exception);
        DispatcherUnhandledException += (_, args) =>
        {
            WriteStartupError(args.Exception);
            args.Handled = false;
        };
    }

    private static void WriteStartupError(Exception? ex)
    {
        if (ex is null)
            return;
        try
        {
            var path = Path.Combine(AppContext.BaseDirectory, "startup-error.log");
            File.AppendAllText(path, $"[{DateTime.Now:yyyy-MM-dd HH:mm:ss}]\n{ex}\n\n");
        }
        catch
        {
            // 启动诊断日志失败不能影响主流程。
        }
    }

    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        _mainWindow = new MainWindow();
        _tray = new TrayIconService();

        _tray.OpenRequested += () => _mainWindow?.ShowFromTray();
        _tray.RefreshRequested += async () =>
        {
            if (_mainWindow is not null)
                await _mainWindow.RefreshAsync();
        };
        _tray.ExitRequested += ExitApplication;

        _mainWindow.DevicesUpdated += devices => _tray?.UpdateDevices(devices);
        _mainWindow.HiddenToTray += () => _tray?.ShowMinimizedHint();

        SessionEnding += (_, _) =>
        {
            if (_mainWindow is not null)
                _mainWindow.AllowClose = true;
        };

        _mainWindow.Show();

        if (e.Args.Contains("--tray-preview", StringComparer.OrdinalIgnoreCase))
        {
            _mainWindow.Hide();
            var previewTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
            previewTimer.Tick += (_, _) =>
            {
                previewTimer.Stop();
                _tray?.ShowPopup();
            };
            previewTimer.Start();
        }
    }

    private void ExitApplication()
    {
        _mainWindow?.ForceClose();
        _tray?.Dispose();
        _tray = null;
        Shutdown();
    }

    protected override void OnExit(ExitEventArgs e)
    {
        _tray?.Dispose();
        _tray = null;
        base.OnExit(e);
    }
}
