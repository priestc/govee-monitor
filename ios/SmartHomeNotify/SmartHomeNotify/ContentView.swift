import SwiftUI
import WidgetKit

private let appGroupDefaults = UserDefaults(suiteName: "group.io.github.priestc.SmartHomeNotify")!

struct ContentView: View {
    // Store URLs in the shared App Group so the widget extension can read them
    @AppStorage("localURL",     store: appGroupDefaults) private var localURL     = ""
    @AppStorage("tailscaleURL", store: appGroupDefaults) private var tailscaleURL = ""
    @State private var status: String? = nil
    @State private var isRegistering = false

    var body: some View {
        NavigationView {
            Form {
                Section(header: Text("Server"), footer: Text("Local is used when on home WiFi. Tailscale is used when away. Registration is attempted on both.")) {
                    TextField("192.168.1.231:5000", text: $localURL)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .listRowSeparator(.visible)
                    TextField("100.x.x.x:5000  (Tailscale IP)", text: $tailscaleURL)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }

                Section {
                    Button(action: registerDevice) {
                        if isRegistering {
                            HStack {
                                ProgressView()
                                Text("Registering…").padding(.leading, 8)
                            }
                        } else {
                            Text("Register for Notifications")
                        }
                    }
                    .disabled((localURL.isEmpty && tailscaleURL.isEmpty) || isRegistering)
                }

                if let status {
                    Section {
                        Text(status)
                            .font(.footnote)
                            .foregroundColor(status.hasPrefix("✓") ? .green : .red)
                    }
                }

                Section(header: Text("About")) {
                    Text("You'll receive a push notification when the smart home server detects you've left home.")
                        .font(.footnote)
                        .foregroundColor(.secondary)
                }
            }
            .navigationTitle("Smart Home")
        }
        .onReceive(NotificationCenter.default.publisher(for: .apnsTokenReceived)) { _ in
            if !localURL.isEmpty || !tailscaleURL.isEmpty {
                registerDevice()
            }
        }
    }

    private func normalizeURL(_ raw: String) -> String? {
        var s = raw.trimmingCharacters(in: .whitespaces)
        guard !s.isEmpty else { return nil }
        if !s.hasPrefix("http") { s = "http://" + s }
        if s.hasSuffix("/") { s = String(s.dropLast()) }
        return s
    }

    private func registerDevice() {
        guard let token = UserDefaults.standard.string(forKey: "apnsDeviceToken"), !token.isEmpty else {
            status = "No device token yet — make sure notifications are allowed in Settings."
            return
        }

        let candidates = [localURL, tailscaleURL].compactMap { normalizeURL($0) }
        guard !candidates.isEmpty else {
            status = "Enter at least one server URL."
            return
        }

        isRegistering = true
        status = nil

        let body = try? JSONSerialization.data(withJSONObject: ["token": token])
        let group = DispatchGroup()
        var successes: [String] = []
        var failures:  [String] = []
        let lock = NSLock()

        for urlStr in candidates {
            guard let url = URL(string: "\(urlStr)/api/register-push-token") else {
                lock.lock(); failures.append(urlStr); lock.unlock()
                continue
            }
            var request = URLRequest(url: url, timeoutInterval: 10)
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = body

            group.enter()
            URLSession.shared.dataTask(with: request) { _, response, error in
                lock.lock()
                if error == nil, let http = response as? HTTPURLResponse, http.statusCode == 200 {
                    successes.append(urlStr)
                } else {
                    failures.append(urlStr)
                }
                lock.unlock()
                group.leave()
            }.resume()
        }

        group.notify(queue: .main) {
            isRegistering = false
            if successes.isEmpty {
                status = "Could not reach any server. Check URLs and try again."
            } else if successes.count == candidates.count {
                status = "✓ Registered on all \(successes.count) server URL(s)."
            } else {
                status = "✓ Registered on \(successes.count) of \(candidates.count) URLs (local may be unreachable when away)."
            }
            WidgetCenter.shared.reloadAllTimelines()
        }
    }
}
