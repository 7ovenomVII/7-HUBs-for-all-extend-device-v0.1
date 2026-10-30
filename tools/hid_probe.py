"""Read-only HID inventory / report probe for 7-HUBs.

Uses SetupAPI + hid.dll via ctypes, so it needs no third-party packages.
"""
import argparse
import ctypes
import ctypes.wintypes as wt
import sys

GUID_DEVINTERFACE_HID = "{4D1E55B2-F16F-11CF-88CB-001111000030}"
DIGCF_PRESENT = 0x02
DIGCF_DEVICEINTERFACE = 0x10
INVALID_HANDLE_VALUE = wt.HANDLE(-1).value
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x01
FILE_SHARE_WRITE = 0x02
OPEN_EXISTING = 3


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wt.DWORD),
        ("Data2", wt.WORD),
        ("Data3", wt.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("InterfaceClassGuid", GUID),
        ("Flags", wt.DWORD),
        ("Reserved", ctypes.c_void_p),
    ]


class SP_DEVICE_INTERFACE_DETAIL_DATA_W(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("DevicePath", ctypes.c_wchar * 1),
    ]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("Size", wt.ULONG),
        ("VendorID", wt.USHORT),
        ("ProductID", wt.USHORT),
        ("VersionNumber", wt.USHORT),
    ]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wt.USHORT),
        ("UsagePage", wt.USHORT),
        ("InputReportByteLength", wt.USHORT),
        ("OutputReportByteLength", wt.USHORT),
        ("FeatureReportByteLength", wt.USHORT),
        ("Reserved", wt.USHORT * 17),
        ("NumberLinkCollectionNodes", wt.USHORT),
        ("NumberInputButtonCaps", wt.USHORT),
        ("NumberInputValueCaps", wt.USHORT),
        ("NumberInputDataIndices", wt.USHORT),
        ("NumberOutputButtonCaps", wt.USHORT),
        ("NumberOutputValueCaps", wt.USHORT),
        ("NumberOutputDataIndices", wt.USHORT),
        ("NumberFeatureButtonCaps", wt.USHORT),
        ("NumberFeatureValueCaps", wt.USHORT),
        ("NumberFeatureDataIndices", wt.USHORT),
    ]


setupapi = ctypes.WinDLL("setupapi", use_last_error=True)
hid = ctypes.WinDLL("hid", use_last_error=True)

setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wt.LPCWSTR, wt.HWND, wt.DWORD]
setupapi.SetupDiGetClassDevsW.restype = wt.HANDLE
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [
    wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wt.DWORD, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)
]
setupapi.SetupDiEnumDeviceInterfaces.restype = wt.BOOL
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [
    wt.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA), ctypes.c_void_p, wt.DWORD,
    ctypes.POINTER(wt.DWORD), ctypes.c_void_p
]
setupapi.SetupDiGetDeviceInterfaceDetailW.restype = wt.BOOL
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wt.HANDLE]
setupapi.SetupDiDestroyDeviceInfoList.restype = wt.BOOL

hid.HidD_GetHidGuid.argtypes = [ctypes.POINTER(GUID)]
hid.HidD_GetAttributes.argtypes = [wt.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetAttributes.restype = wt.BOOL
hid.HidD_GetManufacturerString.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]
hid.HidD_GetManufacturerString.restype = wt.BOOL
hid.HidD_GetProductString.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]
hid.HidD_GetProductString.restype = wt.BOOL
hid.HidD_GetSerialNumberString.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]
hid.HidD_GetSerialNumberString.restype = wt.BOOL
hid.HidD_GetPreparsedData.argtypes = [wt.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_GetPreparsedData.restype = wt.BOOL
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidD_FreePreparsedData.restype = wt.BOOL
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidP_GetCaps.restype = wt.LONG
hid.HidD_GetFeature.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]
hid.HidD_GetFeature.restype = wt.BOOL

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateFileW.argtypes = [
    wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE
]
kernel32.CreateFileW.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CloseHandle.restype = wt.BOOL


def guid_from_string(s):
    g = GUID()
    ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(s), ctypes.byref(g))
    return g


def get_string(fn, handle, chars=256):
    buf = ctypes.create_unicode_buffer(chars)
    if fn(handle, buf, chars * 2):
        return buf.value
    return ""


def open_hid(path):
    return kernel32.CreateFileW(
        path,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_READ | FILE_SHARE_WRITE,
        None,
        OPEN_EXISTING,
        0,
        None,
    )


def read_caps(handle):
    preparsed = ctypes.c_void_p()
    if not hid.HidD_GetPreparsedData(handle, ctypes.byref(preparsed)):
        return None
    try:
        caps = HIDP_CAPS()
        if hid.HidP_GetCaps(preparsed, ctypes.byref(caps)) != 0x00110000:  # HIDP_STATUS_SUCCESS
            return None
        return caps
    finally:
        hid.HidD_FreePreparsedData(preparsed)


def enum_hid():
    guid = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(guid))
    info = setupapi.SetupDiGetClassDevsW(
        ctypes.byref(guid), None, None, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE
    )
    if info == INVALID_HANDLE_VALUE:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        index = 0
        while True:
            iface = SP_DEVICE_INTERFACE_DATA()
            iface.cbSize = ctypes.sizeof(iface)
            if not setupapi.SetupDiEnumDeviceInterfaces(
                info, None, ctypes.byref(guid), index, ctypes.byref(iface)
            ):
                err = ctypes.get_last_error()
                if err == 259:  # ERROR_NO_MORE_ITEMS
                    break
                raise ctypes.WinError(err)
            index += 1

            required = wt.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(
                info, ctypes.byref(iface), None, 0, ctypes.byref(required), None
            )
            buf = ctypes.create_string_buffer(required.value)
            ctypes.c_uint.from_address(ctypes.addressof(buf)).value = (
                8 if ctypes.sizeof(ctypes.c_void_p) == 8 else 6
            )
            if not setupapi.SetupDiGetDeviceInterfaceDetailW(
                info, ctypes.byref(iface), buf, required, None, None
            ):
                continue
            # DevicePath is a flexible WCHAR array at offset 4.  Reading it
            # through a c_wchar * 1 field only yields the first character,
            # so pull the full NUL-terminated string out of the raw buffer.
            yield ctypes.wstring_at(ctypes.addressof(buf) + 4)
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(info)


def ids_from_path(path):
    import re
    m = re.search(r"vid_([0-9a-f]{4})&pid_([0-9a-f]{4})", path, re.I)
    if m:
        return int(m.group(1), 16), int(m.group(2), 16)
    return None, None


def probe_one(path):
    path_vid, path_pid = ids_from_path(path)
    handle = open_hid(path)
    ok = handle != INVALID_HANDLE_VALUE
    if not ok:
        return {
            "path": path,
            "vendor_id": path_vid,
            "product_id": path_pid,
            "open_error": ctypes.get_last_error(),
        }
    try:
        attrs = HIDD_ATTRIBUTES()
        attrs.Size = ctypes.sizeof(attrs)
        if not hid.HidD_GetAttributes(handle, ctypes.byref(attrs)):
            attrs = None
        caps = read_caps(handle)
        return {
            "path": path,
            "vendor_id": attrs.VendorID if attrs else None,
            "product_id": attrs.ProductID if attrs else None,
            "version": attrs.VersionNumber if attrs else None,
            "manufacturer": get_string(hid.HidD_GetManufacturerString, handle),
            "product": get_string(hid.HidD_GetProductString, handle),
            "serial": get_string(hid.HidD_GetSerialNumberString, handle),
            "usage_page": caps.UsagePage if caps else None,
            "usage": caps.Usage if caps else None,
            "input_len": caps.InputReportByteLength if caps else None,
            "output_len": caps.OutputReportByteLength if caps else None,
            "feature_len": caps.FeatureReportByteLength if caps else None,
        }
    finally:
        kernel32.CloseHandle(handle)


def scan_features(path, feature_len, report_ids, show_zero=False):
    handle = open_hid(path)
    if handle == INVALID_HANDLE_VALUE:
        print(f"    open failed: {ctypes.get_last_error()}")
        return
    try:
        for rid in report_ids:
            buf = (ctypes.c_ubyte * feature_len)()
            buf[0] = rid
            ok = hid.HidD_GetFeature(handle, buf, feature_len)
            data = bytes(buf)
            if ok:
                if show_zero or any(data[1:]):
                    hexs = " ".join(f"{b:02X}" for b in data[:32])
                    print(f"    feature id={rid:02X} len={feature_len} -> {hexs}")
            else:
                err = ctypes.get_last_error()
                if show_zero:
                    print(f"    feature id={rid:02X} -> fail err={err}")
    finally:
        kernel32.CloseHandle(handle)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--filter", default="", help="comma separated hex VIDs, e.g. 3837,373B,2DC8")
    ap.add_argument("--read", action="store_true", help="scan feature report IDs 0..15")
    ap.add_argument("--all", action="store_true", help="show every HID interface")
    ap.add_argument("--show-zero", action="store_true")
    args = ap.parse_args()

    vids = {int(x, 16) for x in args.filter.split(",") if x.strip()}

    devices = []
    for path in enum_hid():
        info = probe_one(path)
        devices.append(info)

    for d in devices:
        vid = d.get("vendor_id")
        if vids and vid not in vids:
            continue
        if not args.all and vid is None and "open_error" not in d:
            continue
        print("=" * 100)
        print(d["path"])
        if "open_error" in d:
            print(f"  OPEN FAILED err={d['open_error']} (device may be in exclusive use)")
            continue
        print(f"  VID={d['vendor_id']:04X} PID={d['product_id']:04X} VER={d['version']:04X}")
        print(f"  manufacturer={d['manufacturer']!r} product={d['product']!r} serial={d['serial']!r}")
        print(
            f"  usage_page=0x{d['usage_page']:04X} usage=0x{d['usage']:04X} "
            f"in={d['input_len']} out={d['output_len']} feature={d['feature_len']}"
        )
        if args.read and d["feature_len"]:
            scan_features(d["path"], d["feature_len"], range(0, 16), args.show_zero)

    print("=" * 100)
    print(f"total HID interfaces: {len(devices)}")


if __name__ == "__main__":
    sys.exit(main())
