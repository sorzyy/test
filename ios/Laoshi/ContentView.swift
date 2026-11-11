import AVFoundation
import SwiftUI

struct ContentView: View {
  @Bindable var glasses: GlassesController
  @State private var showSettings = false

  var body: some View {
    NavigationStack {
      ScrollView {
        VStack(spacing: 20) {
          if let message = glasses.message { ErrorBanner(text: message) { glasses.message = nil } }
          StepsView(glasses: glasses)
          if glasses.running {
            runningPanel
          } else {
            PowerButton(glasses: glasses)
          }
          ModePicker(selection: $glasses.mode)
          if glasses.running, glasses.isStreaming { results }
          ActivityList(entries: glasses.activity)
        }
        .padding()
      }
      .navigationTitle("老师 Lǎoshī")
      .toolbar {
        Button { showSettings = true } label: { Image(systemName: "gearshape") }
          .accessibilityLabel("Réglages")
      }
      .sheet(isPresented: $showSettings) { SettingsView(glasses: glasses) }
    }
  }

  // MARK: Pendant l'utilisation

  @ViewBuilder private var runningPanel: some View {
    VStack(spacing: 14) {
      if let preview = glasses.preview {
        Image(uiImage: preview)
          .resizable().scaledToFill()
          .frame(maxWidth: .infinity, maxHeight: 220)
          .clipShape(RoundedRectangle(cornerRadius: 16))
          .overlay(alignment: .topLeading) {
            Label("Vue des lunettes", systemImage: "eyeglasses")
              .font(.caption.bold()).padding(6)
              .background(.ultraThinMaterial, in: Capsule()).padding(8)
          }
          .overlay {
            if glasses.isThinking {
              ProgressView("Le prof réfléchit…").padding().background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
            }
          }
      } else {
        VStack(spacing: 10) {
          ProgressView()
          Text("Connexion aux lunettes…").font(.headline)
          Text("Suis les étapes ci-dessus. Si Meta AI s'ouvre, accepte puis reviens ici.")
            .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity, minHeight: 160)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 16))
      }

      if glasses.isStreaming { actionArea }

      Button(role: .destructive) { glasses.powerOff() } label: {
        Label("Arrêter", systemImage: "stop.circle").frame(maxWidth: .infinity)
      }
      .buttonStyle(.bordered)
    }
  }

  @ViewBuilder private var actionArea: some View {
    VStack(spacing: 10) {
      if glasses.mode == .challenge, let word = glasses.challengeWord {
        VStack(spacing: 4) {
          Text("Trouve autour de toi :").foregroundStyle(.secondary)
          Text(word.hanzi).font(.system(size: 56))
          PinyinText(pinyin: word.pinyin).font(.title3)
        }
      }
      if glasses.mode == .ask, !glasses.transcript.isEmpty {
        Text("« \(glasses.transcript) »").font(.title3).multilineTextAlignment(.center)
      }
      if glasses.mode == .walk {
        Label(glasses.autoMode ? "Balade en cours : une leçon toutes les 15 s" : "Balade en pause", systemImage: "figure.walk")
          .foregroundStyle(.secondary)
      }
      Button {
        Task { await glasses.primaryAction() }
      } label: {
        Label(actionTitle, systemImage: actionIcon)
          .font(.title3.bold()).frame(maxWidth: .infinity).padding(.vertical, 14)
      }
      .buttonStyle(.borderedProminent)
      .tint(glasses.isListening ? .red : .accentColor)
      .disabled(glasses.isThinking)
      Text("Astuce : le bouton photo de tes lunettes fait la même chose.")
        .font(.caption).foregroundStyle(.secondary)
    }
  }

  private var actionTitle: String {
    if glasses.isThinking { return "Le prof réfléchit…" }
    switch glasses.mode {
    case .look: return "Qu'est-ce que je vois ?"
    case .ask: return glasses.isListening ? "J'écoute… (touche pour finir)" : "Parler au prof"
    case .walk: return "Leçon maintenant"
    case .challenge: return glasses.challengeWord == nil ? "Nouveau défi" : "Je l'ai trouvé !"
    }
  }

  private var actionIcon: String {
    switch glasses.mode {
    case .look: return "eye.fill"
    case .ask: return glasses.isListening ? "waveform" : "mic.fill"
    case .walk: return "sparkles"
    case .challenge: return glasses.challengeWord == nil ? "target" : "checkmark.circle.fill"
    }
  }

  @ViewBuilder private var results: some View {
    if let answer = glasses.lastAnswer { AnswerView(answer: answer, replay: replay) }
    if let result = glasses.lastResult { LessonView(result: result, replay: replay) }
  }

  private func replay() {
    guard let speech = glasses.lastAnswer?.speech ?? glasses.lastResult?.speech else { return }
    Task { await glasses.speaker.speak(speech) }
  }
}

// MARK: - Le gros bouton

struct PowerButton: View {
  let glasses: GlassesController

  var body: some View {
    VStack(spacing: 14) {
      Button { glasses.powerOn() } label: {
        VStack(spacing: 8) {
          Image(systemName: "power").font(.system(size: 44, weight: .bold))
          Text("Démarrer").font(.title2.bold())
        }
        .foregroundStyle(.white)
        .frame(width: 180, height: 180)
        .background(Circle().fill(Color.accentColor))
        .shadow(color: .accentColor.opacity(0.35), radius: 16, y: 6)
      }
      .buttonStyle(.plain)
      .accessibilityLabel("Démarrer Lǎoshī")
      Text("Mets tes lunettes, choisis un mode, puis appuie.")
        .font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
    }
    .frame(maxWidth: .infinity)
    .padding(.vertical, 8)
  }
}

// MARK: - Les 3 étapes

struct StepsView: View {
  let glasses: GlassesController

  var body: some View {
    HStack(spacing: 8) {
      step("Autorisation", done: glasses.isRegistered, active: glasses.running && !glasses.isRegistered)
      step("Lunettes", done: glasses.isSessionStarted, active: glasses.running && glasses.isRegistered && !glasses.isSessionStarted)
      step("Caméra", done: glasses.hasFirstFrame, active: glasses.isSessionStarted && !glasses.hasFirstFrame)
    }
  }

  private func step(_ title: String, done: Bool, active: Bool) -> some View {
    VStack(spacing: 4) {
      ZStack {
        if active {
          ProgressView()
        } else {
          Image(systemName: done ? "checkmark.circle.fill" : "circle")
            .font(.title2)
            .foregroundStyle(done ? Color.green : Color.secondary)
        }
      }
      .frame(height: 28)
      Text(title).font(.caption.bold()).foregroundStyle(done ? .primary : .secondary)
    }
    .frame(maxWidth: .infinity)
    .padding(.vertical, 8)
    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 12))
  }
}

// MARK: - Choix du mode

struct ModePicker: View {
  @Binding var selection: LessonMode

  var body: some View {
    LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
      ForEach(LessonMode.allCases) { mode in
        Button { selection = mode } label: {
          VStack(alignment: .leading, spacing: 6) {
            Image(systemName: mode.icon).font(.title2)
            Text(mode.title).font(.headline)
            Text(mode.hint).font(.caption).foregroundStyle(.secondary)
              .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
          }
          .frame(maxWidth: .infinity, minHeight: 110, alignment: .topLeading)
          .padding(12)
          .background(
            RoundedRectangle(cornerRadius: 14)
              .fill(selection == mode ? Color.accentColor.opacity(0.18) : Color.secondary.opacity(0.08))
          )
          .overlay(
            RoundedRectangle(cornerRadius: 14)
              .stroke(selection == mode ? Color.accentColor : .clear, lineWidth: 2)
          )
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(selection == mode ? .isSelected : [])
      }
    }
  }
}

// MARK: - Fil d'activité et erreurs

struct ActivityList: View {
  let entries: [ActivityEntry]

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("Ce qui se passe").font(.headline)
      if entries.isEmpty {
        Text("Rien pour l'instant. Appuie sur « Démarrer ».").font(.subheadline).foregroundStyle(.secondary)
      }
      ForEach(entries.prefix(8)) { entry in
        HStack(alignment: .top, spacing: 8) {
          Image(systemName: icon(entry.kind)).foregroundStyle(color(entry.kind))
          VStack(alignment: .leading, spacing: 2) {
            Text(entry.text).font(.subheadline)
            Text(entry.date, style: .time).font(.caption2).foregroundStyle(.secondary)
          }
        }
      }
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .padding()
    .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14))
  }

  private func icon(_ kind: ActivityEntry.Kind) -> String {
    switch kind {
    case .info: return "info.circle"
    case .success: return "checkmark.circle.fill"
    case .warning: return "exclamationmark.triangle.fill"
    case .error: return "xmark.octagon.fill"
    }
  }

  private func color(_ kind: ActivityEntry.Kind) -> Color {
    switch kind {
    case .info: return .secondary
    case .success: return .green
    case .warning: return .orange
    case .error: return .red
    }
  }
}

struct ErrorBanner: View {
  let text: String
  let dismiss: () -> Void

  var body: some View {
    HStack(alignment: .top, spacing: 10) {
      Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.white)
      Text(text).foregroundStyle(.white).font(.subheadline.weight(.semibold))
        .frame(maxWidth: .infinity, alignment: .leading)
      Button(action: dismiss) { Image(systemName: "xmark").foregroundStyle(.white) }
        .accessibilityLabel("Fermer")
    }
    .padding()
    .background(Color.red, in: RoundedRectangle(cornerRadius: 14))
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

struct AnswerView: View {
  let answer: AskResult
  let replay: () -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      Text("« \(answer.question) »").font(.headline)
      if !answer.intro.isEmpty { Text(answer.intro) }
      ForEach(answer.words) { WordCard(word: $0) }
      if !answer.followup.isEmpty { Text(answer.followup).foregroundStyle(.secondary) }
      Button("🔊 Réécouter", action: replay)
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
      Text(word.fr).font(.headline) + Text(word.where.isEmpty ? "" : "  · \(word.where)").foregroundStyle(.secondary)
      if let check = word.pinyinCheck, !check.ok {
        Text("⚠ Pinyin à vérifier — dictionnaire : \(check.dictionary)")
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
        Section {
          SecureField("Clé API Gemini", text: $glasses.geminiKey)
            .textInputAutocapitalization(.never).autocorrectionDisabled()
          TextField("Modèle", text: $glasses.geminiModel)
            .textInputAutocapitalization(.never).autocorrectionDisabled()
        } header: {
          Text("Mode direct (recommandé)")
        } footer: {
          Text("Avec une clé Gemini, l'app parle directement à Gemini : pas de serveur. La clé reste dans le trousseau de ton iPhone. Laisse vide pour utiliser ton serveur.")
        }
        Section {
          TextField("https://mon-serveur.onrender.com", text: $glasses.serverURL)
            .keyboardType(.URL).textInputAutocapitalization(.never).autocorrectionDisabled()
          SecureField("Jeton d'accès (optionnel)", text: $glasses.token)
        } header: {
          Text("Ou : ton serveur")
        } footer: {
          Text("Utilisé seulement sans clé Gemini. Avantage : le pinyin y est vérifié avec un dictionnaire.")
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
          LabeledContent("Série", value: "🔥 \(glasses.vocabulary.streakDays) jour(s)")
          LabeledContent("À retravailler", value: "\(glasses.vocabulary.struggling.count) mot(s)")
        }
        Section {
          LabeledContent("Autorisation Meta AI", value: GlassesController.describe(glasses.registrationState))
          LabeledContent("Lunettes détectées", value: glasses.hasActiveDevice ? "oui" : "non")
          LabeledContent("Connexion", value: String(describing: glasses.sessionState))
          LabeledContent("Caméra", value: glasses.hasFirstFrame ? "images reçues" : String(describing: glasses.streamState))
          LabeledContent("Identifiant de l'app", value: Bundle.main.bundleIdentifier ?? "?")
          Button("Refaire l'autorisation Meta AI", role: .destructive) { glasses.resetRegistration() }
        } header: {
          Text("Diagnostic")
        } footer: {
          Text("Si l'autorisation reste « pas encore faite » après Meta AI : \(GlassesController.devModeHelp) Ensuite, Lǎoshī doit apparaître dans Meta AI › Paramètres › Connexions d'apps › Apps en mode développeur.")
        }
        VoiceSection(speaker: glasses.speaker, teacherPace: $glasses.teacherPace)
      }
      .navigationTitle("Réglages")
      .toolbar { Button("OK") { dismiss() } }
    }
  }
}


// MARK: - Réglages de la voix

struct VoiceSection: View {
  let speaker: Speaker
  @Binding var teacherPace: Bool
  @State private var chineseVoice = ""
  @State private var frenchVoice = ""
  @State private var rate: Double = 0.45

  var body: some View {
    Section {
      Toggle("Rythme de prof", isOn: $teacherPace)
      Picker("Voix chinoise", selection: $chineseVoice) {
        Text("Automatique (la meilleure)").tag("")
        ForEach(Speaker.voices(for: "zh-CN"), id: \.identifier) { voice in
          Text("\(voice.name) · \(Speaker.qualityLabel(voice))").tag(voice.identifier)
        }
      }
      Picker("Voix française", selection: $frenchVoice) {
        Text("Automatique (la meilleure)").tag("")
        ForEach(Speaker.voices(for: "fr-FR"), id: \.identifier) { voice in
          Text("\(voice.name) · \(Speaker.qualityLabel(voice))").tag(voice.identifier)
        }
      }
      VStack(alignment: .leading) {
        Text("Vitesse du chinois")
        Slider(value: $rate, in: 0.3...0.6) {
          Text("Vitesse du chinois")
        } minimumValueLabel: {
          Image(systemName: "tortoise")
        } maximumValueLabel: {
          Image(systemName: "hare")
        }
      }
      Button("🔊 Tester la voix") {
        Task {
          await speaker.speak([
            SpeechSegment(lang: "fr-FR", text: "Bonjour ! Je suis ton prof de chinois. Écoute :"),
            SpeechSegment(lang: "zh-CN", text: "椅子", slow: true, pause: 0.6),
            SpeechSegment(lang: "zh-CN", text: "椅子"),
            SpeechSegment(lang: "fr-FR", text: "chaise. À toi !", pause: 2.0),
            SpeechSegment(lang: "zh-CN", text: "这是一把椅子。"),
          ])
        }
      }
    } header: {
      Text("Voix")
    } footer: {
      Text(footer)
    }
    .onAppear {
      chineseVoice = speaker.chineseVoiceID ?? ""
      frenchVoice = speaker.frenchVoiceID ?? ""
      rate = Double(speaker.chineseRate)
    }
    .onChange(of: chineseVoice) { _, value in speaker.chineseVoiceID = value.isEmpty ? nil : value }
    .onChange(of: frenchVoice) { _, value in speaker.frenchVoiceID = value.isEmpty ? nil : value }
    .onChange(of: rate) { _, value in speaker.chineseRate = Float(value) }
  }

  private var footer: String {
    var text = "Rythme de prof : le mot lentement puis normalement, puis « À toi ! » avec un silence pour répéter. "
    if speaker.onlyBasicVoice(for: "zh-CN") {
      text += "Pour une voix chinoise bien plus naturelle : Réglages de l'iPhone › Accessibilité › Contenu énoncé › Voix › Chinois (Chine) › télécharge une voix « Premium » ou « Améliorée », puis reviens ici."
    } else {
      text += "Une voix chinoise de bonne qualité est installée ✓"
    }
    return text
  }
}
