import SwiftUI

@MainActor
final class SyncViewModel: ObservableObject {
    @Published var status = "Ready"
    @Published var running = false
    private var engine: SyncEngine?

    func sync() async {
        running = true; defer { running = false }
        do {
            if engine == nil { engine = SyncEngine(db: try Database()) }
            let sum = try await engine!.run { [weak self] msg in Task { @MainActor in self?.status = msg } }
            status = "Done. " + sum.text
        } catch {
            status = "Failed: \(error.localizedDescription)"
        }
    }
}

struct ContentView: View {
    @StateObject private var vm = SyncViewModel()

    var body: some View {
        VStack(spacing: 20) {
            Text("Spotify ⇄ Apple Music").font(.title2).bold()
            Text("Liked Songs ⇄ “Spotify Sync” playlist").foregroundStyle(.secondary)
            Button(vm.running ? "Syncing…" : "Sync now") { Task { await vm.sync() } }
                .buttonStyle(.borderedProminent).disabled(vm.running)
            Text(vm.status).font(.footnote).multilineTextAlignment(.center).padding()
        }
        .padding()
    }
}
