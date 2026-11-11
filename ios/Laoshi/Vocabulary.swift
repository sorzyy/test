import Foundation

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

@MainActor
final class Vocabulary {
  static let intervals: [Double] = [0, 1, 3, 7, 16, 35, 80]
  static let knownBox = 4

  private(set) var cards: [String: Card] = [:]
  private let key = "laoshi.deck"
  private let daysKey = "laoshi.studyDays"

  init() {
    if let data = UserDefaults.standard.data(forKey: key),
      let decoded = try? JSONDecoder().decode([String: Card].self, from: data)
    {
      cards = decoded
    }
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
      if var card = cards[word.hanzi] {
        card.seen += 1
        card.lastSeen = .now
        cards[word.hanzi] = card
      } else {
        cards[word.hanzi] = Card(hanzi: word.hanzi, pinyin: word.pinyin, fr: word.fr, lastSeen: .now)
      }
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
