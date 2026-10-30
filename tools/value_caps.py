"""Enumerate HID value caps (usage page / usage / report id) for selected VIDs."""
import argparse
import ctypes
import ctypes.wintypes as wt
import sys

import hid_probe


class HIDP_VALUE_CAPS(ctypes.Structure):
    _fields_ = [
        ("UsagePage", wt.USHORT),
        ("ReportID", ctypes.c_ubyte),
        ("IsAlias", ctypes.c_ubyte),
        ("BitField", wt.USHORT),
        ("LinkCollection", wt.USHORT),
        ("LinkUsage", wt.USHORT),
        ("LinkUsagePage", wt.USHORT),
        ("IsRange", ctypes.c_ubyte),
        ("IsString", ctypes.c_ubyte),
        ("IsDesignator", ctypes.c_ubyte),
        ("Reserved", wt.ULONG * 10),
        ("Range", ctypes.c_ubyte * 16),
    ]


hid_probe.hid.HidP_GetValueCaps.argtypes = [
    ctypes.c_int,
    ctypes.POINTER(HIDP_VALUE_CAPS),
    ctypes.POINTER(wt.USHORT),
    ctypes.c_void_p,
]
hid_probe.hid.HidP_GetValueCaps.restype = wt.LONG


def caps_for(path, report_type, count):
    handle = hid_probe.open_hid(path)
    if handle == hid_probe.INVALID_HANDLE_VALUE:
        return None, ctypes.get_last_error()
    preparsed = ctypes.c_void_p()
    try:
        if not hid_probe.hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
            return None, ctypes.get_last_error()
        if count == 0:
            return [], 0
        arr = (HIDP_VALUE_CAPS * count)()
        length = wt.USHORT(count)
        status = hid_probe.hid.HidP_GetValueCaps(
            report_type, arr, ctypes.byref(length), preparsed
        )
        if status != 0x00110000:
            return None, status
        return [(arr[i].UsagePage, arr[i].ReportID,
                 int.from_bytes(bytes(arr[i].Range[0:2]), "little"),
                 int.from_bytes(bytes(arr[i].Range[2:4]), "little"))
                for i in range(length.value)], 0
    finally:
        if preparsed:
            hid_probe.hid.HidD_FreePreparsedData(preparsed)
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
        if info.get("usage_page") is None:
            continue
        print("=" * 100)
        print(f"VID={vid:04X} PID={info.get('product_id', 0):04X} "
              f"usage={info.get('usage_page')}:{info.get('usage')} "
              f"in={info.get('input_len')} out={info.get('output_len')} feature={info.get('feature_len')}")
        print(path)
        handle = hid_probe.open_hid(path)
        if handle == hid_probe.INVALID_HANDLE_VALUE:
            print(f"  open failed err={ctypes.get_last_error()}")
            continue
        preparsed = ctypes.c_void_p()
        try:
            if not hid_probe.hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
                print(f"  preparsed failed err={ctypes.get_last_error()}")
                continue
            caps = hid_probe.HIDP_CAPS()
            hid_probe.hid.HidP_GetCaps(preparsed, ctypes.byref(caps))
            for name, rt, count in (
                ("input", 0, caps.NumberInputValueCaps),
                ("output", 1, caps.NumberOutputValueCaps),
                ("feature", 2, caps.NumberFeatureValueCaps),
            ):
                if count == 0:
                    continue
                arr = (HIDP_VALUE_CAPS * count)()
                length = wt.USHORT(count)
                status = hid_probe.hid.HidP_GetValueCaps(rt, arr, ctypes.byref(length), preparsed)
                if status != 0x00110000:
                    print(f"  {name}: caps failed status=0x{status:08X}")
                    continue
                for i in range(length.value):
                    c = arr[i]
                    usage = int.from_bytes(bytes(c.Range[0:2]), "little")
                    usage_max = int.from_bytes(bytes(c.Range[2:4]), "little")
                    print(f"  {name}: page=0x{c.UsagePage:04X} usage=0x{usage:04X} "
                          f"max=0x{usage_max:04X} rid=0x{c.ReportID:02X} range={bool(c.IsRange)}")
        finally:
            if preparsed:
                hid_probe.hid.HidD_FreePreparsedData(preparsed)
            hid_probe.kernel32.CloseHandle(handle)


if __name__ == "__main__":
    sys.exit(main())
