// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
// Native display and input for the actual ESP32-S3 machine. No HTML or WebView.

import AppKit
import Foundation

struct LCDFrame {
    static let width = 320
    static let height = 240
    let rgba: Data

    init?(_ message: Data) {
        guard message.count == 5 + Self.width * Self.height * 2 else { return nil }
        let bytes = [UInt8](message)
        guard bytes[0] == 1,
              Int(bytes[1]) | Int(bytes[2]) << 8 == Self.width,
              Int(bytes[3]) | Int(bytes[4]) << 8 == Self.height else { return nil }
        var pixels = [UInt8](repeating: 255, count: Self.width * Self.height * 4)
        for index in 0..<(Self.width * Self.height) {
            let source = 5 + index * 2
            let pixel = UInt16(bytes[source]) | UInt16(bytes[source + 1]) << 8
            let red = UInt8((pixel >> 11) & 31)
            let green = UInt8((pixel >> 5) & 63)
            let blue = UInt8(pixel & 31)
            pixels[index * 4] = (red << 3) | (red >> 2)
            pixels[index * 4 + 1] = (green << 2) | (green >> 4)
            pixels[index * 4 + 2] = (blue << 3) | (blue >> 2)
        }
        rgba = Data(pixels)
    }

    var image: CGImage? {
        guard let provider = CGDataProvider(data: rgba as CFData) else { return nil }
        return CGImage(width: Self.width, height: Self.height, bitsPerComponent: 8,
                       bitsPerPixel: 32, bytesPerRow: Self.width * 4,
                       space: CGColorSpaceCreateDeviceRGB(),
                       bitmapInfo: CGBitmapInfo(rawValue: CGImageAlphaInfo.noneSkipLast.rawValue)
                           .union(.byteOrder32Big),
                       provider: provider, decode: nil, shouldInterpolate: false,
                       intent: .defaultIntent)
    }

    static func point(_ point: NSPoint, in bounds: NSRect) -> (Int, Int)? {
        guard bounds.width > 0, bounds.height > 0,
              point.x >= bounds.minX, point.x < bounds.maxX,
              point.y >= bounds.minY, point.y < bounds.maxY else { return nil }
        return (Int((point.x - bounds.minX) * CGFloat(width) / bounds.width),
                Int((point.y - bounds.minY) * CGFloat(height) / bounds.height))
    }
}

@MainActor
final class MachineConnection {
    private struct Outbound {
        let text: String
        let serial: Bool
    }
    var onFrame: ((LCDFrame) -> Void)?
    var onSerial: ((String) -> Void)?
    var onTime: ((Double) -> Void)?
    var onConnection: ((Bool) -> Void)?
    private let url: URL
    private let session: URLSession
    private var socket: URLSessionWebSocketTask?
    private var receiver: Task<Void, Never>?
    private var sender: Task<Void, Never>?
    private var outgoing: [Outbound] = []
    private var connected = false
    private var generation = 0

    init(url: URL) {
        self.url = url
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 10
        session = URLSession(configuration: configuration)
    }

    func start() {
        receiver = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                generation += 1
                let current = session.webSocketTask(with: url)
                current.maximumMessageSize = 2 * 1024 * 1024
                socket = current
                current.resume()
                do {
                    while !Task.isCancelled {
                        let message = try await current.receive()
                        if !connected {
                            connected = true
                            onConnection?(true)
                        }
                        consume(message)
                    }
                } catch {
                    if !Task.isCancelled {
                        fputs("CoreS3 connection: \(error.localizedDescription)\n", stderr)
                    }
                }
                connected = false
                onConnection?(false)
                sender?.cancel()
                sender = nil
                outgoing.removeAll()
                current.cancel(with: .goingAway, reason: nil)
                socket = nil
                if Task.isCancelled { break }
                try? await Task.sleep(nanoseconds: 1_000_000_000)
            }
        }
    }

    func stop() {
        receiver?.cancel()
        sender?.cancel()
        socket?.cancel(with: .goingAway, reason: nil)
        session.invalidateAndCancel()
    }

    func send(_ fields: [String: Any]) {
        guard connected, let current = socket,
              let data = try? JSONSerialization.data(withJSONObject: fields),
              let text = String(data: data, encoding: .utf8) else { return }
        // A single sender preserves down/move/up and serial command ordering.
        guard outgoing.count < 256 else {
            current.cancel(with: .policyViolation, reason: nil)
            return
        }
        let kind = fields["t"] as? String
        outgoing.append(Outbound(text: text, serial: kind == "key" || kind == "serial"))
        guard sender == nil else { return }
        let startedGeneration = generation
        sender = Task { [weak self, weak current] in
            guard let self, let current else { return }
            defer { if generation == startedGeneration { sender = nil } }
            do {
                while !Task.isCancelled && generation == startedGeneration && !outgoing.isEmpty {
                    let message = outgoing.removeFirst()
                    try await current.send(.string(message.text))
                }
            } catch {
                current.cancel(with: .goingAway, reason: nil)
            }
        }
    }

    func discardQueuedSerial() {
        outgoing.removeAll { $0.serial }
        // A chunk already submitted to URLSession cannot be recalled. It is
        // never retried; the ordered reset message follows any such chunk.
    }

    private func consume(_ message: URLSessionWebSocketTask.Message) {
        switch message {
        case .data(let data):
            if let frame = LCDFrame(data) { onFrame?(frame) }
        case .string(let string):
            guard let data = string.data(using: .utf8),
                  let json = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
                  let type = json["t"] as? String else { return }
            if type == "serial", json["src"] as? String == "usb",
               let text = json["data"] as? String {
                onSerial?(text)
            } else if type == "stat", let time = json["time"] as? Double, time.isFinite {
                onTime?(time)
            }
        @unknown default: break
        }
    }
}

@MainActor
final class SerialInput {
    var send: (([String: Any]) -> Void)?
    private var chunks: [String] = []
    private var queuedBytes = 0
    private var nextWriteTime: Double?
    private var time: Double?
    private var connected = false

    func connection(_ connected: Bool) {
        self.connected = connected
        reset()
    }

    func reset() {
        chunks.removeAll()
        queuedBytes = 0
        nextWriteTime = nil
        time = nil
    }

    @discardableResult
    func enqueue(_ line: String) -> Bool {
        guard connected, !line.isEmpty, line.utf8.count <= 4096,
              !line.contains("\n"), !line.contains("\r"),
              queuedBytes + line.utf8.count + 1 <= 8192 else { return false }
        var chunk = ""
        var count = 0
        // Each WebSocket JSON string must remain valid UTF-8. A Unicode
        // scalar is at most four bytes, so none needs splitting at 64 bytes.
        for scalar in (line + "\n").unicodeScalars {
            let text = String(scalar)
            let bytes = text.utf8.count
            if count + bytes > 64 {
                chunks.append(chunk)
                chunk = ""
                count = 0
            }
            chunk.append(text)
            count += bytes
        }
        if !chunk.isEmpty { chunks.append(chunk) }
        queuedBytes += line.utf8.count + 1
        return true
    }

    func advance(_ value: Double) {
        if let time, value < time {
            // A machine restart discards an unfinished line, not just its
            // pacing deadline. Application commands are never replayed.
            reset()
        }
        time = value
        guard connected, !chunks.isEmpty,
              nextWriteTime.map({ value >= $0 }) ?? true else { return }
        let chunk = chunks.removeFirst()
        queuedBytes -= chunk.utf8.count
        send?(["t": "key", "src": "usb", "data": chunk])
        // At most one chunk per observed stat. Never catch up with a burst
        // after a delayed update: the physical USB FIFO is only 256 bytes.
        nextWriteTime = value + 0.025
    }
}

@MainActor
final class TouchInput {
    enum Phase { case idle, pressed, release, cancel }
    var send: (([String: Any]) -> Void)?
    private(set) var phase = Phase.idle
    private var point = (0, 0)
    private var time: Double?
    private var releaseTime: Double?
    private var connected = false

    func connection(_ connected: Bool) {
        self.connected = connected
        time = nil
        phase = .idle
        releaseTime = nil
        // A preceding client may have disappeared with a finger held down.
        // Move outside the display before releasing, through the actual FT.
        if connected { cancel(force: true) }
    }

    func begin(_ point: (Int, Int)) {
        guard connected, phase == .idle else { return }
        self.point = point
        phase = .pressed
        transmit(down: true)
    }

    func move(_ point: (Int, Int)) {
        guard phase == .pressed else { return }
        self.point = point
        transmit(down: true)
    }

    func end(_ point: (Int, Int)) {
        guard phase == .pressed else { return }
        move(point)
        phase = .release
        // Hold the final coordinate for several guest touch polls, including
        // quick host clicks and a last move delivered with the mouse-up event.
        releaseTime = time.map { $0 + 0.04 }
        finishIfDue()
    }

    func cancel(force: Bool = false) {
        guard connected, force || phase != .idle else { return }
        point = (0, 279) // FT6336 lower bezel, outside all 320x240 UI hitboxes.
        phase = .cancel
        releaseTime = time.map { $0 + 0.06 }
        transmit(down: true)
        // Wait for emulated time, not host wall time: the guest must observe
        // movement before release, including when emulation runs slowly.
    }

    func reset() {
        phase = .idle
        releaseTime = nil
        time = nil
    }

    func advance(_ value: Double) {
        if let time, value < time {
            // The physical reset button restarts the machine timebase.
            reset()
        }
        time = value
        if (phase == .release || phase == .cancel) && releaseTime == nil {
            releaseTime = value + (phase == .cancel ? 0.06 : 0.04)
        }
        finishIfDue()
    }

    private func finishIfDue() {
        guard phase == .release || phase == .cancel,
              let time, let releaseTime, time >= releaseTime else { return }
        transmit(down: false)
        phase = .idle
        self.releaseTime = nil
    }

    private func transmit(down: Bool) {
        send?(["t": "touch", "x": point.0, "y": point.1, "down": down ? 1 : 0])
    }
}

@MainActor
final class LCDView: NSView {
    var touch: TouchInput?
    private var lcd: NSImage?
    override var isFlipped: Bool { true }
    override var acceptsFirstResponder: Bool { true }
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    func display(_ frame: LCDFrame) {
        guard let image = frame.image else { return }
        lcd = NSImage(cgImage: image, size: NSSize(width: 320, height: 240))
        needsDisplay = true
    }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.black.setFill()
        bounds.fill()
        NSGraphicsContext.current?.imageInterpolation = .none
        lcd?.draw(in: bounds, from: .zero, operation: .copy, fraction: 1,
                  respectFlipped: true, hints: nil)
    }

    private func point(_ event: NSEvent) -> (Int, Int)? {
        LCDFrame.point(convert(event.locationInWindow, from: nil), in: bounds)
    }
    override func mouseDown(with event: NSEvent) {
        window?.makeFirstResponder(self)
        if let point = point(event) { touch?.begin(point) }
    }
    override func mouseDragged(with event: NSEvent) {
        if let point = point(event) { touch?.move(point) } else { touch?.cancel() }
    }
    override func mouseUp(with event: NSEvent) {
        if let point = point(event) { touch?.end(point) } else { touch?.cancel() }
    }
    override func cancelOperation(_ sender: Any?) { touch?.cancel() }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    private let connection: MachineConnection
    private let touch = TouchInput()
    private let serial = SerialInput()
    private let lcd = LCDView()
    private var window: NSWindow!
    private let resetButton = NSButton(title: "Reset", target: nil, action: nil)
    private let consoleButton = NSButton(checkboxWithTitle: "USB console", target: nil, action: nil)
    private let status = NSTextField(labelWithString: "●")
    private let output = NSTextView()
    private let input = NSTextField()
    private let console = NSStackView()
    private let scroll = NSScrollView()
    private var terminating = false
    private var receivedFrame = false

    init(url: URL) { connection = MachineConnection(url: url); super.init() }

    func applicationDidFinishLaunching(_ notification: Notification) {
        fputs("CoreS3: application finished launching\n", stderr)
        let menu = NSMenu()
        let applicationItem = NSMenuItem()
        menu.addItem(applicationItem)
        let applicationMenu = NSMenu()
        applicationMenu.addItem(withTitle: "Quit CoreS3", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        applicationItem.submenu = applicationMenu
        let editItem = NSMenuItem(title: "Edit", action: nil, keyEquivalent: "")
        let edit = NSMenu(title: "Edit")
        for (name, action, key) in [("Copy", "copy:", "c"), ("Paste", "paste:", "v"), ("Select All", "selectAll:", "a")] {
            edit.addItem(withTitle: name, action: NSSelectorFromString(action), keyEquivalent: key)
        }
        editItem.submenu = edit
        menu.addItem(editItem)
        NSApp.mainMenu = menu

        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 640, height: 520),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "M5CoreS3 SE"
        window.delegate = self
        window.isReleasedWhenClosed = false
        window.collectionBehavior = [.fullScreenNone]
        let content = NSStackView()
        content.orientation = .vertical
        content.alignment = .leading
        content.spacing = 0
        window.contentView = content

        resetButton.target = self
        resetButton.action = #selector(resetMachine)
        resetButton.bezelStyle = .rounded
        resetButton.isEnabled = false
        consoleButton.target = self
        consoleButton.action = #selector(toggleConsole)
        status.textColor = .systemGray
        status.toolTip = "Connecting"
        let spacer = NSView()
        let bar = NSStackView(views: [resetButton, consoleButton, spacer, status])
        bar.orientation = .horizontal
        bar.spacing = 12
        bar.edgeInsets = NSEdgeInsets(top: 6, left: 10, bottom: 6, right: 10)
        content.addArrangedSubview(bar)
        content.addArrangedSubview(lcd)
        content.addArrangedSubview(console)
        lcd.touch = touch
        lcd.widthAnchor.constraint(equalToConstant: 640).isActive = true
        lcd.heightAnchor.constraint(equalToConstant: 480).isActive = true
        bar.widthAnchor.constraint(equalTo: lcd.widthAnchor).isActive = true
        bar.heightAnchor.constraint(equalToConstant: 40).isActive = true

        console.orientation = .vertical
        console.alignment = .leading
        console.spacing = 6
        console.edgeInsets = NSEdgeInsets(top: 8, left: 10, bottom: 8, right: 10)
        // The console is detached when hidden; keep its dimensions local so
        // hiding it cannot remove a constraint held by the outer stack.
        console.widthAnchor.constraint(equalToConstant: 640).isActive = true
        console.heightAnchor.constraint(equalToConstant: 220).isActive = true
        output.isEditable = false
        output.isSelectable = true
        output.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        output.textColor = .textColor
        output.backgroundColor = .textBackgroundColor
        output.isVerticallyResizable = true
        output.isHorizontallyResizable = false
        output.frame = NSRect(x: 0, y: 0, width: 620, height: 170)
        output.minSize = NSSize(width: 0, height: 170)
        output.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        output.autoresizingMask = [.width]
        output.textContainer?.widthTracksTextView = true
        scroll.documentView = output
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        scroll.widthAnchor.constraint(equalToConstant: 620).isActive = true
        scroll.heightAnchor.constraint(equalToConstant: 170).isActive = true
        input.placeholderString = "USB command"
        input.target = self
        input.action = #selector(sendSerial)
        console.addArrangedSubview(scroll)
        console.addArrangedSubview(input)
        // Cross-view constraints require both views to have a common ancestor.
        input.widthAnchor.constraint(equalTo: scroll.widthAnchor).isActive = true
        console.isHidden = true

        touch.send = { [weak connection] fields in connection?.send(fields) }
        serial.send = { [weak connection] fields in connection?.send(fields) }
        connection.onFrame = { [weak self] frame in
            guard let self else { return }
            lcd.display(frame)
            if !receivedFrame {
                receivedFrame = true
                fputs("CoreS3: first 320x240 LCD frame received\n", stderr)
            }
        }
        connection.onSerial = { [weak self] text in self?.appendSerial(text) }
        connection.onTime = { [weak self] time in
            self?.touch.advance(time)
            self?.serial.advance(time)
            if let self, terminating && touch.phase == .idle { NSApp.reply(toApplicationShouldTerminate: true) }
        }
        connection.onConnection = { [weak self] connected in
            guard let self else { return }
            resetButton.isEnabled = connected
            input.isEnabled = connected
            status.textColor = connected ? .systemGreen : .systemOrange
            status.toolTip = connected ? "Connected" : "Disconnected; reconnecting"
            touch.connection(connected)
            serial.connection(connected)
        }
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
        fputs("CoreS3: native window shown\n", stderr)
        connection.start()
    }

    private func appendSerial(_ text: String) {
        guard let storage = output.textStorage else { return }
        let wasAtEnd = scroll.contentView.bounds.maxY >= output.bounds.maxY - 30
        storage.append(NSAttributedString(string: text, attributes: [
            .font: NSFont.monospacedSystemFont(ofSize: 11, weight: .regular),
            .foregroundColor: NSColor.textColor
        ]))
        if storage.length > 256_000 {
            storage.deleteCharacters(in: NSRange(location: 0, length: storage.length - 192_000))
        }
        if wasAtEnd { output.scrollToEndOfDocument(nil) }
    }

    @objc private func sendSerial() {
        let line = input.stringValue
        guard serial.enqueue(line) else { NSSound.beep(); return }
        input.stringValue = ""
    }

    @objc private func resetMachine() {
        touch.reset()
        serial.reset()
        connection.discardQueuedSerial()
        connection.send(["t": "reset"])
    }

    @objc private func toggleConsole() {
        let visible = consoleButton.state == .on
        console.isHidden = !visible
        let old = window.frame
        let newSize = NSSize(width: 640, height: visible ? 740 : 520)
        let frame = window.frameRect(forContentRect: NSRect(origin: .zero, size: newSize))
        window.setFrame(NSRect(x: old.minX, y: old.maxY - frame.height,
                               width: frame.width, height: frame.height), display: true, animate: true)
        if visible { window.makeFirstResponder(input) }
    }

    func windowDidResignKey(_ notification: Notification) { touch.cancel() }
    func applicationWillResignActive(_ notification: Notification) { touch.cancel() }
    func windowShouldClose(_ sender: NSWindow) -> Bool { NSApp.terminate(nil); return false }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard touch.phase != .idle else { return .terminateNow }
        terminating = true
        touch.cancel()
        // The launcher also stops its owned machine when this process exits.
        // Bound shutdown if the transport or guest has stopped advancing.
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            NSApp.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }
    func applicationWillTerminate(_ notification: Notification) { connection.stop() }
}

@MainActor
func selfTest() {
    var data = Data([1, 0x40, 1, 0xf0, 0])
    data.append(Data(repeating: 0, count: 320 * 240 * 2))
    data[5] = 0; data[6] = 0xf8
    data[7] = 0xe0; data[8] = 0x07
    data[data.count - 2] = 0x1f
    guard let frame = LCDFrame(data) else { fatalError("RGB565 frame rejected") }
    precondition(Array(frame.rgba.prefix(8)) == [255, 0, 0, 255, 0, 255, 0, 255])
    precondition(Array(frame.rgba.suffix(4)) == [0, 0, 255, 255])
    precondition(frame.image?.width == 320 && frame.image?.height == 240)
    precondition(LCDFrame(data.dropLast()) == nil)
    data[0] = 2
    precondition(LCDFrame(data) == nil)
    let bounds = NSRect(x: 0, y: 0, width: 640, height: 480)
    let first = LCDFrame.point(NSPoint(x: 0, y: 0), in: bounds)!
    let last = LCDFrame.point(NSPoint(x: 639, y: 479), in: bounds)!
    precondition(first.0 == 0 && first.1 == 0 && last.0 == 319 && last.1 == 239)
    precondition(LCDFrame.point(NSPoint(x: 640, y: 0), in: bounds) == nil)
    var touches: [[String: Any]] = []
    let touch = TouchInput()
    touch.send = { touches.append($0) }
    touch.connection(true)
    precondition(touches.last?["y"] as? Int == 279 && touches.last?["down"] as? Int == 1)
    touch.advance(1)
    touch.advance(1.05)
    precondition(touch.phase == .cancel)
    touch.advance(1.07)
    precondition(touch.phase == .idle && touches.last?["down"] as? Int == 0)
    touch.begin((80, 178))
    touch.end((80, 178))
    precondition(touch.phase == .release && touches.last?["down"] as? Int == 1)
    touch.advance(1.12)
    precondition(touch.phase == .idle && touches.last?["down"] as? Int == 0)
    touch.begin((238, 178))
    touch.cancel()
    precondition(touches.last?["y"] as? Int == 279 && touches.last?["down"] as? Int == 1)
    touch.advance(1.19)
    precondition(touch.phase == .idle && touches.last?["down"] as? Int == 0)
    let serial = SerialInput()
    var writes: [String] = []
    serial.send = { fields in
        precondition(fields["t"] as? String == "key" && fields["src"] as? String == "usb")
        writes.append(fields["data"] as! String)
    }
    serial.connection(true)
    let line = String(repeating: "é", count: 65) + "🪟"
    precondition(serial.enqueue(line))
    serial.advance(0)
    precondition(writes.count == 1)
    serial.advance(0.024)
    precondition(writes.count == 1)
    serial.advance(0.025)
    precondition(writes.count == 2)
    serial.advance(0.049)
    precondition(writes.count == 2)
    serial.advance(0.050)
    precondition(writes.count == 3 && writes.joined() == line + "\n")
    precondition(writes.allSatisfy { $0.utf8.count <= 64 })
    precondition(!serial.enqueue("two\ncommands"))
    precondition(serial.enqueue(String(repeating: "x", count: 150)))
    serial.advance(1)
    precondition(writes.count == 4) // A large time jump emits only one chunk.
    serial.reset()
    serial.advance(2)
    precondition(writes.count == 4)
    precondition(serial.enqueue(String(repeating: "y", count: 150)))
    serial.connection(false)
    precondition(!serial.enqueue("disconnected"))
    serial.connection(true)
    precondition(serial.enqueue("new"))
    serial.advance(0)
    precondition(writes.count == 5 && writes.last == "new\n")
    print("CoreS3 framebuffer, pointer, cancellation and serial pacing tests passed")
}

MainActor.assumeIsolated {
if CommandLine.arguments.contains("--self-test") {
    selfTest()
} else {
    var address = "ws://127.0.0.1:18079/ws"
    if let index = CommandLine.arguments.firstIndex(of: "--url"), index + 1 < CommandLine.arguments.count {
        address = CommandLine.arguments[index + 1]
    }
    guard let url = URL(string: address), ["ws", "wss"].contains(url.scheme ?? ""), url.host != nil else {
        fputs("Usage: CoreS3 [--url ws://127.0.0.1:18079/ws]\n", stderr)
        exit(2)
    }
    let application = NSApplication.shared
    let delegate = AppDelegate(url: url)
    application.setActivationPolicy(.regular)
    application.delegate = delegate
    // NSApplication.delegate is weak. Optimized builds may otherwise release
    // this local immediately after assignment, before launch notifications.
    withExtendedLifetime(delegate) {
        application.run()
    }
}
}
