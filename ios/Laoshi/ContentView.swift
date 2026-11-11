import SwiftUI

struct ContentView: View {
  @Bindable var glasses: GlassesController
  @State private var showSettings = false
  @State private var challengeWord: Card?

  var body: some View {
    NavigationStack {
      ScrollView {
        VStack(spacing: 16) {
          connectionCard
          if glasses.isStreaming { lessonControls }
          if let challengeWord { challengeCard(challengeWord) }
          if let result = glasses.lastResult { LessonView(result: result, replay: replay) }
          if let message = glasses.message {
            Text(message).font(.footnote).foregroundStyle(.red).frame(maxWidth: .infinity, alignment: .leading)
          }
        }
        .padding()
      }
      .navigationTitle("老师 Lǎoshī")
      .toolbar {
        Button { showSettings = true } label: { Image(systemName: "gearshape") }
      }
      .sheet(isPresented: $showSettings) { SettingsView(glasses: glasses) }
    }
  }

  // MARK: Connexion

  @ViewBuilder private var connectionCard: some View {
    VStack(spacing: 12) {
      if !glasses.isRegistered {
        Text("Connecte tes lunettes Meta via l'app Meta AI (une seule fois).")
          .multilineTextAlignment(.center)
        Button("Connecter mes lunettes", action: glasses.register).buttonStyle(.borderedProminent)
      } else if !glasses.hasActiveDevice {
        Label("Mets tes lunettes et allume-les", systemImage: "eyeglasses")
      } else if glasses.sessionState == .idle || glasses.sessionState == .stopped {
        Button("Démarrer la caméra des lunettes", action: glasses.start).buttonStyle(.borderedProminent)
      } else if !glasses.isStreaming {
        ProgressView("Connexion aux lunettes…")
      }

      if let preview = glasses.preview {
        Image(uiImage: preview)
          .resizable().scaledToFit()
          .clipShape(RoundedRectangle(cornerRadius: 14))
          .overlay(alignment: .topTrailing) {
            if glasses.isThinking { ProgressView().padding(8).background(.ultraThinMaterial, in: Circle()).padding(8) }
          }
      }
      if glasses.isStreaming {
        Button("Arrêter", role: .destructive, action: glasses.stop).font(.footnote)
      }
    }
    .frame(maxWidth: .infinity)
  }

  // MARK: Leçon

  private var lessonControls: some View {
    VStack(spacing: 10) {
      Button {
        Task { await glasses.scan() }
      } label: {
        Text(glasses.isThinking ? "Le prof regarde…" : "Qu'est-ce que je vois ?")
          .font(.title3.bold()).frame(maxWidth: .infinity).padding(.vertical, 8)
      }
      .buttonStyle(.borderedProminent)
      .disabled(glasses.isThinking)

      Text("Astuce : appuie sur le bouton photo des lunettes pour scanner sans sortir ton téléphone.")
        .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)

      Toggle("Mode balade (toutes les 15 s)", isOn: $glasses.autoMode)

      Button("🎯 Défi : retrouver un mot") {
        let due = glasses.vocabulary.due
        challengeWord = (due.isEmpty ? Array(glasses.vocabulary.cards.values) : due).randomElement()
        if let word = challengeWord {
          Task { await glasses.speaker.speak([SpeechSegment(lang: "zh-CN", text: word.hanzi)]) }
        }
      }
      .disabled(glasses.vocabulary.cards.isEmpty)
    }
  }

  private func challengeCard(_ word: Card) -> some View {
    VStack(spacing: 8) {
      Text("Trouve autour de toi :").foregroundStyle(.secondary)
      Text(word.hanzi).font(.system(size: 56))
      PinyinText(pinyin: word.pinyin).font(.title3)
      HStack {
        Button("Je l'ai trouvé !") {
          Task {
            await glasses.scan(challenge: word.hanzi)
            if glasses.lastResult?.challenge?.found == true { challengeWord = nil }
          }
        }
        .buttonStyle(.borderedProminent)
        Button("Abandonner") { challengeWord = nil }
      }
    }
    .frame(maxWidth: .infinity)
    .padding()
    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14))
  }

  private func replay() {
    guard let result = glasses.lastResult else { return }
    Task { await glasses.speaker.speak(result.speech) }
  }
}

// MARK: - Affichage d'une leçon

struct LessonView: View {
  let result: ScanResult
  let replay: () -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      if let challenge = result.challenge {
        Label(challenge.feedback, systemImage: challenge.found ? "checkmark.circle.fill" : "magnifyingglass")
          .foregroundStyle(challenge.found ? .green : .orange)
      }
      Text(result.scene).italic().foregroundStyle(.secondary)
      ForEach(result.words) { WordCard(word: $0) }
      VStack(alignment: .leading, spacing: 4) {
        Text("Le prof te demande :").font(.caption).foregroundStyle(.secondary)
        Text(result.teacher.zh).font(.title2)
        PinyinText(pinyin: result.teacher.pinyin)
        Text(result.teacher.fr).foregroundStyle(.secondary)
        Button("🔊 Réécouter", action: replay).padding(.top, 4)
      }
      .padding()
      .frame(maxWidth: .infinity, alignment: .leading)
      .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14))
    }
  }
}

struct WordCard: View {
  let word: Word

  var body: some View {
    VStack(alignment: .leading, spacing: 6) {
      HStack(alignment: .firstTextBaseline, spacing: 10) {
        Text(word.hanzi).font(.system(size: 40))
        PinyinText(pinyin: word.pinyin).font(.title3)
        Spacer()
        Text(word.status == "new" ? "nouveau" : word.status == "review" ? "à revoir" : "connu")
          .font(.caption.bold()).padding(.horizontal, 8).padding(.vertical, 2)
          .background(word.status == "new" ? Color.red.opacity(0.85) : Color.secondary.opacity(0.2), in: Capsule())
          .foregroundStyle(word.status == "new" ? .white : .primary)
      }
      Text(word.fr).font(.headline) + Text("  · \(word.where)").foregroundStyle(.secondary)
      if !word.pinyinCheck.ok {
        Text("⚠ Pinyin à vérifier — dictionnaire : \(word.pinyinCheck.dictionary)")
          .font(.caption).foregroundStyle(.orange)
      }
      Text("\(word.measure.zh) · \(word.measure.pinyin)").font(.subheadline)
      Text(word.example.zh).font(.body)
      PinyinText(pinyin: word.example.pinyin).font(.caption)
      Text(word.example.fr).font(.caption).foregroundStyle(.secondary)
      Text("💡 \(word.tip)").font(.caption).foregroundStyle(.secondary)
    }
    .padding()
    .frame(maxWidth: .infinity, alignment: .leading)
    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14))
  }
}

/// Pinyin coloré selon le ton (1 rouge, 2 vert, 3 bleu, 4 violet, neutre gris).
struct PinyinText: View {
  let pinyin: String

  var body: some View {
    pinyin.split(separator: " ", omittingEmptySubsequences: true)
      .map { Text(String($0) + " ").foregroundColor(Self.color(for: String($0))) }
      .reduce(Text(""), +)
  }

  static func color(for syllable: String) -> Color {
    for scalar in syllable.decomposedStringWithCanonicalMapping.unicodeScalars {
      switch scalar.value {
      case 0x0304: return .red
      case 0x0301: return .green
      case 0x030C: return .blue
      case 0x0300: return .purple
      default: continue
      }
    }
    return .gray
  }
}

// MARK: - Réglages

struct SettingsView: View {
  @Bindable var glasses: GlassesController
  @Environment(\.dismiss) private var dismiss

  var body: some View {
    NavigationStack {
      Form {
        Section("Serveur du prof") {
          TextField("https://mon-serveur.onrender.com", text: $glasses.serverURL)
            .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
          SecureField("Jeton d'accès (optionnel)", text: $glasses.token)
        }
        Section("Apprentissage") {
          Picker("Niveau", selection: $glasses.level) {
            Text("Débutant (HSK 1-2)").tag("debutant")
            Text("Intermédiaire (HSK 3-4)").tag("intermediaire")
            Text("Avancé").tag("avance")
          }
          Stepper("Mots nouveaux par photo : \(glasses.maxNew)", value: $glasses.maxNew, in: 1...3)
          LabeledContent("Mots appris", value: "\(glasses.vocabulary.cards.count)")
          LabeledContent("Maîtrisés", value: "\(glasses.vocabulary.known.count)")
        }
        Section {
          Button("Tester la voix") {
            Task {
              await glasses.speaker.speak([
                SpeechSegment(lang: "zh-CN", text: "你好！我是你的中文老师。"),
                SpeechSegment(lang: "fr-FR", text: "Bonjour ! Je suis ton prof de chinois."),
              ])
            }
          }
        } footer: {
          Text("Si la voix chinoise est absente : Réglages iPhone › Accessibilité › Contenu énoncé › Voix › Chinois.")
        }
      }
      .navigationTitle("Réglages")
      .toolbar { Button("OK") { dismiss() } }
    }
  }
}
