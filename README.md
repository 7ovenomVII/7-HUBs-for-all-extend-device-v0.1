# 7 HUBs

Windows 外设状态中心：把键盘、鼠标、耳机、手柄的电量、连接方式和可读参数集中到一张卡片界面上，并常驻托盘。

当前版本：`0.2.0`（2026-10-30）

## 现在能做什么

- 双击 `SevenHubs.exe` 打开主窗口。
- 已连接 / 未连接设备分开展示；未连接设备保留最后一次电量和在线时间。
- 按设备类型自动分组：鼠标、键盘、耳机、手柄。
- 卡片直接显示电量、连接方式（USB / 2.4G / 蓝牙）和在线状态。
- 点卡片打开右侧详情：产品型号、固件、DPI、回报率、传感器、最后在线、电量更新时间；DPI/传感器只对鼠标显示，回报率只对鼠标和键盘显示。
- 关闭窗口不退出，收进任务栏右下角托盘；单击托盘图标弹出速览面板，右键菜单可打开主界面、立即刷新或退出。
- 每 30 秒自动扫描一次，也可以点标题栏的刷新按钮手动刷新。
- 历史记录默认写到 `%LOCALAPPDATA%\7HUBs\devices.json`；如果目录不可写，会退到程序旁边的 `data\devices.json`。

## 直接运行

运行 `dist\7HUBs\SevenHubs.exe`。

需要安装 **.NET 10 Desktop Runtime**（本机已有 `Microsoft.WindowsDesktop.App 10.0.x`）。发布目录是框架依赖版本，体积约 0.3 MB，不包含运行时。

关闭按钮只是隐藏到托盘；要彻底退出，右键托盘图标选“退出”。

## 当前设备支持情况

| 设备 | VID:PID | 连接 | 电量 | DPI / 回报率 |
| --- | --- | --- | --- | --- |
| 迈从 G87 V2 | `3837:3033` | 2.4G | 已实测可读（cmd 4 活动配置） | 回报率已实测可读（当前 1000 Hz）；DPI 不是键盘参数 |
| ATK A9 Air 大师版 | `373B:11D9` | 2.4G | 当前用 `FF04/0x06` feature report 兜底 | 协议已实现，但设备/厂商服务暂不响应 |
| 迈从 V9 Pro 2 | `3837:6011` | USB | 暂不可读 | 无 |
| 8BitDo 猎户座 2 代 NS 版 | `2DC8:3109` / `310B` | 2.4G | 暂不可读 | 无 |

说明：

- **G87 V2**：电量与回报率走同一条 65 字节 vendor 配置通道；`config[1]` 是回报率档位（1/2/3 对应 250/500/1000 Hz），`config[32]` 低 7 位是电量、最高位是充电状态。
- **8BitDo**：2.4G 接收器路径没有可靠的实时电量；社区实现（`MoridaDE/8bitdo-2c-battery-tray`）确认该系列主要通过蓝牙 GATT 读电量，USB/接收器只能做充电状态估算。因此卡片显示“未知”是预期行为，不是扫描失败。
- **V9 Pro 2**：旧款 V9 的 `55 65 01` 协议不适用于这一代；本机 `3837:6011` 的四个 HID collection 都试过，仍未拿到电量应答。当前只保证连接状态可见。
- **ATK**：正式协议是 `FF02/0x0002` 的 17 字节报告，电量 `res[6]`、有线标志 `res[7]`，EEPROM 命令 `0x08` 读 DPI/回报率；本机 ATK HUB 服务占用或鼠标休眠时拿不到应答，所以详情里的 DPI/回报率会显示 `—`。
- 厂商软件（ATK HUB、MCHOSE HUB）可能长期占用 HID；如果电量读不到，先退出厂商软件再点刷新。

## 从源码构建

本仓库使用本地 SDK，不依赖 Visual Studio：

```powershell
$env:DOTNET_CLI_HOME = "$PWD\.dotnet_home"
$env:NUGET_PACKAGES = "$PWD\.nuget"
$env:APPDATA = "$PWD\.appdata\Roaming"
$env:LOCALAPPDATA = "$PWD\.appdata\Local"

.\.dotnet\dotnet.exe build src\SevenHubs\SevenHubs.csproj
.\.dotnet\dotnet.exe publish src\SevenHubs\SevenHubs.csproj -c Release --no-restore -o dist\7HUBs
```

`NuGet.Config` 当前是离线配置（`<clear/>`），首次构建依赖本机 SDK/缓存的 WPF 包。

## 代码结构

```text
src/SevenHubs/
  Models/DeviceRecord.cs        设备卡片/详情模型
  Services/HidNative.cs         SetupAPI + hid.dll 枚举、读写、feature report
  Services/KnownDevices.cs      已支持设备目录（VID/PID/类型/连接方式）
  Services/BatteryReader.cs     G87 / ATK / 8BitDo 电量与 ATK DPI/回报率
  Services/DeviceScanner.cs     扫描、历史合并、在线/离线判定
  Services/HistoryStore.cs      本地历史 JSON（主路径 + 兜底路径）
  Services/TrayIconService.cs   托盘图标、速览弹窗、菜单
  TrayPopup.xaml                托盘速览面板
  MainWindow.xaml               主窗口卡片 + 详情
  App.xaml.cs                   启动、扫描事件、托盘接线
```

## 加一个新品牌/型号

1. 在 `src/SevenHubs/Services/KnownDevices.cs` 增加 VID/PID、名称、类型和默认连接方式。
2. 在 `src/SevenHubs/Services/BatteryReader.cs` 增加该型号的只读查询；拿不到电量就返回 `null`，不要伪造。
3. 如果 VID/PID 会随有线/2.4G/蓝牙变化，把多个 PID 都放进 `ProductIds`。
4. 重新构建并刷新，卡片会自动出现。

DPI、回报率没有 Windows 统一接口，必须逐品牌逆向/参考厂商协议；不要把“电量可读”当成“DPI 也可读”。

## 已知限制

- 目前只验证了上述 4 台设备；其他型号需要单独适配。
- 电量依赖厂商 HID 协议，设备休眠、厂商软件占用、接收器休眠都会导致读不到。
- 未连接卡片依赖本地历史；第一次运行前没插过的设备不会凭空出现。
- 托盘图标左键点击、托盘“打开主界面”按钮建议人工再点一遍确认（自动化工具无法枚举 Windows 托盘按钮）。
