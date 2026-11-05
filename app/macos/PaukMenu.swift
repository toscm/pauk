// The pauk menu bar item (macOS): shows whether pauk runs and where, restarts
// it from the menu or with Ctrl+Option+Cmd+P. Built and started by
// `pauk service install`; restarting means `launchctl kickstart -k` on the
// login service local.pauk.server.

import AppKit
import Carbon.HIToolbox

let home = ProcessInfo.processInfo.environment["PAUK_HOME"] ?? NSHomeDirectory() + "/pauk"
let service = "gui/\(getuid())/local.pauk.server"

// `listen: host:port` from config.yaml (no YAML library needed for one line)
func listen() -> (host: String, port: String) {
    let text = (try? String(contentsOfFile: home + "/config.yaml", encoding: .utf8)) ?? ""
    for line in text.split(separator: "\n") where line.hasPrefix("listen:") {
        let value = line.dropFirst(7).split(separator: "#")[0].trimmingCharacters(in: .whitespaces)
        let parts = value.split(separator: ":").map(String.init)
        if parts.count == 2 { return (parts[0], parts[1]) }
    }
    return ("127.0.0.1", "8765")
}

// the Mac's IPv4 addresses in the LAN
func lanAddresses() -> [String] {
    var out: [String] = []
    var list: UnsafeMutablePointer<ifaddrs>?
    guard getifaddrs(&list) == 0 else { return out }
    defer { freeifaddrs(list) }
    var p = list
    while let a = p?.pointee {
        if a.ifa_addr.pointee.sa_family == UInt8(AF_INET), a.ifa_flags & UInt32(IFF_LOOPBACK) == 0 {
            var buf = [CChar](repeating: 0, count: Int(NI_MAXHOST))
            getnameinfo(a.ifa_addr, socklen_t(a.ifa_addr.pointee.sa_len), &buf, socklen_t(buf.count), nil, 0, NI_NUMERICHOST)
            out.append(String(cString: buf))
        }
        p = a.ifa_next
    }
    return out
}

final class Menu: NSObject, NSMenuDelegate {
    let item = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
    let menu = NSMenu()
    var running = false
    var hotKey: EventHotKeyRef?

    override init() {
        super.init()
        menu.delegate = self
        item.menu = menu
        update(false)
        Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in self?.check() }
        check()
        registerHotKey()
    }

    // pauk runs if its port answers HTTP at all (an unauthorized answer counts)
    func check() {
        let url = URL(string: "http://127.0.0.1:\(listen().port)/api/me")!
        var req = URLRequest(url: url)
        req.timeoutInterval = 2
        URLSession.shared.dataTask(with: req) { _, response, _ in
            DispatchQueue.main.async { self.update(response != nil) }
        }.resume()
    }

    func update(_ up: Bool) {
        running = up
        let image = NSImage(systemSymbolName: up ? "graduationcap.fill" : "graduationcap", accessibilityDescription: "pauk")
        image?.isTemplate = true
        item.button?.image = image
        item.button?.appearsDisabled = !up
    }

    // the address to give out: the LAN address when pauk serves the LAN
    func url() -> String {
        let (host, port) = listen()
        return "http://\(host == "0.0.0.0" ? lanAddresses().first ?? "127.0.0.1" : host):\(port)"
    }

    // rebuilt each time the menu opens, so it is always current
    func menuNeedsUpdate(_ menu: NSMenu) {
        menu.removeAllItems()
        menu.autoenablesItems = false
        let add = { (title: String, action: Selector?) in
            let item = menu.addItem(withTitle: title, action: action, keyEquivalent: "")
            item.target = self
            return item
        }
        // a line to read, not to click, but in the normal text colour
        let status = add(running ? "pauk is running at \(url())" : "pauk is not running", nil)
        status.isEnabled = false
        status.attributedTitle = NSAttributedString(string: status.title, attributes: [.foregroundColor: NSColor.labelColor, .font: NSFont.menuFont(ofSize: 0)])
        menu.addItem(.separator())
        if running {
            _ = add("Copy URL", #selector(copyURL))
            _ = add("Open URL", #selector(openURL))
            menu.addItem(.separator())
        }
        let restart = add(running ? "Restart pauk" : "Start pauk", #selector(restart))
        restart.keyEquivalent = "p"
        restart.keyEquivalentModifierMask = [.control, .option, .command]
        _ = add("Show log", #selector(showLog))
        menu.addItem(.separator())
        if running { _ = add("Quit pauk", #selector(quitPauk)) }
        _ = add("Quit this menu", #selector(quit))
    }

    @objc func copyURL() {
        NSPasteboard.general.clearContents()
        NSPasteboard.general.setString(url(), forType: .string)
    }

    @objc func openURL() {
        NSWorkspace.shared.open(URL(string: url())!)
    }

    @discardableResult
    func launchctl(_ args: [String]) -> Int32 {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        p.arguments = args
        try? p.run()
        p.waitUntilExit()
        return p.terminationStatus
    }

    // restart the service, or load it again after "Quit pauk"
    @objc func restart() {
        update(false)
        if launchctl(["kickstart", "-k", service]) != 0,
           launchctl(["bootstrap", "gui/\(getuid())", NSHomeDirectory() + "/Library/LaunchAgents/local.pauk.server.plist"]) != 0 {
            let alert = NSAlert()
            alert.messageText = "The pauk service is not installed."
            alert.informativeText = "Run `pauk service install` in a terminal."
            alert.runModal()
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { self.check() }
    }

    // stop pauk until "Start pauk" or the next login
    @objc func quitPauk() {
        launchctl(["bootout", service])
        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { self.check() }
    }

    @objc func showLog() {
        NSWorkspace.shared.open(URL(fileURLWithPath: home + "/server.log"))
    }

    @objc func quit() {
        // launchd would start the menu again right away; bootout stops it until the next login
        launchctl(["bootout", "gui/\(getuid())/local.pauk.menu"])
        NSApp.terminate(nil)
    }

    // Ctrl+Option+Cmd+P anywhere: the Carbon hot-key API needs no
    // Accessibility permission
    func registerHotKey() {
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let me = Unmanaged.passUnretained(self).toOpaque()
        InstallEventHandler(GetApplicationEventTarget(), { _, _, data in
            Unmanaged<Menu>.fromOpaque(data!).takeUnretainedValue().restart()
            return noErr
        }, 1, &spec, me, nil)
        let id = EventHotKeyID(signature: OSType(0x7061_756B), id: 1)   // "pauk"
        RegisterEventHotKey(UInt32(kVK_ANSI_P), UInt32(controlKey | optionKey | cmdKey), id, GetApplicationEventTarget(), 0, &hotKey)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)   // a menu bar item only: no Dock icon, no window
let menu = Menu()
app.run()
