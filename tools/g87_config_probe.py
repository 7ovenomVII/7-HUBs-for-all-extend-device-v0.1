"""Read-only probe of the G87 V2 configuration channel.

Tries the CZ SDK "J / Channel:Keyboard" read commands documented by
eamonwey/BatteryViewer: cmd 4 (active config) and cmd 5 (profile header).
No writes to device settings.
"""
import sys
sys.path.insert(0, "tools")
import live_probe as lp
import hid_probe as hp


def request(cmd, size=56, offset=0):
    body = bytearray(64)
    body[0] = 0x55
    body[1] = cmd
    body[2] = 0x00
    body[3] = (size + offset) & 0xFF
    body[4] = size
    body[5] = offset & 0xFF
    body[6] = (offset >> 8) & 0xFF
    return b"\x00" + bytes(body)


def main():
    paths = lp.find_paths(0x3837, 0x3033, 0x0001, 0x0000)
    print("paths", len(paths))
    for path, caps in paths:
        if caps.OutputReportByteLength < 65 or caps.InputReportByteLength < 65:
            continue
        print("using", path, "out", caps.OutputReportByteLength, "in", caps.InputReportByteLength)
        h = lp.open_path(path)
        if h == hp.INVALID_HANDLE_VALUE:
            print("open failed", lp.ctypes.get_last_error())
            continue
        try:
            for cmd in (4, 5):
                lp.drain(h, 65)
                n, err = lp.io_once(h, request(cmd), 65, 600, True)
                print(f"cmd {cmd} write n={n} err={err}")
                for _ in range(3):
                    data, err = lp.io_once(h, b"", 65, 600, False)
                    if data:
                        print("  read", lp.fmt(data))
                        print("  data[32]", data[1 + 8 + 32] if len(data) > 41 else None,
                              "poll", data[1 + 8 + 1] if len(data) > 10 else None)
                        break
                    else:
                        print("  read err", err)
        finally:
            lp.kernel32.CloseHandle(h)


if __name__ == "__main__":
    main()
