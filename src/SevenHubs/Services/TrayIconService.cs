using System;
using System.Collections.Generic;
using System.Drawing;
using System.Linq;
using System.Windows;
using SevenHubs.Models;

namespace SevenHubs.Services;

public sealed class TrayIconService : IDisposable
{
    private readonly System.Windows.Forms.NotifyIcon _notifyIcon;
    private readonly TrayPopup _popup;
    private DateTime _suppressToggleUntil;
    private bool _balloonShown;

    public event Action? OpenRequested;
    public event Action? RefreshRequested;
    public event Action? ExitRequested;

    public TrayIconService()
    {
        _popup = new TrayPopup();
        _popup.OpenMainRequested += () => OpenRequested?.Invoke();

        _notifyIcon = new System.Windows.Forms.NotifyIcon
        {
            Icon = LoadAppIcon(),
            Text = "7 HUBs · 外设状态中心",
            Visible = true
        };

        _notifyIcon.MouseClick += (_, e) =>
        {
            if (e.Button == System.Windows.Forms.MouseButtons.Left)
                TogglePopup();
        };

        var menu = new System.Windows.Forms.ContextMenuStrip();
        menu.Items.Add("打开 7 HUBs", null, (_, _) => OpenRequested?.Invoke());
        menu.Items.Add("立即刷新", null, (_, _) => RefreshRequested?.Invoke());
        menu.Items.Add(new System.Windows.Forms.ToolStripSeparator());
        menu.Items.Add("退出", null, (_, _) => ExitRequested?.Invoke());
        _notifyIcon.ContextMenuStrip = menu;
    }

    public void UpdateDevices(IEnumerable<DeviceRecord> devices)
        => _popup.UpdateDevices(devices);

    public void TogglePopup()
    {
        if (_popup.IsVisible)
        {
            _popup.Hide();
            _suppressToggleUntil = DateTime.UtcNow.AddMilliseconds(260);
            return;
        }

        if (DateTime.UtcNow < _suppressToggleUntil)
            return;

        _popup.ShowNearTray();
    }

    public void ShowPopup() => _popup.ShowNearTray();

    public void ShowMinimizedHint()
    {
        if (_balloonShown)
            return;

        _balloonShown = true;
        _notifyIcon.ShowBalloonTip(3000, "7 HUBs 仍在运行",
            "单击任务栏右下角的图标，快速查看已连接设备的电量。",
            System.Windows.Forms.ToolTipIcon.Info);
    }

    public void Dispose()
    {
        _notifyIcon.Visible = false;
        _notifyIcon.Dispose();
        _popup.Close();
    }

    private static Icon LoadAppIcon()
    {
        try
        {
            var resource = System.Windows.Application.GetResourceStream(
                new Uri("pack://application:,,,/Assets/app.ico"));
            if (resource?.Stream is { } stream)
            {
                using (stream)
                    return (Icon)new Icon(stream).Clone();
            }
        }
        catch
        {
            // 图标缺失时退回系统图标，不影响托盘功能。
        }

        return SystemIcons.Application;
    }
}
