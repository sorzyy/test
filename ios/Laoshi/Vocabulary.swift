import Foundation
import Observation

/// Le vocabulaire de l'élève, avec répétition espacée (boîtes de Leitner).
/// Mêmes règles que l'appli web : 1, 3, 7, 16, 35, 80 jours ; maîtrisé à partir de la boîte 4.
struct Card: Codable, Hashable, Identifiable {
  var id: String { hanzi }
  let hanzi: String
  var pinyin: String
  var fr: String
  var box: Int = 0
  var due: Date = .now
  var seen: Int = 1
  // Ajoutés plus tard : optionnels pour relire les anciens vocabulaires sans erreur.
  /// Nombre de fois où l'élève a montré qu'il l'avait oublié.
  var misses: Int? = nil
  var lastSeen: Date? = nil
  /// De quoi réviser sans réseau : un exemple et l'astuce du prof.
  var exampleZh: String? = nil
  var examplePinyin: String? = nil
  var exampleFr: String? = nil
  var tip: String? = nil
}

/// Ce que le prof sait de l'élève, envoyé à Gemini à chaque leçon.
struct LearnerProfile {
  var level: String
  var known: [String]
  var learning: [String]
  /// Mots souvent oubliés : à réutiliser en priorité.
  var struggling: [String]
  /// Derniers mots vus : pour varier et faire des liens.
  var recent: [String]
  var totalWords: Int
  var streakDays: Int
}

@Observable
@MainActor
final class Vocabulary {
  static let intervals: [Double] = [0, 1, 3, 7, 16, 35, 80]
  static let knownBox = 4

  private(set) var cards: [String: Card] = [:]
  @ObservationIgnored private let key = "laoshi.deck"
  @ObservationIgnored private let daysKey = "laoshi.studyDays"

  // MARK: Objectif du jour

  /// Actions d'apprentissage visées par jour (leçon, réponse, révision, défi).
  var dailyGoal: Int = (UserDefaults.standard.object(forKey: "laoshi.dailyGoal") as? Int) ?? 10 {
    didSet { UserDefaults.standard.set(dailyGoal, forKey: "laoshi.dailyGoal") }
  }
  /// Actions faites aujourd'hui (relu au lancement, remis à zéro chaque jour).
  private(set) var doneToday: Int = 0

  private var todayProgressKey: String { "laoshi.done." + Self.dayFormat.string(from: .now) }

  /// Compte une action pour l'objectif du jour et la série.
  func countAction() {
    doneToday = UserDefaults.standard.integer(forKey: todayProgressKey) + 1
    UserDefaults.standard.set(doneToday, forKey: todayProgressKey)
    markStudiedToday()
  }

  func refreshToday() {
    doneToday = UserDefaults.standard.integer(forKey: todayProgressKey)
  }

  init() {
    if let data = UserDefaults.standard.data(forKey: key),
      let decoded = try? JSONDecoder().decode([String: Card].self, from: data)
    {
      cards = decoded
    }
    refreshToday()
  }

  var known: [String] { cards.values.filter { $0.box >= Self.knownBox }.map(\.hanzi) }
  var learning: [String] { cards.values.filter { $0.box < Self.knownBox }.map(\.hanzi) }
  var due: [Card] { cards.values.filter { $0.due <= .now }.sorted { $0.due < $1.due } }

  var struggling: [String] {
    cards.values
      .filter { ($0.misses ?? 0) > 0 && $0.box < Self.knownBox }
      .sorted { ($0.misses ?? 0) > ($1.misses ?? 0) }
      .prefix(15)
      .map(\.hanzi)
  }

  var recent: [String] {
    cards.values
      .sorted { ($0.lastSeen ?? .distantPast) > ($1.lastSeen ?? .distantPast) }
      .prefix(10)
      .map(\.hanzi)
  }

  func profile(level: String) -> LearnerProfile {
    LearnerProfile(
      level: level, known: known, learning: learning, struggling: struggling, recent: recent,
      totalWords: cards.count, streakDays: streakDays)
  }

  /// Mots rencontrés dans une leçon : on ajoute les nouveaux, on note les revus.
  func record(_ words: [Word]) {
    for word in words where word.status != "known" {
      var card = cards[word.hanzi] ?? Card(hanzi: word.hanzi, pinyin: word.pinyin, fr: word.fr, seen: 0)
      card.seen += 1
      card.lastSeen = .now
      if !word.example.zh.isEmpty {
        card.exampleZh = word.example.zh
        card.examplePinyin = word.example.pinyin
        card.exampleFr = word.example.fr
      }
      if !word.tip.isEmpty { card.tip = word.tip }
      cards[word.hanzi] = card
    }
    markStudiedToday()
    save()
  }

  /// L'élève redemande un mot déjà appris : il l'a oublié. On le fait revenir vite.
  func recordForgotten(_ hanzi: String) {
    guard var card = cards[hanzi], card.box > 0 || card.seen > 1 else { return }
    card.misses = (card.misses ?? 0) + 1
    card.box = 0
    card.due = .now.addingTimeInterval(600)
    cards[hanzi] = card
    save()
  }

  func grade(_ hanzi: String, good: Bool) {
    guard var card = cards[hanzi] else { return }
    if good {
      card.box = min(card.box + 1, Self.intervals.count - 1)
      card.due = .now.addingTimeInterval(Self.intervals[card.box] * 86_400)
    } else {
      card.box = 0
      card.due = .now.addingTimeInterval(600)
      card.misses = (card.misses ?? 0) + 1
    }
    cards[hanzi] = card
    save()
  }

  // MARK: Série de jours

  private static let dayFormat: DateFormatter = {
    let f = DateFormatter()
    f.calendar = Calendar(identifier: .gregorian)
    f.locale = Locale(identifier: "en_US_POSIX")
    f.dateFormat = "yyyy-MM-dd"
    return f
  }()

  /// Cartes à réviser maintenant ; s'il n'y en a pas, les moins sûres (pour réviser quand même).
  func reviewQueue(extra: Bool) -> [Card] {
    let dueNow = due
    if !dueNow.isEmpty || !extra { return dueNow }
    return cards.values.sorted { ($0.box, $0.due) < ($1.box, $1.due) }.prefix(10).map { $0 }
  }

  private var studyDays: Set<String> {
    Set(UserDefaults.standard.stringArray(forKey: daysKey) ?? [])
  }

  private func markStudiedToday() {
    var days = studyDays
    days.insert(Self.dayFormat.string(from: .now))
    UserDefaults.standard.set(Array(Array(days).sorted().suffix(400)), forKey: daysKey)
  }

  /// Jours d'affilée avec au moins une leçon (aujourd'hui compris, ou jusqu'à hier).
  var streakDays: Int {
    let days = studyDays
    let calendar = Calendar(identifier: .gregorian)
    var day = Date.now
    if !days.contains(Self.dayFormat.string(from: day)) {
      guard let yesterday = calendar.date(byAdding: .day, value: -1, to: day) else { return 0 }
      day = yesterday
    }
    var count = 0
    while days.contains(Self.dayFormat.string(from: day)) {
      count += 1
      guard let previous = calendar.date(byAdding: .day, value: -1, to: day) else { break }
      day = previous
    }
    return count
  }

  private func save() {
    if let data = try? JSONEncoder().encode(cards) {
      UserDefaults.standard.set(data, forKey: key)
    }
  }
}
