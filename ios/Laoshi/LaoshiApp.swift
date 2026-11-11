import MWDATCore
import SwiftUI

@main
struct LaoshiApp: App {
  @State private var glasses: GlassesController
  @Environment(\.scenePhase) private var scenePhase

  init() {
    var configureError: String?
    do {
      try Wearables.configure()
    } catch {
      NSLog("[Laoshi] Impossible de configurer le SDK des lunettes : \(error)")
      configureError = error.localizedDescription
    }
    let controller = GlassesController(wearables: Wearables.shared)
    if let configureError {
      controller.report("Le SDK des lunettes n'a pas démarré : \(configureError)")
    }
    _glasses = State(wrappedValue: controller)
  }

  var body: some Scene {
    WindowGroup {
      ContentView(glasses: glasses)
        // Retour depuis l'app Meta AI après l'enregistrement / les permissions.
        .onOpenURL { url in glasses.handleOpenURL(url) }
        .onChange(of: scenePhase) { _, phase in
          if phase == .active {
            glasses.appBecameActive()
            glasses.vocabulary.refreshToday()
          }
          // Le texte du rappel (série, mots à réviser) est remis à jour en quittant l'app.
          if phase == .background { Reminders.reschedule(vocabulary: glasses.vocabulary) }
        }
    }
  }
}
