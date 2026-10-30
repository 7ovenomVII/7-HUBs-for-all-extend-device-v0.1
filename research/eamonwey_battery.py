# -*- coding: utf-8 -*-
"""设备电量读取（纯 ctypes，无第三方依赖）。

已打通：
  * ROG OMNI RECEIVER (0B05:1ACE)  ->  ROG 月刃 AP (Keris Wireless Aimpoint)
  * 迈从 G87 V2 2.4G (3837:3033)   ->  J 协议实时电量查询（已实测）

对外接口：
  read_mouse()      -> Reading 或 None
  read_keyboard()   -> Reading 或 None
  read_all()        -> (mouse, keyboard)
"""

import ctypes
import time

import hid_win as H
from hid_win import setupapi, w

ROG_VID, ROG_PID = 0x0B05, 0x1ACE
MC_VID, MC_PID = 0x3837, 0x3033

# ------------------------------------------------------------ 蓝牙电量兜底
# Windows 蓝牙栈把设备上报的电量写在一个未公开 PnP 属性里：
#   PROPERTYKEY {104EA319-6EE2-4701-BD47-8DDBF425BBE5}, pid=2 (DEVPROP_TYPE_BYTE)
# 该属性挂在 BTHENUM 枚举出的节点上（免提/HID 节点），蓝牙连接时才有效。
_FMTID_BT = H.GUID(0x104EA319, 0x6EE2, 0x4701,
                   (ctypes.c_ubyte * 8)(0xBD, 0x47, 0x8D, 0xDB,
                                        0xF4, 0x25, 0xBB, 0xE5))
_DIGCF_PRESENT = 0x02
_DIGCF_ALLCLASSES = 0x04
_ERROR_NOT_FOUND = 1168


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", H.GUID), ("pid", w.DWORD)]


setupapi.SetupDiEnumDeviceInfo.restype = w.BOOL
setupapi.SetupDiEnumDeviceInfo.argtypes = [ctypes.c_void_p, w.DWORD,
                                           ctypes.POINTER(H.SP_DEVINFO_DATA)]
setupapi.SetupDiGetDeviceInstanceIdW.restype = w.BOOL
setupapi.SetupDiGetDeviceInstanceIdW.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(H.SP_DEVINFO_DATA), w.LPWSTR, w.DWORD,
    ctypes.POINTER(w.DWORD)]
setupapi.SetupDiGetDevicePropertyW.restype = w.BOOL
setupapi.SetupDiGetDevicePropertyW.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(H.SP_DEVINFO_DATA),
    ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(w.ULONG), ctypes.c_void_p,
    w.DWORD, ctypes.POINTER(w.DWORD), w.DWORD]
setupapi.SetupDiGetDeviceRegistryPropertyW.restype = w.BOOL
setupapi.SetupDiGetDeviceRegistryPropertyW.argtypes = [
    ctypes.c_void_p, ctypes.POINTER(H.SP_DEVINFO_DATA), w.DWORD,
    ctypes.POINTER(w.DWORD), ctypes.c_void_p, w.DWORD,
    ctypes.POINTER(w.DWORD)]


def _bt_node_name(hdev, info):
    buf = ctypes.create_unicode_buffer(512)
    need = w.DWORD(0)
    for prop in (0x0C, 0x00):        # FriendlyName / DeviceDesc
        if setupapi.SetupDiGetDeviceRegistryPropertyW(
                hdev, ctypes.byref(info), prop, None, buf, 512,
                ctypes.byref(need)):
            return buf.value
    return ""


def read_bluetooth_battery():
    """从蓝牙 PnP 属性读电量，返回 (电量, 名称) 或 (None, None)。"""
    best = (None, None)
    attempts = ((None, _DIGCF_ALLCLASSES), (u"BTHENUM", 0))
    for enumerator, flags in attempts:
        hdev = setupapi.SetupDiGetClassDevsW(None, enumerator, None,
                                             flags | _DIGCF_PRESENT)
        if not hdev or hdev == ctypes.c_void_p(-1).value:
            continue
        try:
            idx = 0
            info = H.SP_DEVINFO_DATA()
            while True:
                info.cbSize = ctypes.sizeof(H.SP_DEVINFO_DATA)
                if not setupapi.SetupDiEnumDeviceInfo(hdev, idx,
                                                      ctypes.byref(info)):
                    break
                idx += 1
                iid = ctypes.create_unicode_buffer(512)
                if not setupapi.SetupDiGetDeviceInstanceIdW(
                        hdev, ctypes.byref(info), iid, 512, None):
                    continue
                if not iid.value.upper().startswith("BTHENUM"):
                    continue
                name = _bt_node_name(hdev, info)
                if not name:
                    continue
                low = name.lower()
                # 只关心可能是我们键盘的节点
                if not ("mchose" in low or "迈从" in name or "g87" in low):
                    continue
                key = _PROPERTYKEY(_FMTID_BT, 2)
                ptype = w.ULONG(0)
                val = ctypes.c_ubyte(0)
                need = w.DWORD(0)
                if setupapi.SetupDiGetDevicePropertyW(
                        hdev, ctypes.byref(info), ctypes.byref(key),
                        ctypes.byref(ptype), ctypes.byref(val), 1,
                        ctypes.byref(need), 0):
                    level = int(val.value)
                    if 0 <= level <= 100 and ptype.value == 3 and best[0] is None:
                        best = (level, name)
        finally:
            setupapi.SetupDiDestroyDeviceInfoList(hdev)
    return best


class Reading(object):
    """一次电量读数。"""

    def __init__(self, level, charging=None, detail="", note=""):
        self.level = level            # 0-100 或 None
        self.charging = charging      # True / False / None(未知)
        self.detail = detail          # 数据来源说明
        self.note = note              # 附加提示（如“敲一下键盘”）
        self.at = time.time()

    @property
    def ok(self):
        return self.level is not None

    def __repr__(self):
        return "<Reading %s%% charging=%s>" % (self.level, self.charging)


# ---------------------------------------------------------------- ROG OMNI

def _rog_interface():
    for itf in H.enumerate_hid(ROG_VID, ROG_PID):
        if itf.usage_page == 0xFF01 and itf.out_len >= 64:
            return itf
    return None


def _rog_send(dev, payload, length=64, wait=0.55):
    """发一帧 64 字节报文（首字节为 Report ID 0x03），返回应答列表。"""
    pkt = bytes([0x03] + list(payload) + [0] * (length - 1 - len(payload)))
    dev.drain_input(length, max_reads=32, timeout_ms=0)
    if not dev.write_output(pkt, timeout_ms=400):
        return []
    out = []
    end = time.time() + wait
    while time.time() < end:
        d = dev.read_input(length, timeout_ms=120)
        if d:
            out.append(d)
            if len(out) >= 3:
                break
    return out


def read_mouse(tries=4):
    """ROG 月刃 AP：0x12 0x07 查询，电量在应答第 6 字节。
    无线鼠标闲置会进休眠，前几次查询常常是唤醒，因此重试多次。"""
    itf = _rog_interface()
    if itf is None:
        return Reading(None, None, "未找到 ROG OMNI 接收器", "请确认接收器已插好")

    last = Reading(None, None, "ROG 接收器无应答", "鼠标可能已休眠，动一下鼠标再刷新")
    for i in range(tries):
        try:
            with H.HidDevice(itf.path, write=True) as dev:
                replies = _rog_send(dev, [0x12, 0x07])
        except Exception as exc:            # 打不开 / 被占用
            return Reading(None, None, "ROG 接收器被占用", str(exc))

        for d in replies:
            # 期望 03 12 07 00 00 <level> ...
            if len(d) >= 7 and d[1] == 0x12 and d[2] == 0x07:
                level = d[5]
                if 0 <= level <= 100:
                    charge = d[10] > 0 if len(d) > 10 else None
                    return Reading(level, charge, "ROG OMNI · 0x12 0x07")

        if i + 1 < tries:
            time.sleep(0.25)
    return last


# ---------------------------------------------------------------- 迈从键盘
# G87 V2 uses Channel:Keyboard (J) in the official CZ SDK, not CZ-Ge.
# Request: 55 cmd 00 checksum size off_lo off_hi 00
# checksum = sum(bytes[4:]) & 0xff; Windows prepends Report ID 0.
# getFuncConfig (cmd 5): data[32] = charging << 7 | battery_percent.
# Battery broadcasts: FA FB 07 percent charging.
MC_WIRED_PID = 0x2015


def _mc_packet(cmd, size=56, offset=0, total=65):
    body = bytes([size, offset & 255, (offset >> 8) & 255, 0])
    frame = bytes([0, 0x55, cmd, 0, sum(body) & 255]) + body
    if len(frame) > total:
        raise ValueError("HID output report too short")
    return frame.ljust(total, b"\x00")


def _mc_payload(report):
    # WebHID hides the report ID; Windows ReadFile includes it.
    return report[1:] if report and report[0] == 0 else report


def _mc_battery_event(report):
    data = _mc_payload(report)
    if (len(data) >= 5 and data[:3] == b"\xfa\xfb\x07"
            and data[3] <= 100 and data[4] in (0, 1)):
        return Reading(data[3], bool(data[4]), "迈从 2.4G · 电量广播")
    return None


def _mc_interfaces():
    # Open only the official command collection; avoid keyboard input interfaces.
    return [i for i in H.enumerate_hid(MC_VID)
            if i.pid in (MC_PID, MC_WIRED_PID) and i.in_len >= 9
            and i.out_len >= 9
            and ((i.usage_page, i.usage) in ((1, 0), (0xFF00, 1)))]


def _mc_query(dev, itf, cmd, size=56, offset=0):
    if not dev.write_output(_mc_packet(cmd, size, offset, itf.out_len),
                            timeout_ms=300):
        return None, None, "写入失败：%s" % dev.last_error
    end = time.monotonic() + 0.65
    while time.monotonic() < end:
        report = dev.read_input(itf.in_len, timeout_ms=100)
        if not report:
            continue
        event = _mc_battery_event(report)
        if event:
            return None, event, ""
        data = _mc_payload(report)
        if len(data) < 8 or data[1] != cmd:
            continue
        if data[0] == 0xAB:
            return None, None, "接收器拒绝命令：%s" % data[8:].rstrip(b"\x00").decode("ascii", "replace")
        if (data[0] == 0xAA and data[4] <= size
                and data[5] == offset & 255 and data[6] == offset >> 8
                and len(data) >= 8 + data[4]):
            return data[8:8 + data[4]], None, ""
    return None, None, "命令无应答；请唤醒键盘后刷新"


def read_keyboard(probe_all=False):
    """Read G87 V2 battery using the official J protocol; Bluetooth fallback."""
    result = _read_keyboard_hid(probe_all)
    if result.ok:
        return result
    level, name = read_bluetooth_battery()
    if level is not None:
        return Reading(level, None, "蓝牙电量属性 · %s" % name)
    return result


def _read_keyboard_hid(probe_all=False):
    interfaces = _mc_interfaces()
    if not interfaces:
        return Reading(None, None, "未找到迈从键盘", "请确认接收器或 USB 连接")
    note = ""
    for itf in interfaces:
        for attempt in range(2 if probe_all else 1):
            try:
                with H.HidDevice(itf.path, write=True) as dev:
                    if not dev.valid or not dev.write_handle:
                        note = "命令接口无法打开；请关闭其他键盘驱动后刷新"
                        continue
                    # Do not drain input: queued reports may contain battery events.
                    base, event, note = _mc_query(dev, itf, 4)
                    if event:
                        return event
                    profile = 0
                    if base is not None and len(base) >= 6:
                        index, count = base[0], base[1]
                        if 0 < count <= 4 and index < count and base[2 + index] < 4:
                            profile = base[2 + index]
                    config, event, note = _mc_query(dev, itf, 5, offset=64 * profile)
                    if event:
                        return event
                    if config is not None and len(config) > 32:
                        value = config[32]
                        level = value & 0x7F
                        if level <= 100:
                            mode = "2.4G" if itf.pid == MC_PID else "USB"
                            return Reading(level, bool(value & 0x80),
                                           "迈从 %s · 实时查询" % mode)
                        note = "键盘返回无效电量（%d）" % level
            except Exception as exc:
                note = str(exc)
    return Reading(None, None, "键盘电量暂不可用", note)


# ---------------------------------------------------------------- 汇总

def read_all():
    return read_mouse(), read_keyboard()


if __name__ == "__main__":
    m, k = read_all()
    print("鼠标：", m.level, m.detail, m.note)
    print("键盘：", k.level, k.detail, k.note)
