import SwiftUI

@main
struct GPXVideoTrackerApp: App {
    @StateObject var model = AppModel()
    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
        }
        .windowStyle(.titleBar)
    }
}
