"""Live probes for the four peripherals on this machine.

Every transaction opens the HID interface with FILE_FLAG_OVERLAPPED so a
non-answering device can be cancelled safely instead of hanging the process.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import json
import sys
import time

sys.path.insert(0, "tools")
import hid_probe as hp  # noqa: E402

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
ERROR_IO_PENDING = 997
WAIT_TIMEOUT = 258
WAIT_OBJECT_0 = 0

kernel32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
kernel32.CreateFileW.restype = wt.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
kernel32.CreateEventW.restype = wt.HANDLE
kernel32.WriteFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, ctypes.c_void_p]
kernel32.WriteFile.restype = wt.BOOL
kernel32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, ctypes.c_void_p]
kernel32.ReadFile.restype = wt.BOOL
kernel32.GetOverlappedResult.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(wt.DWORD), wt.BOOL]
kernel32.GetOverlappedResult.restype = wt.BOOL
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.WaitForSingleObject.restype = wt.DWORD
kernel32.CancelIoEx.argtypes = [wt.HANDLE, ctypes.c_void_p]
kernel32.CancelIoEx.restype = wt.BOOL
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wt.DWORD),
        ("OffsetHigh", wt.DWORD),
        ("hEvent", wt.HANDLE),
    ]


def open_path(path):
    return kernel32.CreateFileW(
        path,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        FILE_FLAG_OVERLAPPED,
        None,
    )


def io_once(handle, data, size, timeout_ms, write):
    ev = kernel32.CreateEventW(None, True, False, None)
    if not ev:
        return None, ctypes.get_last_error()
    ov = OVERLAPPED()
    ov.hEvent = ev
    transferred = wt.DWORD()
    if write:
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        ok = kernel32.WriteFile(handle, buf, len(data), None, ctypes.byref(ov))
    else:
        buf = (ctypes.c_ubyte * size)()
        ok = kernel32.ReadFile(handle, buf, size, None, ctypes.byref(ov))
    if not ok:
        err = ctypes.get_last_error()
        if err != ERROR_IO_PENDING:
            kernel32.CloseHandle(ev)
            return None, err
        rc = kernel32.WaitForSingleObject(ev, timeout_ms)
        if rc != WAIT_OBJECT_0:
            kernel32.CancelIoEx(handle, ctypes.byref(ov))
            kernel32.WaitForSingleObject(ev, 200)
            kernel32.GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(transferred), False)
            kernel32.CloseHandle(ev)
            return None, WAIT_TIMEOUT
        if not kernel32.GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(transferred), False):
            err = ctypes.get_last_error()
            kernel32.CloseHandle(ev)
            return None, err
    kernel32.CloseHandle(ev)
    if write:
        return transferred.value, 0
    return bytes(buf[: transferred.value]), 0


def drain(handle, size, rounds=4):
    for _ in range(rounds):
        data, err = io_once(handle, b"", size, 10, False)
        if data is None or not data:
            return


def find_paths(vid, pid, usage_page=None, usage=None):
    out = []
    for path in hp.enum_hid():
        low = path.lower()
        if f"vid_{vid:04x}&pid_{pid:04x}" not in low:
            continue
        h = hp.open_hid(path)
        if h == hp.INVALID_HANDLE_VALUE:
            continue
        try:
            caps = hp.read_caps(h)
            if caps is None:
                continue
            if usage_page is not None and (caps.UsagePage != usage_page or caps.Usage != usage):
                continue
            out.append((path, caps))
        finally:
            kernel32.CloseHandle(h)
    return out


def fmt(data):
    return " ".join(f"{b:02X}" for b in data)


# ---------------------------------------------------------------- ATK A9
ATK_VID, ATK_PID = 0x373B, 0x11D9
ATK_USAGE_PAGE, ATK_USAGE = 0xFF02, 0x0002
ATK_REPORT_ID = 0x08
ATK_CMD_BATTERY = 0x04
ATK_CMD_GET_EEPROM = 0x08
ADDR_POLLING = 0x0000
ADDR_STAGE_COUNT = 0x0002
ADDR_CURRENT_STAGE = 0x0004
ADDR_DPI_VALUES = 0x000C

POLLING_VALUE_TO_HZ = {8: 125, 4: 250, 2: 500, 1: 1000, 0x10: 2000, 0x20: 4000, 0x40: 8000}


def atk_cmd(cmd, addr=0, data=b""):
    r = bytearray(17)
    r[0] = ATK_REPORT_ID
    r[1] = cmd
    r[3] = (addr >> 8) & 0xFF
    r[4] = addr & 0xFF
    r[5] = len(data)
    r[6:6 + len(data)] = data
    r[16] = (0x55 - (sum(r[:16]) & 0xFF)) & 0xFF
    return bytes(r)


def atk_transact(handle, cmd, addr=0, data=b"", timeout_ms=500):
    req = atk_cmd(cmd, addr, data)
    n, err = io_once(handle, req, 0, 500, True)
    if n is None:
        return None, f"write err={err}"
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        resp, err = io_once(handle, b"", 17, 80, False)
        if resp is None:
            continue
        if len(resp) >= 9 and resp[0] == ATK_REPORT_ID and resp[1] == cmd:
            if addr and (resp[3] != ((addr >> 8) & 0xFF) or resp[4] != (addr & 0xFF)):
                continue
            return resp, None
    return None, "no response"


def atk_eeprom_byte(handle, addr):
    resp, err = atk_transact(handle, ATK_CMD_GET_EEPROM, addr, b"\x01")
    if resp is None:
        return None, err
    return resp[6], None


def probe_atk():
    result = {"device": "ATK A9 Air", "vid": f"{ATK_VID:04X}", "pid": f"{ATK_PID:04X}"}
    found = find_paths(ATK_VID, ATK_PID, ATK_USAGE_PAGE, ATK_USAGE)
    if not found:
        result["error"] = "config interface not found"
        return result
    path, caps = found[0]
    result["interface"] = path
    result["caps"] = f"in={caps.InputReportByteLength} out={caps.OutputReportByteLength}"
    h = open_path(path)
    if h == hp.INVALID_HANDLE_VALUE:
        result["error"] = f"open err={ctypes.get_last_error()}"
        return result
    try:
        drain(h, 17)
        resp, err = atk_transact(h, ATK_CMD_BATTERY)
        if resp is None:
            result["battery_error"] = err
        else:
            result["battery"] = resp[6]
            result["wired"] = bool(resp[7])
            result["battery_raw"] = fmt(resp)
        stage, err = atk_eeprom_byte(h, ADDR_CURRENT_STAGE)
        result["stage_index"] = stage
        result["stage_error"] = err
        count, err = atk_eeprom_byte(h, ADDR_STAGE_COUNT)
        result["stage_count"] = count
        if stage is not None:
            low, e1 = atk_eeprom_byte(h, ADDR_DPI_VALUES + stage * 4)
            mult, e2 = atk_eeprom_byte(h, ADDR_DPI_VALUES + stage * 4 + 2)
            if low is not None and mult is not None:
                result["dpi"] = (low + 1) * 10 * ((mult & 0x0F) + 1)
            else:
                result["dpi_error"] = f"{e1}/{e2}"
        pv, err = atk_eeprom_byte(h, ADDR_POLLING)
        result["polling_raw"] = pv
        result["polling_hz"] = POLLING_VALUE_TO_HZ.get(pv) if pv is not None else None
    finally:
        kernel32.CloseHandle(h)
    return result


# ---------------------------------------------------------------- MCHOSE G87 V2
MCH_VID, MCH_PID = 0x3837, 0x3033
MCH_REQ = bytes([0x55, 0x03, 0x00, 0x38, 0x38, 0x00, 0x00, 0x00]) + bytes(56)


def probe_mchose():
    result = {"device": "MCHOSE G87 V2", "vid": f"{MCH_VID:04X}", "pid": f"{MCH_PID:04X}"}
    found = find_paths(MCH_VID, MCH_PID, 0x0001, 0x0000)
    if not found:
        result["error"] = "64-byte generic-desktop channel not found"
        return result
    path, caps = found[0]
    result["interface"] = path
    result["caps"] = f"in={caps.InputReportByteLength} out={caps.OutputReportByteLength}"
    h = open_path(path)
    if h == hp.INVALID_HANDLE_VALUE:
        result["error"] = f"open err={ctypes.get_last_error()}"
        return result
    try:
        drain(h, 65)
        n, err = io_once(h, b"\x00" + MCH_REQ, 0, 600, True)
        result["write"] = {"n": n, "err": err}
        for i in range(4):
            resp, err = io_once(h, b"", 65, 500, False)
            if resp is None:
                result[f"read{i}"] = f"err={err}"
                continue
            result[f"read{i}"] = fmt(resp[:24])
            if len(resp) >= 10 and resp[1] == 0xAA and resp[2] == 0x03 and resp[4] == 0x38:
                result["battery"] = resp[9]
                result["response"] = fmt(resp[:24])
                break
    finally:
        kernel32.CloseHandle(h)
    return result


# ---------------------------------------------------------------- MCHOSE V9 Pro 2
V9_VID, V9_PID = 0x3837, 0x6011


def probe_v9():
    result = {"device": "MCHOSE V9 Pro 2", "vid": f"{V9_VID:04X}", "pid": f"{V9_PID:04X}"}
    found = find_paths(V9_VID, V9_PID, 0xFF07, 0x0222)
    if not found:
        result["error"] = "FF07/0x0222 interface not found"
        return result
    path, caps = found[0]
    result["interface"] = path
    result["caps"] = f"in={caps.InputReportByteLength} out={caps.OutputReportByteLength} feature={caps.FeatureReportByteLength}"
    attempts = [
        ("64_55_65_01", bytes([0x55, 0x65, 0x01]) + bytes(61), 64),
        ("65_00_55_65_01", b"\x00" + bytes([0x55, 0x65, 0x01]) + bytes(61), 65),
        ("64_55_65_00", bytes([0x55, 0x65, 0x00]) + bytes(61), 64),
        ("64_55_65_02", bytes([0x55, 0x65, 0x02]) + bytes(61), 64),
    ]
    for label, req, read_size in attempts:
        h = open_path(path)
        if h == hp.INVALID_HANDLE_VALUE:
            result[label] = f"open err={ctypes.get_last_error()}"
            continue
        try:
            drain(h, read_size)
            n, err = io_once(h, req, 0, 600, True)
            item = {"write_n": n, "write_err": err}
            if n is not None:
                for i in range(3):
                    resp, rerr = io_once(h, b"", read_size, 500, False)
                    if resp is None:
                        item[f"read{i}"] = f"err={rerr}"
                        continue
                    item[f"read{i}"] = fmt(resp[:24])
                    if len(resp) >= 4 and resp[0] == 0x55 and resp[1] == 0x65:
                        item["battery"] = resp[2]
                        item["status"] = resp[3]
                        result["match"] = label
                        result.update(item)
                        return result
        finally:
            kernel32.CloseHandle(h)
        result[label] = item
    return result


# ---------------------------------------------------------------- generic dump
def probe_dump(name, vid, pid, usage_page=None, usage=None, seconds=3.0):
    result = {"device": name, "vid": f"{vid:04X}", "pid": f"{pid:04X}"}
    found = find_paths(vid, pid, usage_page, usage)
    if not found:
        result["error"] = "interface not found"
        return result
    path, caps = found[0]
    result["interface"] = path
    result["caps"] = f"in={caps.InputReportByteLength} out={caps.OutputReportByteLength} feature={caps.FeatureReportByteLength}"
    h = open_path(path)
    if h == hp.INVALID_HANDLE_VALUE:
        result["error"] = f"open err={ctypes.get_last_error()}"
        return result
    packets = []
    try:
        deadline = time.time() + seconds
        while time.time() < deadline and len(packets) < 8:
            data, err = io_once(h, b"", caps.InputReportByteLength, 300, False)
            if data:
                packets.append(fmt(data[:32]))
    finally:
        kernel32.CloseHandle(h)
    result["packets"] = packets
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--atk", action="store_true")
    ap.add_argument("--mchose", action="store_true")
    ap.add_argument("--v9", action="store_true")
    ap.add_argument("--8bitdo", action="store_true")
    args = ap.parse_args()
    selected = []
    if args.atk or not any([args.atk, args.mchose, args.v9, args.__dict__.get("8bitdo")]):
        selected.append(("atk", probe_atk))
    if args.mchose or not any([args.atk, args.mchose, args.v9, args.__dict__.get("8bitdo")]):
        selected.append(("mchose", probe_mchose))
    if args.v9 or not any([args.atk, args.mchose, args.v9, args.__dict__.get("8bitdo")]):
        selected.append(("v9", probe_v9))
    if args.__dict__.get("8bitdo") or not any([args.atk, args.mchose, args.v9, args.__dict__.get("8bitdo")]):
        selected.append(("8bitdo", lambda: probe_dump("8BitDo Orion 2 NS", 0x2DC8, 0x3109, 0x008C, 0x0001, 3.0)))
    for name, fn in selected:
        print("=" * 20, name)
        try:
            print(json.dumps(fn(), ensure_ascii=False, indent=2))
        except Exception as e:
            print(json.dumps({"device": name, "exception": repr(e)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
