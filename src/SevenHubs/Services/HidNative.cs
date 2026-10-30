using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace SevenHubs.Services;

public sealed class HidDeviceInfo
{
    public string Path { get; init; } = "";
    public ushort VendorId { get; init; }
    public ushort ProductId { get; init; }
    public ushort Version { get; init; }
    public string Manufacturer { get; init; } = "";
    public string Product { get; init; } = "";
    public string Serial { get; init; } = "";
    public ushort UsagePage { get; init; }
    public ushort Usage { get; init; }
    public ushort InputReportLength { get; init; }
    public ushort OutputReportLength { get; init; }
    public ushort FeatureReportLength { get; init; }

    public bool IsVendorDefined => UsagePage >= 0xFF00;
    public string Key => $"{VendorId:X4}:{ProductId:X4}";
    public override string ToString() => $"{VendorId:X4}:{ProductId:X4} {UsagePage:X4}/{Usage:X4} {Product}";
}

public sealed class HidConnection : IDisposable
{
    private readonly FileStream _stream;

    private HidConnection(FileStream stream) => _stream = stream;

    public static HidConnection? Open(string path)
    {
        try
        {
            var stream = new FileStream(
                path,
                FileMode.Open,
                FileAccess.ReadWrite,
                FileShare.ReadWrite,
                4096,
                FileOptions.Asynchronous);
            return new HidConnection(stream);
        }
        catch
        {
            return null;
        }
    }

    public bool Write(byte[] report, int timeoutMs = 600)
    {
        try
        {
            var task = _stream.WriteAsync(report, 0, report.Length);
            return task.Wait(timeoutMs);
        }
        catch
        {
            return false;
        }
    }

    public byte[]? Read(int length, int timeoutMs = 600)
    {
        try
        {
            var buffer = new byte[length];
            var task = _stream.ReadAsync(buffer, 0, buffer.Length);
            if (!task.Wait(timeoutMs))
                return null;
            var read = task.Result;
            if (read <= 0)
                return null;
            if (read == buffer.Length)
                return buffer;
            var trimmed = new byte[read];
            Array.Copy(buffer, trimmed, read);
            return trimmed;
        }
        catch
        {
            return null;
        }
    }

    public byte[]? GetFeature(byte reportId, int length)
    {
        try
        {
            var buffer = new byte[length];
            buffer[0] = reportId;
            using var handle = HidNative.OpenHandle(_stream.SafeFileHandle.DangerousGetHandle(), _stream.Name);
            if (handle.IsInvalid)
                return null;
            return HidNative.HidD_GetFeature(handle, buffer, buffer.Length) ? buffer : null;
        }
        catch
        {
            return null;
        }
    }

    public void Dispose() => _stream.Dispose();
}

public static class HidNative
{
    private const uint GENERIC_READ = 0x80000000;
    private const uint GENERIC_WRITE = 0x40000000;
    private const uint FILE_SHARE_READ = 0x00000001;
    private const uint FILE_SHARE_WRITE = 0x00000002;
    private const uint OPEN_EXISTING = 3;
    private const uint FILE_FLAG_OVERLAPPED = 0x40000000;
    private const int DIGCF_PRESENT = 0x00000002;
    private const int DIGCF_DEVICEINTERFACE = 0x00000010;

    [StructLayout(LayoutKind.Sequential)]
    private struct SP_DEVICE_INTERFACE_DATA
    {
        public int cbSize;
        public Guid InterfaceClassGuid;
        public int Flags;
        public IntPtr Reserved;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct HIDD_ATTRIBUTES
    {
        public int Size;
        public ushort VendorID;
        public ushort ProductID;
        public ushort VersionNumber;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct HIDP_CAPS
    {
        public ushort Usage;
        public ushort UsagePage;
        public ushort InputReportByteLength;
        public ushort OutputReportByteLength;
        public ushort FeatureReportByteLength;
        [MarshalAs(UnmanagedType.ByValArray, SizeConst = 17)]
        public ushort[] Reserved;
        public ushort NumberLinkCollectionNodes;
        public ushort NumberInputButtonCaps;
        public ushort NumberInputValueCaps;
        public ushort NumberInputDataIndices;
        public ushort NumberOutputButtonCaps;
        public ushort NumberOutputValueCaps;
        public ushort NumberOutputDataIndices;
        public ushort NumberFeatureButtonCaps;
        public ushort NumberFeatureValueCaps;
        public ushort NumberFeatureDataIndices;
    }

    [DllImport("hid.dll")]
    private static extern void HidD_GetHidGuid(out Guid hidGuid);

    [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr SetupDiGetClassDevs(ref Guid classGuid, IntPtr enumerator, IntPtr hwndParent, int flags);

    [DllImport("setupapi.dll", SetLastError = true)]
    private static extern bool SetupDiEnumDeviceInterfaces(IntPtr deviceInfoSet, IntPtr deviceInfoData, ref Guid interfaceClassGuid, int memberIndex, ref SP_DEVICE_INTERFACE_DATA deviceInterfaceData);

    [DllImport("setupapi.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool SetupDiGetDeviceInterfaceDetail(IntPtr deviceInfoSet, ref SP_DEVICE_INTERFACE_DATA deviceInterfaceData, IntPtr deviceInterfaceDetailData, int deviceInterfaceDetailDataSize, ref int requiredSize, IntPtr deviceInfoData);

    [DllImport("setupapi.dll", SetLastError = true)]
    private static extern bool SetupDiDestroyDeviceInfoList(IntPtr deviceInfoSet);

    [DllImport("hid.dll", SetLastError = true)]
    private static extern bool HidD_GetAttributes(SafeFileHandle hidDeviceObject, ref HIDD_ATTRIBUTES attributes);

    [DllImport("hid.dll", SetLastError = true)]
    private static extern bool HidD_GetPreparsedData(SafeFileHandle hidDeviceObject, out IntPtr preparsedData);

    [DllImport("hid.dll")]
    private static extern bool HidD_FreePreparsedData(IntPtr preparsedData);

    [DllImport("hid.dll")]
    private static extern int HidP_GetCaps(IntPtr preparsedData, ref HIDP_CAPS capabilities);

    [DllImport("hid.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool HidD_GetManufacturerString(SafeFileHandle hidDeviceObject, IntPtr buffer, int bufferLength);

    [DllImport("hid.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool HidD_GetProductString(SafeFileHandle hidDeviceObject, IntPtr buffer, int bufferLength);

    [DllImport("hid.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool HidD_GetSerialNumberString(SafeFileHandle hidDeviceObject, IntPtr buffer, int bufferLength);

    [DllImport("hid.dll", SetLastError = true)]
    internal static extern bool HidD_GetFeature(SafeFileHandle hidDeviceObject, byte[] reportBuffer, int reportBufferLength);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern SafeFileHandle CreateFile(
        string fileName,
        uint desiredAccess,
        uint shareMode,
        IntPtr securityAttributes,
        uint creationDisposition,
        uint flagsAndAttributes,
        IntPtr templateFile);

    internal static SafeFileHandle OpenHandle(IntPtr existingHandle, string name)
    {
        return CreateFile(name, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, IntPtr.Zero, OPEN_EXISTING, 0, IntPtr.Zero);
    }

    public static IReadOnlyList<HidDeviceInfo> Enumerate()
    {
        var result = new List<HidDeviceInfo>();
        HidD_GetHidGuid(out var hidGuid);
        var set = SetupDiGetClassDevs(ref hidGuid, IntPtr.Zero, IntPtr.Zero, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
        if (set == IntPtr.Zero || set == new IntPtr(-1))
            return result;

        try
        {
            var interfaceData = new SP_DEVICE_INTERFACE_DATA
            {
                cbSize = Marshal.SizeOf<SP_DEVICE_INTERFACE_DATA>()
            };

            for (var index = 0; ; index++)
            {
                if (!SetupDiEnumDeviceInterfaces(set, IntPtr.Zero, ref hidGuid, index, ref interfaceData))
                    break;

                int requiredSize = 0;
                SetupDiGetDeviceInterfaceDetail(set, ref interfaceData, IntPtr.Zero, 0, ref requiredSize, IntPtr.Zero);
                if (requiredSize <= 0)
                    continue;

                var detailBuffer = Marshal.AllocHGlobal(requiredSize);
                try
                {
                    // SP_DEVICE_INTERFACE_DETAIL_DATA_W is byte-packed: DWORD cbSize + WCHAR DevicePath[].
                    Marshal.WriteInt32(detailBuffer, 0, IntPtr.Size == 8 ? 8 : 6);
                    if (!SetupDiGetDeviceInterfaceDetail(set, ref interfaceData, detailBuffer, requiredSize, ref requiredSize, IntPtr.Zero))
                        continue;

                    var path = Marshal.PtrToStringUni(IntPtr.Add(detailBuffer, 4));
                    if (string.IsNullOrWhiteSpace(path))
                        continue;

                    var info = ReadInfo(path);
                    if (info is not null)
                        result.Add(info);
                }
                finally
                {
                    Marshal.FreeHGlobal(detailBuffer);
                }
            }
        }
        finally
        {
            SetupDiDestroyDeviceInfoList(set);
        }

        return result;
    }

    private static HidDeviceInfo? ReadInfo(string path)
    {
        using var handle = CreateFile(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, IntPtr.Zero, OPEN_EXISTING, 0, IntPtr.Zero);
        if (handle.IsInvalid)
            return null;

        var attributes = new HIDD_ATTRIBUTES { Size = Marshal.SizeOf<HIDD_ATTRIBUTES>() };
        if (!HidD_GetAttributes(handle, ref attributes))
            return null;

        if (!HidD_GetPreparsedData(handle, out var preparsedData))
            return null;

        HIDP_CAPS caps;
        try
        {
            caps = new HIDP_CAPS { Reserved = new ushort[17] };
            if (HidP_GetCaps(preparsedData, ref caps) != 0x00110000) // HIDP_STATUS_SUCCESS
                return null;
        }
        finally
        {
            HidD_FreePreparsedData(preparsedData);
        }

        return new HidDeviceInfo
        {
            Path = path,
            VendorId = attributes.VendorID,
            ProductId = attributes.ProductID,
            Version = attributes.VersionNumber,
            Manufacturer = GetString(handle, HidD_GetManufacturerString),
            Product = GetString(handle, HidD_GetProductString),
            Serial = GetString(handle, HidD_GetSerialNumberString),
            UsagePage = caps.UsagePage,
            Usage = caps.Usage,
            InputReportLength = caps.InputReportByteLength,
            OutputReportLength = caps.OutputReportByteLength,
            FeatureReportLength = caps.FeatureReportByteLength
        };
    }

    private static string GetString(SafeFileHandle handle, Func<SafeFileHandle, IntPtr, int, bool> getter)
    {
        var buffer = Marshal.AllocHGlobal(512);
        try
        {
            if (!getter(handle, buffer, 512))
                return "";
            var value = Marshal.PtrToStringUni(buffer);
            return value?.TrimEnd('\0') ?? "";
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }
}
