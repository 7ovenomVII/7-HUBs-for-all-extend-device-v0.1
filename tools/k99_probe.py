"""Probe the MCHOSE 0x3837:0x3033 (G87 V2 / K99 V3) 64-byte vendor channel.

Read-only experiment: sends the documented K99 V3 battery query and prints
raw responses.  No UI, no persistence.
"""
import ctypes
import ctypes.wintypes as wt
import sys
import time

sys.path.insert(0, "tools")
import hid_probe as hp  # noqa: E402

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)

kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
kernel32.CreateEventW.restype = wt.HANDLE
kernel32.WriteFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
kernel32.WriteFile.restype = wt.BOOL
kernel32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
kernel32.ReadFile.restype = wt.BOOL
kernel32.GetOverlappedResult.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(wt.DWORD), wt.BOOL]
kernel32.GetOverlappedResult.restype = wt.BOOL
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.WaitForSingleObject.restype = wt.DWORD
kernel32.CancelIoEx.argtypes = [wt.HANDLE, ctypes.c_void_p]
kernel32.CancelIoEx.restype = wt.BOOL
kernel32.ResetEvent.argtypes = [wt.HANDLE]
kernel32.ResetEvent.restype = wt.BOOL

hid.HidD_SetOutputReport.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]
hid.HidD_SetOutputReport.restype = wt.BOOL
hid.HidD_GetInputReport.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]
hid.HidD_GetInputReport.restype = wt.BOOL


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_void_p),
        ("InternalHigh", ctypes.c_void_p),
        ("Offset", wt.DWORD),
        ("OffsetHigh", wt.DWORD),
        ("hEvent", wt.HANDLE),
    ]


def descriptor(handle):
    # hid.dll on this Windows build does not export HidD_GetReportDescriptor.
    # The repo fixture for this exact model declares a 64-byte report with no
    # report ID; the live descriptor is checked separately via IOCTL later.
    return None


def overlapped_write(handle, data, timeout_ms=1000):
    ev = kernel32.CreateEventW(None, True, False, None)
    ov = OVERLAPPED()
    ov.hEvent = ev
    written = wt.DWORD()
    buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    ok = kernel32.WriteFile(handle, buf, len(data), ctypes.byref(written), ctypes.byref(ov))
    if not ok:
        err = ctypes.get_last_error()
        if err != 997:  # ERROR_IO_PENDING
            kernel32.CloseHandle(ev)
            return False, 0, err
        rc = kernel32.WaitForSingleObject(ev, timeout_ms)
        if rc != 0:
            kernel32.CancelIoEx(handle, ctypes.byref(ov))
            kernel32.CloseHandle(ev)
            return False, 0, 1460  # WAIT_TIMEOUT
        if not kernel32.GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(written), False):
            err = ctypes.get_last_error()
            kernel32.CloseHandle(ev)
            return False, 0, err
    kernel32.CloseHandle(ev)
    return True, written.value, 0


def overlapped_read(handle, size, timeout_ms=500):
    ev = kernel32.CreateEventW(None, True, False, None)
    ov = OVERLAPPED()
    ov.hEvent = ev
    got = wt.DWORD()
    buf = (ctypes.c_ubyte * size)()
    ok = kernel32.ReadFile(handle, buf, size, ctypes.byref(got), ctypes.byref(ov))
    if not ok:
        err = ctypes.get_last_error()
        if err != 997:
            kernel32.CloseHandle(ev)
            return None, err
        rc = kernel32.WaitForSingleObject(ev, timeout_ms)
        if rc != 0:
            kernel32.CancelIoEx(handle, ctypes.byref(ov))
            kernel32.CloseHandle(ev)
            return None, 1460
        if not kernel32.GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(got), False):
            err = ctypes.get_last_error()
            kernel32.CloseHandle(ev)
            return None, err
    data = bytes(buf[: got.value])
    kernel32.CloseHandle(ev)
    return data, 0


def hexs(data):
    return " ".join(f"{b:02X}" for b in data)


def main():
    paths = []
    for path in hp.enum_hid():
        low = path.lower()
        if "vid_3837&pid_3033" in low:
            paths.append(path)
    print(f"found {len(paths)} interfaces")
    for path in sorted(paths):
        print("=" * 100)
        print(path)
        handle = hp.open_hid(path)
        if handle == hp.INVALID_HANDLE_VALUE:
            print(f"  open failed err={ctypes.get_last_error()}")
            continue
        try:
            caps = hp.read_caps(handle)
            if caps:
                print(
                    f"  usage_page=0x{caps.UsagePage:04X} usage=0x{caps.Usage:04X} "
                    f"in={caps.InputReportByteLength} out={caps.OutputReportByteLength} "
                    f"feature={caps.FeatureReportByteLength}"
                )
            desc = descriptor(handle)
            if desc:
                print(f"  report_desc[{len(desc)}]: {hexs(desc[:160])}")
        finally:
            kernel32.CloseHandle(handle)

    # Target the generic-desktop / usage-undefined 64-byte channel.
    target = next((p for p in paths if "mi_01" in p.lower()), None)
    if not target:
        print("mi_01 not found")
        return 1
    print("=" * 100)
    print("TARGET", target)
    handle = hp.open_hid(target)
    if handle == hp.INVALID_HANDLE_VALUE:
        print(f"open failed err={ctypes.get_last_error()}")
        return 1
    try:
        caps = hp.read_caps(handle)
        out_len = caps.OutputReportByteLength if caps else 65
        in_len = caps.InputReportByteLength if caps else 65
        req64 = bytes([0x55, 0x03, 0x00, 0x38, 0x38, 0x00, 0x00, 0x00]) + bytes(56)
        variants = [
            ("write64_no_id", req64),
            ("write65_id0", b"\x00" + req64),
            ("write65_id1", b"\x01" + req64),
        ]
        for name, payload in variants:
            print("-" * 100)
            print(f"{name}: len={len(payload)} {hexs(payload[:16])}")
            ok, n, err = overlapped_write(handle, payload, 1000)
            print(f"  write ok={ok} n={n} err={err}")
            if not ok:
                continue
            for i in range(5):
                data, rerr = overlapped_read(handle, in_len, 500)
                if data is None:
                    print(f"  read[{i}] err={rerr}")
                    if rerr == 1460:
                        break
                else:
                    print(f"  read[{i}] n={len(data)} {hexs(data[:32])}")
                    if len(data) >= 9 and data[0] == 0xAA:
                        print(f"  *** K99V3 response pct={data[8]} status=0x{data[6]:02X}")
                        return 0
        # Control-transfer fallback.
        for name, payload in [("setoutput65_id0", b"\x00" + req64), ("setoutput65_id1", b"\x01" + req64)]:
            print("-" * 100)
            print(f"{name}: len={len(payload)}")
            buf = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
            ok = hid.HidD_SetOutputReport(handle, buf, len(payload))
            print(f"  SetOutputReport ok={ok} err={ctypes.get_last_error()}")
            if ok:
                rbuf = (ctypes.c_ubyte * in_len)()
                ok2 = hid.HidD_GetInputReport(handle, rbuf, in_len)
                print(f"  GetInputReport ok={ok2} err={ctypes.get_last_error()} data={hexs(bytes(rbuf[:32]))}")
    finally:
        kernel32.CloseHandle(handle)
    return 0


if __name__ == "__main__":
    sys.exit(main())
