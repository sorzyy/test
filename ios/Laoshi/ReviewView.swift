import SwiftUI

/// Révision des mots appris : la carte montre le caractère, le prof le dit dans les lunettes,
/// l'élève cherche le sens, peut le prononcer (« Répète après moi »), puis note s'il savait.
struct ReviewView: View {
  let glasses: GlassesController
  @Environment(\.dismiss) private var dismiss
  @State private var queue: [Card] = []
  @State private var index = 0
  @State private var revealed = false
  @State private var reviewedCount = 0
  @State private var coach = PronunciationCoach()
  @State private var coachMessage: String?
  @State private var extraMode = false

  private var vocabulary: Vocabulary { glasses.vocabulary }
  private var current: Card? { index < queue.count ? queue[index] : nil }

  var body: some View {
    NavigationStack {
      VStack(spacing: 20) {
        if let card = current {
          Text("Carte \(index + 1) sur \(queue.count)").font(.subheadline).foregroundStyle(.secondary)
          cardView(card)
          Spacer(minLength: 0)
          controls(card)
        } else {
          finished
        }
      }
      .padding()
      .navigationTitle("Révision")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        Button("Fermer") { dismiss() }
      }
      .onAppear(perform: load)
    }
  }

  // MARK: La carte

  private func cardView(_ card: Card) -> some View {
    VStack(spacing: 12) {
      Text(card.hanzi).font(.system(size: 72))
      Button {
        say(card)
      } label: {
        Label("Écouter", systemImage: "speaker.wave.2.fill")
      }
      .buttonStyle(.bordered)

      if revealed {
        PinyinText(pinyin: card.pinyin).font(.title2)
        Text(card.fr).font(.title3.bold())
        if let example = card.exampleZh {
          VStack(spacing: 2) {
            Text(example).font(.title3)
            if let pinyin = card.examplePinyin { PinyinText(pinyin: pinyin).font(.caption) }
            if let fr = card.exampleFr { Text(fr).font(.caption).foregroundStyle(.secondary) }
          }
        }
        if let tip = card.tip {
          Text("💡 \(tip)").font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }
      } else {
        Text("Que veut dire ce mot ? Dis-le dans ta tête, puis regarde la réponse.")
          .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
      }

      Button {
        Task { await practice(card) }
      } label: {
        Label(coach.isListening ? "J'écoute…" : "Répète après moi", systemImage: coach.isListening ? "waveform" : "mic.fill")
      }
      .buttonStyle(.bordered)
      .tint(coach.isListening ? .red : .accentColor)
      .disabled(coach.isListening)

      if coach.isListening, !coach.heard.isEmpty {
        Text("« \(coach.heard) »").foregroundStyle(.secondary)
      }
      if let coachMessage {
        Text(coachMessage).font(.callout.weight(.semibold)).multilineTextAlignment(.center)
      }
    }
    .frame(maxWidth: .infinity)
    .padding()
    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 18))
  }

  @ViewBuilder private func controls(_ card: Card) -> some View {
    if revealed {
      HStack(spacing: 12) {
        Button {
          answer(card, good: false)
        } label: {
          Text("À revoir").frame(maxWidth: .infinity).padding(.vertical, 10)
        }
        .buttonStyle(.bordered)
        Button {
          answer(card, good: true)
        } label: {
          Text("Je savais").frame(maxWidth: .infinity).padding(.vertical, 10)
        }
        .buttonStyle(.borderedProminent)
      }
    } else {
      Button {
        revealed = true
        Task {
          await glasses.speaker.speak([
            SpeechSegment(lang: "zh-CN", text: card.hanzi),
            SpeechSegment(lang: "fr-FR", text: card.fr),
          ])
        }
      } label: {
        Text("Voir la réponse").font(.headline).frame(maxWidth: .infinity).padding(.vertical, 12)
      }
      .buttonStyle(.borderedProminent)
    }
  }

  private var finished: some View {
    VStack(spacing: 14) {
      Image(systemName: "checkmark.seal.fill").font(.system(size: 56)).foregroundStyle(.green)
      Text(reviewedCount > 0 ? "Bravo, \(reviewedCount) carte(s) révisée(s) !" : "Rien à réviser pour l'instant.")
        .font(.title3.bold()).multilineTextAlignment(.center)
      Text("🔥 Série : \(vocabulary.streakDays) jour(s) · Objectif : \(vocabulary.doneToday)/\(vocabulary.dailyGoal)")
        .foregroundStyle(.secondary)
      if !vocabulary.cards.isEmpty {
        Button("Réviser quand même mes mots les moins sûrs") {
          extraMode = true
          load()
        }
        .buttonStyle(.bordered)
      }
      Button("Fermer") { dismiss() }.buttonStyle(.borderedProminent)
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity)
  }

  // MARK: Actions

  private func load() {
    queue = vocabulary.reviewQueue(extra: extraMode)
    index = 0
    revealed = false
    coachMessage = nil
    if let card = current { say(card) }
  }

  private func say(_ card: Card) {
    Task {
      await glasses.speaker.speak([
        SpeechSegment(lang: "zh-CN", text: card.hanzi, slow: true, pause: 0.5),
        SpeechSegment(lang: "zh-CN", text: card.hanzi),
      ])
    }
  }

  private func answer(_ card: Card, good: Bool) {
    vocabulary.grade(card.hanzi, good: good)
    vocabulary.countAction()
    reviewedCount += 1
    index += 1
    revealed = false
    coachMessage = nil
    if let next = current { say(next) }
  }

  private func practice(_ card: Card) async {
    coachMessage = nil
    glasses.speaker.stop()
    await glasses.speaker.speak([SpeechSegment(lang: "fr-FR", text: "À toi !", pause: 0.2)])
    let verdict = await coach.listen(expected: card.hanzi)
    let feedback = PronunciationCoach.feedback(verdict, word: card.hanzi, pinyin: card.pinyin)
    coachMessage = feedback.text
    await glasses.speaker.speak(feedback.speech)
  }
}
