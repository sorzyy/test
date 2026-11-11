import MWDATCore
import SwiftUI

@main
struct LaoshiApp: App {
  @State private var glasses: GlassesController

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
        .onOpenURL { url in
          guard
            let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
            components.queryItems?.contains(where: { $0.name == "metaWearablesAction" }) == true
          else { return }
          Task {
            do {
              _ = try await Wearables.shared.handleUrl(url)
            } catch {
              glasses.report("Retour de Meta AI : \(error.localizedDescription)")
            }
          }
        }
    }
  }
}
