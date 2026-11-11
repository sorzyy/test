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
}

@MainActor
final class Vocabulary {
  static let intervals: [Double] = [0, 1, 3, 7, 16, 35, 80]
  static let knownBox = 4

  private(set) var cards: [String: Card] = [:]
  private let key = "laoshi.deck"

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

  /// Mots rencontrés dans une leçon : on ajoute les nouveaux, on note les revus.
  func record(_ words: [Word]) {
    for word in words where word.status != "known" {
      if var card = cards[word.hanzi] {
        card.seen += 1
        cards[word.hanzi] = card
      } else {
        cards[word.hanzi] = Card(hanzi: word.hanzi, pinyin: word.pinyin, fr: word.fr)
      }
    }
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
    }
    cards[hanzi] = card
    save()
  }

  private func save() {
    if let data = try? JSONEncoder().encode(cards) {
      UserDefaults.standard.set(data, forKey: key)
    }
  }
}
