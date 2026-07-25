import SwiftUI
import Combine

private let garageAppGroupDefaults = UserDefaults(suiteName: "group.io.github.priestc.SmartHomeNotify")!

// MARK: - Models

struct GarageDoor: Codable, Identifiable {
    var id: String { name }
    let name: String
    let ip: String?
    let pulse_seconds: Double?
}

struct GarageStatus: Codable {
    let ok: Bool
    let door_closed: Bool?
    let last_opened: String?
    let last_closed: String?
    let error: String?
}

private struct TriggerResponse: Codable {
    let ok: Bool
    let error: String?
}

// MARK: - Store

@MainActor
final class GarageDoorsStore: ObservableObject {
    @Published var doors: [GarageDoor] = []
    @Published var statuses: [String: GarageStatus] = [:]
    @Published var triggering: Set<String> = []
    @Published var errorMessage: String? = nil
    @Published var isLoading = false

    private var refreshTimer: Timer?

    enum GarageError: LocalizedError {
        case noServer, unreachable

        var errorDescription: String? {
            switch self {
            case .noServer:    return "No server URL configured. Set one in Settings."
            case .unreachable: return "Could not reach the smart home server."
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

    private func candidateBaseURLs() -> [String] {
        let localURL     = garageAppGroupDefaults.string(forKey: "localURL")     ?? ""
        let tailscaleURL = garageAppGroupDefaults.string(forKey: "tailscaleURL") ?? ""
        return [localURL, tailscaleURL].compactMap(normalizeURL)
    }

    /// Tries each configured server URL in order (local first, then Tailscale) until one responds.
    private func request(path: String, method: String = "GET") async throws -> Data {
        let candidates = candidateBaseURLs()
        guard !candidates.isEmpty else { throw GarageError.noServer }

        var lastError: Error = GarageError.unreachable
        for base in candidates {
            guard let url = URL(string: base + path) else { continue }
            var req = URLRequest(url: url, timeoutInterval: 6)
            req.httpMethod = method
            do {
                let (data, response) = try await URLSession.shared.data(for: req)
                guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                    lastError = GarageError.unreachable
                    continue
                }
                return data
            } catch {
                lastError = error
                continue
            }
        }
        throw lastError
    }

    private func pathEncoded(_ name: String) -> String {
        name.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? name
    }

    func loadDoors() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let data = try await request(path: "/api/garage")
            doors = try JSONDecoder().decode([GarageDoor].self, from: data)
            errorMessage = nil
            await refreshAllStatuses()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func refreshAllStatuses() async {
        await withTaskGroup(of: Void.self) { group in
            for door in doors {
                group.addTask { await self.refreshStatus(for: door.name) }
            }
        }
    }

    func refreshStatus(for name: String) async {
        do {
            let data = try await request(path: "/api/garage/\(pathEncoded(name))/status")
            let status = try JSONDecoder().decode(GarageStatus.self, from: data)
            statuses[name] = status
            if !status.ok {
                errorMessage = status.error ?? "Could not read status for \(name)."
            }
        } catch {
            statuses[name] = GarageStatus(ok: false, door_closed: nil, last_opened: nil, last_closed: nil, error: error.localizedDescription)
            errorMessage = error.localizedDescription
        }
    }

    func trigger(_ name: String) async {
        triggering.insert(name)
        defer { triggering.remove(name) }
        do {
            let data = try await request(path: "/api/garage/\(pathEncoded(name))/trigger", method: "POST")
            let resp = try JSONDecoder().decode(TriggerResponse.self, from: data)
            if !resp.ok {
                errorMessage = resp.error ?? "Trigger failed for \(name)."
            }
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            await refreshStatus(for: name)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func startAutoRefresh() {
        stopAutoRefresh()
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 10, repeats: true) { [weak self] _ in
            Task { @MainActor in await self?.refreshAllStatuses() }
        }
    }

    func stopAutoRefresh() {
        refreshTimer?.invalidate()
        refreshTimer = nil
    }
}

// MARK: - View

struct GarageDoorsView: View {
    @StateObject private var store = GarageDoorsStore()

    var body: some View {
        NavigationView {
            Group {
                if store.doors.isEmpty && !store.isLoading && store.errorMessage == nil {
                    VStack(spacing: 8) {
                        Image(systemName: "door.garage.closed")
                            .font(.system(size: 40))
                            .foregroundColor(.secondary)
                        Text("No Garage Doors")
                            .font(.headline)
                        Text("Configure garage doors on the server with `smart-home configure-garage`.")
                            .font(.footnote)
                            .foregroundColor(.secondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 32)
                    }
                } else {
                    List {
                        if let errorMessage = store.errorMessage {
                            Section {
                                Text(errorMessage)
                                    .font(.footnote)
                                    .foregroundColor(.red)
                            }
                        }
                        ForEach(store.doors) { door in
                            GarageDoorRow(
                                door: door,
                                status: store.statuses[door.name],
                                isTriggering: store.triggering.contains(door.name),
                                onTrigger: { Task { await store.trigger(door.name) } }
                            )
                        }
                    }
                    .listStyle(.insetGrouped)
                    .refreshable { await store.loadDoors() }
                }
            }
            .navigationTitle("Garage Doors")
            .toolbar {
                if store.isLoading {
                    ToolbarItem(placement: .navigationBarTrailing) {
                        ProgressView()
                    }
                }
            }
        }
        .task {
            await store.loadDoors()
            store.startAutoRefresh()
        }
        .onDisappear {
            store.stopAutoRefresh()
        }
    }
}

private struct GarageDoorRow: View {
    let door: GarageDoor
    let status: GarageStatus?
    let isTriggering: Bool
    let onTrigger: () -> Void

    private var stateText: String {
        guard let status else { return "Loading…" }
        guard status.ok else { return "Unreachable" }
        switch status.door_closed {
        case true:  return "Closed"
        case false: return "Open"
        default:    return "Unknown"
        }
    }

    private var stateColor: Color {
        guard let status, status.ok else { return .secondary }
        switch status.door_closed {
        case true:  return .green
        case false: return .red
        default:    return .secondary
        }
    }

    private var actionLabel: String {
        guard let status, status.ok, let closed = status.door_closed else { return "Trigger" }
        return closed ? "Open" : "Close"
    }

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(door.name)
                    .font(.headline)
                Text(stateText)
                    .font(.subheadline)
                    .foregroundColor(stateColor)
            }
            Spacer()
            Button(action: onTrigger) {
                if isTriggering {
                    ProgressView()
                        .frame(width: 44)
                } else {
                    Text(actionLabel)
                        .frame(minWidth: 44)
                }
            }
            .buttonStyle(.borderedProminent)
            .disabled(isTriggering)
        }
        .padding(.vertical, 4)
    }
}
