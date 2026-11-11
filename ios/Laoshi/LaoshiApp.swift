import MWDATCore
import SwiftUI

@main
struct LaoshiApp: App {
  @State private var glasses: GlassesController
  @Environment(\.scenePhase) private var scenePhase

  init() {
    do {
      try Wearables.configure()
    } catch {
      NSLog("[Laoshi] Impossible de configurer le SDK des lunettes : \(error)")
    }
    _glasses = State(wrappedValue: GlassesController(wearables: Wearables.shared))
  }

  var body: some Scene {
    WindowGroup {
      ContentView(glasses: glasses)
        // Retour depuis l'app Meta AI après l'enregistrement / les permissions.
        .onOpenURL { url in glasses.handleOpenURL(url) }
        .onChange(of: scenePhase) { _, phase in
          if phase == .active { glasses.appBecameActive() }
        }
    }
  }
}
