import Foundation
import UserNotifications

/// Rappel quotidien : une notification à l'heure choisie, avec la série et les mots à réviser.
/// Le texte est recalculé à chaque passage dans l'app (une notification ne peut pas se mettre
/// à jour toute seule).
@MainActor
enum Reminders {
  private static let identifier = "laoshi.daily"

  static var enabled: Bool {
    get { UserDefaults.standard.bool(forKey: "reminder.enabled") }
    set { UserDefaults.standard.set(newValue, forKey: "reminder.enabled") }
  }

  /// Heure du rappel (par défaut 19 h).
  static var time: Date {
    get {
      if let saved = UserDefaults.standard.object(forKey: "reminder.time") as? Date { return saved }
      return Calendar.current.date(bySettingHour: 19, minute: 0, second: 0, of: .now) ?? .now
    }
    set { UserDefaults.standard.set(newValue, forKey: "reminder.time") }
  }

  /// Active le rappel (demande l'autorisation la première fois). Renvoie false si refusé.
  static func enable() async -> Bool {
    let center = UNUserNotificationCenter.current()
    let granted = (try? await center.requestAuthorization(options: [.alert, .sound, .badge])) ?? false
    enabled = granted
    return granted
  }

  static func disable() {
    enabled = false
    UNUserNotificationCenter.current().removePendingNotificationRequests(withIdentifiers: [identifier])
  }

  /// (Re)programme le rappel avec un texte à jour.
  static func reschedule(vocabulary: Vocabulary) {
    let center = UNUserNotificationCenter.current()
    center.removePendingNotificationRequests(withIdentifiers: [identifier])
    guard enabled else { return }

    let content = UNMutableNotificationContent()
    let streak = vocabulary.streakDays
    let due = vocabulary.due.count
    content.title = streak > 0 ? "🔥 \(streak) jour(s) d'affilée : garde ta série !" : "老师 Lǎoshī t'attend"
    if due > 0 {
      content.body = "\(due) mot(s) à réviser, et une leçon avec tes lunettes ? 5 minutes suffisent."
    } else {
      content.body = "Regarde autour de toi avec tes lunettes : je t'apprends 2 nouveaux mots."
    }
    content.sound = .default

    let parts = Calendar.current.dateComponents([.hour, .minute], from: time)
    let trigger = UNCalendarNotificationTrigger(dateMatching: parts, repeats: true)
    center.add(UNNotificationRequest(identifier: identifier, content: content, trigger: trigger))
  }
}
