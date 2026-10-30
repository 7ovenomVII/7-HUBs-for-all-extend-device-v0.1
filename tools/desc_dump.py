"""Dump HID report descriptors for selected vendors.

IOCTL_HID_GET_REPORT_DESCRIPTOR is used because HidD_GetReportDescriptor
is not exported by the hid.dll shipped on this machine.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import sys

import hid_probe

IOCTL_HID_GET_REPORT_DESCRIPTOR = 0x000B0000

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.DeviceIoControl.argtypes = [
    wt.HANDLE,
    wt.DWORD,
    ctypes.c_void_p,
    wt.DWORD,
    ctypes.c_void_p,
    wt.DWORD,
    ctypes.POINTER(wt.DWORD),
    ctypes.c_void_p,
]
_kernel32.DeviceIoControl.restype = wt.BOOL


def read_descriptor(path):
    handle = hid_probe.open_hid(path)
    if handle == hid_probe.INVALID_HANDLE_VALUE:
        return None, ctypes.get_last_error()
    try:
        buf = ctypes.create_string_buffer(4096)
        returned = wt.DWORD()
        ok = _kernel32.DeviceIoControl(
            handle,
            IOCTL_HID_GET_REPORT_DESCRIPTOR,
            None,
            0,
            buf,
            len(buf),
            ctypes.byref(returned),
            None,
        )
        if not ok:
            return None, ctypes.get_last_error()
        return buf.raw[: returned.value], 0
    finally:
        hid_probe.kernel32.CloseHandle(handle)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--filter", default="", help="comma separated hex VIDs")
    args = ap.parse_args()
    vids = {int(x, 16) for x in args.filter.split(",") if x.strip()}

    for path in hid_probe.enum_hid():
        info = hid_probe.probe_one(path)
        vid = info.get("vendor_id")
        if vids and vid not in vids:
            continue
        data, err = read_descriptor(path)
        print("=" * 100)
        print(f"VID={vid:04X} PID={info.get('product_id', 0):04X} "
              f"usage={info.get('usage_page')}:{info.get('usage')} "
              f"in={info.get('input_len')} out={info.get('output_len')} feature={info.get('feature_len')}")
        print(path)
        if data is None:
            print(f"  descriptor read failed err={err}")
            continue
        print(f"  length={len(data)}")
        for off in range(0, len(data), 32):
            chunk = data[off:off + 32]
            print(f"  {off:04X}: " + " ".join(f"{b:02X}" for b in chunk))


if __name__ == "__main__":
    sys.exit(main())
