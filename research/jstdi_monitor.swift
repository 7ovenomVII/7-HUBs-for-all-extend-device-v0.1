import Foundation
import IOKit.hid
import MCHOSECore

private let mchoseVendorID = 0x3837
private let g3V2WirelessProductID = 0x4245
private let g3V2WiredProductID = 0x418C
private let vendorUsagePage = 0xFF01
private let vendorUsage = 0x10
private let automaticRefreshInterval: TimeInterval = 3 * 60 * 60

private let deviceMatchedCallback: IOHIDDeviceCallback = { context, result, _, device in
    guard result == kIOReturnSuccess, let context else { return }
    let owner = Unmanaged<MCHOSEHIDMonitor>.fromOpaque(context).takeUnretainedValue()
    owner.deviceMatched(device)
}

private let deviceRemovedCallback: IOHIDDeviceCallback = { context, _, _, device in
    guard let context else { return }
    let owner = Unmanaged<MCHOSEHIDMonitor>.fromOpaque(context).takeUnretainedValue()
    owner.deviceRemoved(device)
}

private let inputReportCallback: IOHIDReportCallback = {
    context,
    result,
    _,
    _,
    _,
    report,
    reportLength in

    guard result == kIOReturnSuccess, let context, reportLength > 0 else { return }
    let owner = Unmanaged<MCHOSEHIDMonitor>.fromOpaque(context).takeUnretainedValue()
    let bytes = Array(UnsafeBufferPointer(start: report, count: reportLength))
    owner.receivedInputReport(bytes)
}

final class MCHOSEHIDMonitor {
    var onSnapshot: ((DeviceSnapshot) -> Void)?

    private(set) var snapshot = DeviceSnapshot() {
        didSet {
            if snapshot != oldValue {
                onSnapshot?(snapshot)
            }
        }
    }

    private let manager: IOHIDManager
    private var activeDevice: IOHIDDevice?
    private var activeConnection: ConnectionMode?
    private let reportBuffer: UnsafeMutablePointer<UInt8>
    private var refreshTimer: Timer?
    private var refreshInProgress = false
    private var refreshRequested = false
    private var pendingCommand: UInt8?
    private var pendingCompletion: (([UInt8]?) -> Void)?
    private var pendingTimeout: DispatchWorkItem?

    init() {
        manager = IOHIDManagerCreate(kCFAllocatorDefault, IOOptionBits(kIOHIDOptionsTypeNone))
        reportBuffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 64)
        reportBuffer.initialize(repeating: 0, count: 64)
    }

    deinit {
        stop()
        reportBuffer.deinitialize(count: 64)
        reportBuffer.deallocate()
    }

    func start() {
        let base: [String: Any] = [
            kIOHIDVendorIDKey as String: mchoseVendorID,
            kIOHIDPrimaryUsagePageKey as String: vendorUsagePage,
            kIOHIDPrimaryUsageKey as String: vendorUsage,
        ]
        var wireless = base
        wireless[kIOHIDProductIDKey as String] = g3V2WirelessProductID
        var wired = base
        wired[kIOHIDProductIDKey as String] = g3V2WiredProductID

        IOHIDManagerSetDeviceMatchingMultiple(manager, [wireless, wired] as CFArray)
        let context = Unmanaged.passUnretained(self).toOpaque()
        IOHIDManagerRegisterDeviceMatchingCallback(manager, deviceMatchedCallback, context)
        IOHIDManagerRegisterDeviceRemovalCallback(manager, deviceRemovedCallback, context)
        IOHIDManagerScheduleWithRunLoop(
            manager,
            CFRunLoopGetMain(),
            CFRunLoopMode.defaultMode.rawValue
        )

        let result = IOHIDManagerOpen(manager, IOOptionBits(kIOHIDOptionsTypeNone))
        if result != kIOReturnSuccess {
            snapshot.lastError = "无法打开 HID 管理器（\(formatIOReturn(result))）"
        }

        refreshTimer?.invalidate()
        refreshTimer = Timer.scheduledTimer(
            withTimeInterval: automaticRefreshInterval,
            repeats: true
        ) { [weak self] _ in
            self?.refreshNow()
        }
    }

    func stop() {
        refreshTimer?.invalidate()
        refreshTimer = nil
        cancelPendingQuery()
        detachActiveDevice()
        IOHIDManagerUnscheduleFromRunLoop(
            manager,
            CFRunLoopGetMain(),
            CFRunLoopMode.defaultMode.rawValue
        )
        IOHIDManagerClose(manager, IOOptionBits(kIOHIDOptionsTypeNone))
    }

    func refreshNow() {
        guard activeDevice != nil else {
            selectBestAvailableDevice()
            return
        }
        guard !refreshInProgress else {
            refreshRequested = true
            return
        }

        refreshInProgress = true
        query(MCHOSEProtocol.batteryQuery) { [weak self] batteryResponse in
            guard let self else { return }
            if let batteryResponse, let battery = MCHOSEProtocol.parseBattery(batteryResponse) {
                snapshot.battery = battery.level
                snapshot.isCharging = battery.charging
                snapshot.lastUpdated = Date()
                snapshot.lastError = nil
            }

            query(MCHOSEProtocol.configQuery) { [weak self] configResponse in
                guard let self else { return }
                if let configResponse, let config = MCHOSEProtocol.parseConfig(configResponse) {
                    snapshot.dpiIndex = config.index
                    snapshot.dpiValues = config.values
                    snapshot.lastUpdated = Date()
                    snapshot.lastError = nil
                } else if batteryResponse == nil {
                    snapshot.lastError = "设备暂未响应"
                }

                refreshInProgress = false
                if refreshRequested {
                    refreshRequested = false
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { [weak self] in
                        self?.refreshNow()
                    }
                }
            }
        }
    }

    fileprivate func deviceMatched(_ device: IOHIDDevice) {
        let connection = connectionMode(for: device)
        guard connection != nil else { return }

        if let activeConnection, activeConnection == .wired, connection == .wireless {
            return
        }
        if let activeDevice, CFEqual(activeDevice, device) {
            return
        }

        attach(device, connection: connection!)
    }

    fileprivate func deviceRemoved(_ device: IOHIDDevice) {
        guard let activeDevice, CFEqual(activeDevice, device) else { return }
        detachActiveDevice()
        snapshot = DeviceSnapshot(lastError: "设备已断开")
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { [weak self] in
            self?.selectBestAvailableDevice()
        }
    }

    fileprivate func receivedInputReport(_ bytes: [UInt8]) {
        if let battery = MCHOSEProtocol.parseBattery(bytes) {
            snapshot.battery = battery.level
            snapshot.isCharging = battery.charging
            snapshot.lastUpdated = Date()
            snapshot.lastError = nil
        }

        if let config = MCHOSEProtocol.parseConfig(bytes) {
            snapshot.dpiIndex = config.index
            snapshot.dpiValues = config.values
            snapshot.lastUpdated = Date()
            snapshot.lastError = nil
        } else if let index = MCHOSEProtocol.parseStatusDPIIndex(bytes) {
            snapshot.dpiIndex = index
            snapshot.lastUpdated = Date()
        }

        guard
            let pendingCommand,
            MCHOSEProtocol.isResponse(bytes, command: pendingCommand)
        else { return }

        let completion = pendingCompletion
        cancelPendingQuery()
        completion?(bytes)
    }

    private func attach(_ device: IOHIDDevice, connection: ConnectionMode) {
        detachActiveDevice()

        let result = IOHIDDeviceOpen(device, IOOptionBits(kIOHIDOptionsTypeNone))
        guard result == kIOReturnSuccess else {
            snapshot = DeviceSnapshot(lastError: "无法打开设备（\(formatIOReturn(result))）")
            return
        }

        activeDevice = device
        activeConnection = connection
        let context = Unmanaged.passUnretained(self).toOpaque()
        IOHIDDeviceRegisterInputReportCallback(
            device,
            reportBuffer,
            64,
            inputReportCallback,
            context
        )
        IOHIDDeviceScheduleWithRunLoop(
            device,
            CFRunLoopGetMain(),
            CFRunLoopMode.defaultMode.rawValue
        )

        snapshot = DeviceSnapshot(isConnected: true, connection: connection)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { [weak self] in
            self?.refreshNow()
        }
    }

    private func detachActiveDevice() {
        guard let activeDevice else { return }
        cancelPendingQuery()
        IOHIDDeviceUnscheduleFromRunLoop(
            activeDevice,
            CFRunLoopGetMain(),
            CFRunLoopMode.defaultMode.rawValue
        )
        IOHIDDeviceClose(activeDevice, IOOptionBits(kIOHIDOptionsTypeNone))
        self.activeDevice = nil
        activeConnection = nil
        refreshInProgress = false
    }

    private func selectBestAvailableDevice() {
        guard let deviceSet = IOHIDManagerCopyDevices(manager) as? Set<IOHIDDevice> else {
            snapshot = DeviceSnapshot(lastError: "未找到 MCHOSE G3 V2")
            return
        }

        let devices = Array(deviceSet)
        if let wired = devices.first(where: { connectionMode(for: $0) == .wired }) {
            attach(wired, connection: .wired)
        } else if let wireless = devices.first(where: { connectionMode(for: $0) == .wireless }) {
            attach(wireless, connection: .wireless)
        } else {
            snapshot = DeviceSnapshot(lastError: "未找到 MCHOSE G3 V2")
        }
    }

    private func connectionMode(for device: IOHIDDevice) -> ConnectionMode? {
        guard let productID = propertyInt(device, kIOHIDProductIDKey) else { return nil }
        switch productID {
        case g3V2WirelessProductID: return .wireless
        case g3V2WiredProductID: return .wired
        default: return nil
        }
    }

    private func query(_ bytes: [UInt8], completion: @escaping ([UInt8]?) -> Void) {
        guard let activeDevice else {
            completion(nil)
            return
        }
        guard pendingCommand == nil else {
            completion(nil)
            return
        }

        let command = bytes.count > 1 ? bytes[1] : 0
        let payload = MCHOSEProtocol.makeOutputPayload(bytes)
        let result = payload.withUnsafeBytes { rawBuffer in
            IOHIDDeviceSetReport(
                activeDevice,
                kIOHIDReportTypeOutput,
                0,
                rawBuffer.bindMemory(to: UInt8.self).baseAddress!,
                payload.count
            )
        }

        guard result == kIOReturnSuccess else {
            snapshot.lastError = "读取失败（\(formatIOReturn(result))）"
            completion(nil)
            return
        }

        pendingCommand = command
        pendingCompletion = completion
        let timeout = DispatchWorkItem { [weak self] in
            guard let self, pendingCommand == command else { return }
            let completion = pendingCompletion
            cancelPendingQuery()
            completion?(nil)
        }
        pendingTimeout = timeout
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5, execute: timeout)
    }

    private func cancelPendingQuery() {
        pendingTimeout?.cancel()
        pendingTimeout = nil
        pendingCommand = nil
        pendingCompletion = nil
    }

    private func propertyInt(_ device: IOHIDDevice, _ key: String) -> Int? {
        (IOHIDDeviceGetProperty(device, key as CFString) as? NSNumber)?.intValue
    }

    private func formatIOReturn(_ result: IOReturn) -> String {
        String(format: "0x%08X", UInt32(bitPattern: result))
    }
}
