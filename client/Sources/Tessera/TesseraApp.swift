import SwiftUI

@main
struct TesseraApp: App {
    @State private var engine = EngineController()

    var body: some Scene {
        WindowGroup("Tessera") {
            StatusView(engine: engine)
                .task { await engine.start() }
        }
        .windowResizability(.contentSize)
        .commands {
            CommandGroup(replacing: .newItem) {}
        }
    }
}
