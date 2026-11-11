import Foundation
import MWDATCamera
import MWDATCore
import Observation
import UIKit

#if canImport(MWDATInputs)
import MWDATInputs
#endif
#if canImport(MWDATSpeech)
import MWDATSpeech
#endif

/// Les façons d'apprendre. Le gros bouton de l'écran et le bouton photo des lunettes
/// déclenchent l'action du mode choisi.
enum LessonMode: String, CaseIterable, Identifiable {
  case look, ask, walk, challenge

  var id: String { rawValue }
  var title: String {
    switch self {
    case .look: return "Regarder"
    case .ask: return "Demander"
    case .walk: return "Balade"
    case .challenge: return "Défi"
    }
  }
  var icon: String {
    switch self {
    case .look: return "eye.fill"
    case .ask: return "mic.fill"
    case .walk: return "figure.walk"
    case .challenge: return "target"
    }
  }
  var hint: String {
    switch self {
    case .look: return "Regarde un objet, le prof te dit son nom."
    case .ask: return "Pose une question : « que veut dire siège ? »"
    case .walk: return "Une mini-leçon toutes les 15 s, sans rien toucher."
    case .challenge: return "Retrouve autour de toi un mot déjà appris."
    }
  }
}

/// Une ligne du fil d'activité affiché à l'écran : l'app n'est jamais silencieuse.
struct ActivityEntry: Identifiable {
  enum Kind { case info, success, warning, error }
  let id = UUID()
  let date = Date()
  let text: String
  let kind: Kind
}

/// Pilote les lunettes : enregistrement auprès de Meta AI, session, flux caméra,
/// bouton photo, « Hey Meta, lance Lǎoshī », micro des lunettes, puis envoi au prof
/// et lecture de la réponse dans les haut-parleurs des lunettes.
@Observable
@MainActor
final class GlassesController {
  // MARK: État affiché

  var registrationState: RegistrationState
  var sessionState: DeviceSessionState = .idle
  var streamState: StreamState = .stopped
  var hasActiveDevice = false
  var preview: UIImage?
  var isThinking = false
  var isListening = false
  var transcript = ""
  var lastResult: ScanResult?
  var lastAnswer: AskResult?
  var message: String?
  /// L'utilisateur a appuyé sur « Démarrer » (et pas encore sur « Arrêter »).
  var running = false
  var mode: LessonMode = .look {
    didSet { if oldValue != mode { modeChanged() } }
  }
  var activity: [ActivityEntry] = []
  var challengeWord: Card?
  var hasFirstFrame = false
  var autoMode = false {
    didSet { autoMode ? startAutoMode() : stopAutoMode() }
  }

  // MARK: Réglages (persistés)

  var serverURL: String = UserDefaults.standard.string(forKey: "serverURL") ?? "" {
    didSet { UserDefaults.standard.set(serverURL, forKey: "serverURL") }
  }
  var token: String = UserDefaults.standard.string(forKey: "token") ?? "" {
    didSet { UserDefaults.standard.set(token, forKey: "token") }
  }
  var level: String = UserDefaults.standard.string(forKey: "level") ?? "debutant" {
    didSet { UserDefaults.standard.set(level, forKey: "level") }
  }
  var maxNew: Int = (UserDefaults.standard.object(forKey: "maxNew") as? Int) ?? 2 {
    didSet { UserDefaults.standard.set(maxNew, forKey: "maxNew") }
  }
  /// Mode direct : avec une clé Gemini, l'app appelle Gemini elle-même (pas de serveur).
  var geminiKey: String = KeyStore.load() {
    didSet { KeyStore.save(geminiKey.trimmingCharacters(in: .whitespacesAndNewlines)) }
  }
  var geminiModel: String = UserDefaults.standard.string(forKey: "geminiModel") ?? "gemini-3.5-flash" {
    didSet { UserDefaults.standard.set(geminiModel, forKey: "geminiModel") }
  }
  /// Rythme de prof : le mot lentement puis normalement, « À toi ! » avec un silence pour répéter.
  var teacherPace: Bool = (UserDefaults.standard.object(forKey: "teacherPace") as? Bool) ?? true {
    didSet { UserDefaults.standard.set(teacherPace, forKey: "teacherPace") }
  }

  var isStreaming: Bool { streamState == .streaming }
  var isRegistered: Bool { registrationState == .registered }
  var isSessionStarted: Bool { sessionState == .started }

  // MARK: Privé

  @ObservationIgnored private let wearables: WearablesInterface
  @ObservationIgnored private let deviceSelector: AutoDeviceSelector
  @ObservationIgnored private var session: DeviceSession?
  @ObservationIgnored private var camera: MWDATCamera.Camera?
  @ObservationIgnored private let sessionTokens = ListenerTokenBag()
  @ObservationIgnored private let streamTokens = ListenerTokenBag()
  @ObservationIgnored private let voiceTokens = ListenerTokenBag()
  @ObservationIgnored private let speechTokens = ListenerTokenBag()
  @ObservationIgnored private let latestFrame = FrameBox()
  @ObservationIgnored private var photoWaiter: CheckedContinuation<Data?, Never>?
  @ObservationIgnored private var photoRequest = 0
  @ObservationIgnored private var tasks: [Task<Void, Never>] = []
  @ObservationIgnored private var autoTask: Task<Void, Never>?
  @ObservationIgnored private var inputsTask: Task<Void, Never>?
  @ObservationIgnored private var voiceStream: VoiceInvocationsStream?
  @ObservationIgnored private var listenAfterStart = false
  @ObservationIgnored private var listenTimeout: Task<Void, Never>?
  @ObservationIgnored private var watchdog: Task<Void, Never>?
  @ObservationIgnored private var announcedReady = false
  /// Ce qu'on attend de Meta AI quand on l'a ouvert (autorisation, caméra, micro).
  @ObservationIgnored private var waitingForMetaAI: String?
  @ObservationIgnored private var returnCheck: Task<Void, Never>?
  #if canImport(MWDATSpeech)
  @ObservationIgnored private var speech: Speech?
  #endif
  @ObservationIgnored let speaker = Speaker()
  @ObservationIgnored let vocabulary = Vocabulary()

  init(wearables: WearablesInterface) {
    self.wearables = wearables
    self.registrationState = wearables.registrationState
    self.deviceSelector = AutoDeviceSelector(wearables: wearables)
    tasks.append(Task { [weak self] in
      for await state in wearables.registrationStateStream() {
        guard let self else { return }
        let wasRegistered = self.isRegistered
        self.registrationState = state
        self.note("Autorisation Meta AI : \(Self.describe(state))")
        if self.isRegistered, !wasRegistered {
          self.waitingForMetaAI = nil
          self.note("Lunettes autorisées dans Meta AI ✓", .success)
          if self.running { self.start() }
        }
      }
    })
    tasks.append(Task { [weak self] in
      guard let selector = self?.deviceSelector else { return }
      for await device in selector.activeDeviceStream() {
        guard let self else { return }
        let had = self.hasActiveDevice
        self.hasActiveDevice = device != nil
        if let device {
          if !had { self.note("Lunettes détectées ✓", .success) }
          self.startVoiceInvocations(on: device)
        } else if had {
          self.note("Lunettes perdues : sont-elles allumées et sur ton nez ?", .warning)
        }
      }
    })
  }

  func report(_ text: String) {
    message = text
    note(text, .error)
  }

  func note(_ text: String, _ kind: ActivityEntry.Kind = .info) {
    activity.insert(ActivityEntry(text: text, kind: kind), at: 0)
    if activity.count > 40 { activity.removeLast(activity.count - 40) }
  }

  // MARK: 0. Le gros bouton

  /// Fait tout dans l'ordre : autorisation Meta AI, connexion aux lunettes, caméra.
  /// Chaque étape s'affiche dans le fil d'activité, et un délai signale ce qui bloque.
  func powerOn() {
    message = nil
    if geminiKey.trimmingCharacters(in: .whitespaces).isEmpty && serverURL.trimmingCharacters(in: .whitespaces).isEmpty {
      report("Ajoute d'abord ta clé Gemini : bouton ⚙︎ en haut à droite.")
      return
    }
    running = true
    announcedReady = false
    if !isRegistered {
      note("Étape 1/3 : autorise Lǎoshī dans l'app Meta AI qui va s'ouvrir…")
      register()
      return
    }
    if !hasActiveDevice {
      note("Lunettes pas encore détectées : allume-les et mets-les. J'essaie quand même…", .warning)
    }
    start()
  }

  func powerOff() {
    running = false
    watchdog?.cancel()
    stop()
    note("Arrêté.")
  }

  /// Action du gros bouton (et du bouton photo des lunettes) selon le mode.
  func primaryAction() async {
    switch mode {
    case .look, .walk:
      await scan()
    case .ask:
      if isListening { stopListening() } else { await listenForQuestion() }
    case .challenge:
      if let word = challengeWord {
        await scan(challenge: word.hanzi)
      } else {
        await newChallenge()
      }
    }
  }

  func newChallenge() async {
    let due = vocabulary.due
    let pool = due.isEmpty ? Array(vocabulary.cards.values) : due
    let others = pool.filter { $0.hanzi != challengeWord?.hanzi }
    guard let word = (others.isEmpty ? pool : others).randomElement() else {
      challengeWord = nil
      report("Pas encore de mots à retrouver : utilise d'abord le mode Regarder.")
      return
    }
    challengeWord = word
    note("Défi : trouve « \(word.hanzi) » (\(word.pinyin)).")
    await speaker.speak([
      SpeechSegment(lang: "fr-FR", text: "Trouve autour de toi :"),
      SpeechSegment(lang: "zh-CN", text: word.hanzi),
    ])
  }

  private func modeChanged() {
    autoMode = (mode == .walk && isStreaming)
    stopListening()
    note("Mode \(mode.title) : \(mode.hint)")
    guard isStreaming else { return }
    Task {
      await speaker.speak([SpeechSegment(lang: "fr-FR", text: "Mode \(mode.title).")])
      if mode == .challenge, challengeWord == nil { await newChallenge() }
    }
  }

  /// Appelé une fois, quand la caméra envoie sa première image.
  private func cameraReady() {
    guard !announcedReady else { return }
    announcedReady = true
    watchdog?.cancel()
    note("Étape 3/3 : caméra des lunettes active ✓ Tout est prêt.", .success)
    autoMode = (mode == .walk)
    Task {
      await speaker.speak([SpeechSegment(lang: "fr-FR", text: "Lǎoshī est prêt. Mode \(mode.title).")])
      if mode == .challenge, challengeWord == nil { await newChallenge() }
    }
  }

  /// Si une étape ne finit pas à temps, dire quoi vérifier au lieu de rester muet.
  private func startWatchdog(seconds: Double, _ advice: @escaping @MainActor () -> String?) {
    watchdog?.cancel()
    watchdog = Task { [weak self] in
      try? await Task.sleep(for: .seconds(seconds))
      guard !Task.isCancelled, let self, self.running, let text = advice() else { return }
      self.report(text)
    }
  }

  // MARK: 1. Enregistrement (une seule fois, ouvre l'app Meta AI)

  func register() {
    waitingForMetaAI = "l'autorisation de Lǎoshī"
    Task {
      do {
        try await wearables.startRegistration()
      } catch {
        waitingForMetaAI = nil
        running = false
        report("Autorisation impossible : \(error.localizedDescription)")
      }
    }
  }

  /// Bouton du diagnostic : retire l'autorisation pour pouvoir la refaire proprement.
  func resetRegistration() {
    Task {
      do {
        try await wearables.startUnregistration()
        note("Autorisation retirée. Appuie sur Démarrer pour la refaire.")
      } catch {
        report("Impossible de retirer l'autorisation : \(error.localizedDescription)")
      }
    }
  }

  /// Lien reçu (retour depuis Meta AI). On l'affiche pour savoir si le retour arrive bien.
  func handleOpenURL(_ url: URL) {
    let components = URLComponents(url: url, resolvingAgainstBaseURL: false)
    guard components?.queryItems?.contains(where: { $0.name == "metaWearablesAction" }) == true else {
      note("Lien reçu, mais pas pour les lunettes : \(url.absoluteString)", .warning)
      return
    }
    waitingForMetaAI = nil
    returnCheck?.cancel()
    note("Retour de Meta AI reçu ✓", .success)
    Task {
      do {
        _ = try await wearables.handleUrl(url)
      } catch {
        running = false
        report("Meta AI a répondu par une erreur : \(error.localizedDescription)")
      }
    }
  }

  /// L'app revient au premier plan. Si on attendait Meta AI et que rien n'est arrivé,
  /// on le dit au lieu de rester bloqué.
  func appBecameActive() {
    guard let what = waitingForMetaAI else { return }
    returnCheck?.cancel()
    returnCheck = Task { [weak self] in
      try? await Task.sleep(for: .seconds(4))
      guard let self, !Task.isCancelled, self.waitingForMetaAI == what else { return }
      self.waitingForMetaAI = nil
      if what == "l'autorisation de Lǎoshī" { self.running = false }
      self.report(
        "Meta AI n'a pas confirmé \(what). Vérifie le mode développeur : \(Self.devModeHelp) "
          + "Puis force-quitte Meta AI, garde les lunettes allumées hors de l'étui, et réessaie.")
    }
  }

  static let devModeHelp = "Meta AI › Paramètres › Infos sur l'app : touche 5 fois le numéro de version, puis active le Mode développeur."

  static func describe(_ state: RegistrationState) -> String {
    switch state {
    case .registered: return "autorisée"
    case .registering: return "en cours"
    case .available: return "pas encore faite"
    case .unavailable: return "indisponible (Meta AI installé et à jour ?)"
    @unknown default: return String(describing: state)
    }
  }

  // MARK: 2. « Hey Meta, lance Lǎoshī »

  /// Meta AI ne transmet pas les questions libres aux apps tierces : il peut seulement
  /// lancer (ou ramener au premier plan) une app. On s'en sert comme mot d'éveil :
  /// « Hey Meta, lance Lǎoshī » → les lunettes disent « Oui ? » → on écoute la question
  /// avec le micro des lunettes → le prof répond dans les lunettes.
  ///
  /// Expérimental : à activer dans le Wearables Developer Center (nom prononcé de l'app inclus).
  private func startVoiceInvocations(on device: DeviceIdentifier) {
    do {
      let stream: VoiceInvocationsStream
      if let voiceStream {
        stream = voiceStream
      } else {
        stream = try VoiceInvocationsStream(wearables: wearables)
        voiceStream = stream
        stream.invocationsPublisher.listen { [weak self] invocation in
          guard let launch = invocation as? LaunchApp else { return }
          Task { @MainActor in
            _ = await launch.responseHandle.sendSuccess(actionOutput: nil)
            self?.heyMeta()
          }
        }.store(in: voiceTokens)
        stream.errorPublisher.listen { error in
          NSLog("[Laoshi] Hey Meta : \(error.localizedDescription)")
        }.store(in: voiceTokens)
      }
      try stream.start(deviceIdentifier: device)
    } catch {
      NSLog("[Laoshi] « Hey Meta » indisponible : \(error)")
    }
  }

  private func heyMeta() {
    if isSessionStarted {
      Task { await listenForQuestion() }
    } else {
      listenAfterStart = true
      start()
    }
  }

  // MARK: 3. Session + caméra

  func start() {
    guard session == nil else { return }
    do {
      let newSession = try wearables.createSession(deviceSelector: deviceSelector)
      session = newSession
      newSession.statePublisher.listen { [weak self] state in
        Task { @MainActor in self?.sessionChanged(state) }
      }.store(in: sessionTokens)
      newSession.errorPublisher.listen { [weak self] error in
        Task { @MainActor in self?.report(error.localizedDescription) }
      }.store(in: sessionTokens)
      sessionState = .starting
      note("Étape 2/3 : connexion aux lunettes…")
      try newSession.start()
      startWatchdog(seconds: 20) { [weak self] in
        guard let self, !self.isSessionStarted else { return nil }
        return "Les lunettes ne répondent pas. Vérifie : lunettes allumées et portées, Bluetooth activé, "
          + "mode développeur de Meta AI activé (\(GlassesController.devModeHelp)). Puis Arrêter et Démarrer."
      }
    } catch {
      report("Connexion aux lunettes impossible : \(error.localizedDescription)")
      cleanupSession()
    }
  }

  func stop() {
    autoMode = false
    stopListening()
    speaker.stop()
    session?.stop()
  }

  private func sessionChanged(_ state: DeviceSessionState) {
    sessionState = state
    switch state {
    case .started:
      note("Lunettes connectées ✓ Démarrage de la caméra…", .success)
      startWatchdog(seconds: 25) { [weak self] in
        guard let self, !self.hasFirstFrame else { return nil }
        return "La caméra des lunettes ne s'allume pas. Si Meta AI t'a demandé l'accès à la caméra, accepte-le. "
          + "Sinon : Arrêter, attends 5 secondes, puis Démarrer."
      }
      attachCaptureButton()
      Task {
        await startCamera()
        if listenAfterStart {
          listenAfterStart = false
          await listenForQuestion()
        }
      }
    case .stopped:
      cleanupSession()
      if running { note("Connexion aux lunettes fermée.", .warning) }
    default:
      break
    }
  }

  private func startCamera() async {
    guard let session, camera == nil else { return }
    do {
      if try await wearables.checkPermissionStatus(.camera) != .granted {
        note("Autorise la caméra dans Meta AI (« Toujours autoriser »), Meta AI te renvoie ici.")
        waitingForMetaAI = "l'accès à la caméra"
        // Ouvre l'app Meta AI pour autoriser la caméra, puis revient ici.
        let status = try await wearables.requestPermission(.camera)
        waitingForMetaAI = nil
        guard status == .granted else {
          report("Permission caméra refusée dans Meta AI.")
          return
        }
      }
      // Basse résolution + peu d'images/s = image plus nette (moins de compression Bluetooth).
      let config = StreamConfiguration(videoCodec: .raw, resolution: .medium, frameRate: 15)
      guard let newCamera = try session.addCamera(config: config) else {
        report("Caméra des lunettes indisponible.")
        return
      }
      camera = newCamera
      observe(newCamera.stream)
      streamState = .starting
      newCamera.stream.start()
    } catch {
      waitingForMetaAI = nil
      report("Caméra : \(error.localizedDescription)")
    }
  }

  private func observe(_ stream: MWDATCamera.Stream) {
    stream.statePublisher.listen { [weak self] state in
      Task { @MainActor in
        self?.streamState = state
        if state == .stopped { self?.cleanupStream() }
      }
    }.store(in: streamTokens)

    let box = latestFrame
    stream.videoFramePublisher.listen { [weak self] frame in
      // Hors du thread principal : on garde la dernière image, et on rafraîchit
      // l'aperçu du téléphone ~3 fois par seconde seulement.
      let count = box.store(frame)
      if count == 1 || count % 5 == 0, let image = frame.makeUIImage() {
        Task { @MainActor in
          guard let self else { return }
          self.preview = image
          if !self.hasFirstFrame {
            self.hasFirstFrame = true
            self.cameraReady()
          }
        }
      }
    }.store(in: streamTokens)

    stream.photoDataPublisher.listen { [weak self] photo in
      Task { @MainActor in self?.deliverPhoto(photo.data) }
    }.store(in: streamTokens)

    stream.errorPublisher.listen { [weak self] error in
      Task { @MainActor in self?.report(error.localizedDescription) }
    }.store(in: streamTokens)
  }

  /// Bouton photo de la branche des lunettes → lance une leçon (mains libres).
  /// Expérimental : à activer pour l'app dans le Wearables Developer Center.
  private func attachCaptureButton() {
    #if canImport(MWDATInputs)
    guard let session, inputsTask == nil else { return }
    do {
      let configuration = InputsConfiguration(sources: [.captureButton], consumeBack: false)
      guard let inputs = try session.addInputs(configuration: configuration) else { return }
      note("Bouton photo des lunettes actif ✓", .success)
      inputsTask = Task { [weak self] in
        for await event in inputs.events {
          if case .capture = event { await self?.primaryAction() }
        }
      }
    } catch {
      NSLog("[Laoshi] Bouton des lunettes indisponible : \(error)")
      note("Bouton photo des lunettes non activé (fonction Meta à activer) : utilise le bouton de l'app.", .warning)
    }
    #else
    #warning("MWDATInputs absent : le bouton photo des lunettes est désactivé")
    #endif
  }

  private func cleanupStream() {
    streamTokens.clear()
    camera?.stop()
    camera = nil
    preview = nil
    hasFirstFrame = false
    announcedReady = false
    autoMode = false
    latestFrame.clear()
  }

  private func cleanupSession() {
    cleanupStream()
    stopListening()
    speechTokens.clear()
    #if canImport(MWDATSpeech)
    speech = nil
    #endif
    inputsTask?.cancel()
    inputsTask = nil
    sessionTokens.clear()
    session = nil
    sessionState = .idle
    streamState = .stopped
  }

  // MARK: 4. Écouter une question (micro des lunettes)

  func listenForQuestion() async {
    #if canImport(MWDATSpeech)
    guard let session, session.state == .started else {
      listenAfterStart = true
      start()
      return
    }
    guard !isListening, !isThinking else { return }
    do {
      if try await wearables.checkPermissionStatus(.microphone) != .granted {
        note("Autorise le micro dans Meta AI, Meta AI te renvoie ici.")
        waitingForMetaAI = "l'accès au micro"
        let micStatus = try await wearables.requestPermission(.microphone)
        waitingForMetaAI = nil
        guard micStatus == .granted else {
          report("Permission micro refusée dans Meta AI.")
          return
        }
      }
      if speech == nil {
        guard let newSpeech = try session.addSpeech() else {
          report("Le micro des lunettes n'est pas activé pour l'app (fonction Meta à activer).")
          return
        }
        newSpeech.transcriptionPublisher.listen { [weak self] result in
          let text = result.text
          let isFinal = result.isFinal
          Task { @MainActor in self?.heard(text, isFinal: isFinal) }
        }.store(in: speechTokens)
        newSpeech.errorPublisher.listen { [weak self] error in
          Task { @MainActor in
            self?.stopListening()
            self?.report("Micro : \(error.localizedDescription)")
          }
        }.store(in: speechTokens)
        speech = newSpeech
      }
    } catch {
      report("Micro : \(error.localizedDescription)")
      return
    }

    // Signal sonore dans les lunettes, puis on écoute (pas pendant : il s'entendrait).
    await speaker.speak([SpeechSegment(lang: "fr-FR", text: "Oui ?")])
    note("Je t'écoute… pose ta question.")
    transcript = ""
    isListening = true
    speech?.start()
    listenTimeout?.cancel()
    listenTimeout = Task { [weak self] in
      try? await Task.sleep(for: .seconds(10))
      guard let self, !Task.isCancelled, self.isListening else { return }
      let text = self.transcript
      self.stopListening()
      if !text.isEmpty { await self.ask(text) }
    }
    #else
    #warning("MWDATSpeech absent : les questions à voix haute sont désactivées")
    report("Ajoute le module MWDATSpeech au projet pour poser des questions à voix haute.")
    #endif
  }

  private func heard(_ text: String, isFinal: Bool) {
    guard isListening else { return }
    transcript = text
    if isFinal, !text.trimmingCharacters(in: .whitespaces).isEmpty {
      stopListening()
      Task { await ask(text) }
    }
  }

  func stopListening() {
    listenTimeout?.cancel()
    listenTimeout = nil
    guard isListening else { return }
    isListening = false
    #if canImport(MWDATSpeech)
    speech?.stop()
    #endif
  }

  // MARK: 5. Le prof

  private var client: TutorClient { TutorClient(serverURL: serverURL, token: token) }
  private var direct: GeminiTutor? {
    let key = geminiKey.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !key.isEmpty else { return nil }
    return GeminiTutor(apiKey: key, model: geminiModel) { [weak self] message in
      self?.note(message, .warning)
    }
  }

  /// Question orale : « que veut dire siège en chinois ? ».
  /// On joint la dernière image des lunettes, pour « c'est quoi ça en chinois ? ».
  func ask(_ question: String) async {
    guard !isThinking else { return }
    isThinking = true
    speaker.stop()
    defer { isThinking = false }
    note("« \(question) » — le prof réfléchit…")
    do {
      let image = isStreaming ? latestFrame.jpeg() : nil
      let result: AskResult
      if let direct {
        result = try await direct.ask(question: question, jpeg: image, profile: vocabulary.profile(level: level))
      } else {
        result = try await client.ask(
          question: question, jpeg: image, level: level, known: vocabulary.known, learning: vocabulary.learning)
      }
      // Redemander un mot déjà rencontré, c'est l'avoir oublié : il reviendra vite en révision.
      for word in result.words where vocabulary.cards[word.hanzi] != nil {
        vocabulary.recordForgotten(word.hanzi)
      }
      vocabulary.record(result.words)
      lastAnswer = result
      lastResult = nil
      message = nil
      note(result.words.isEmpty ? "Réponse du prof." : "Réponse : " + result.words.map(\.hanzi).joined(separator: ", "), .success)
      await speaker.speak(
        LessonVoice.ask(intro: result.intro, words: result.words, followup: result.followup, teacherPace: teacherPace))
    } catch {
      report(error.localizedDescription)
      await speaker.speak([SpeechSegment(lang: "fr-FR", text: "Désolé, je n'ai pas pu répondre.")])
    }
  }

  /// Prend une photo avec les lunettes, l'envoie au prof, lit la leçon.
  func scan(challenge: String? = nil) async {
    guard !isThinking else { return }
    guard isStreaming else {
      report("Appuie d'abord sur « Démarrer » pour allumer la caméra des lunettes.")
      return
    }
    isThinking = true
    stopListening()
    speaker.stop()
    defer { isThinking = false }

    note("Photo prise, le prof regarde…")
    guard let jpeg = await takePhoto() else {
      report("Pas d'image des lunettes, réessaie.")
      return
    }
    do {
      let result: ScanResult
      if let direct {
        result = try await direct.scan(
          jpeg: jpeg, profile: vocabulary.profile(level: level), maxNew: maxNew, challenge: challenge)
      } else {
        result = try await client.scan(
          jpeg: jpeg, level: level, maxNew: maxNew, known: vocabulary.known, learning: vocabulary.learning,
          challenge: challenge)
      }
      vocabulary.record(result.words)
      if let challenge, result.challenge?.found == true {
        vocabulary.grade(challenge, good: true)
        challengeWord = nil
        note("Défi réussi ✓ Appuie pour un nouveau défi.", .success)
      }
      lastResult = result
      lastAnswer = nil
      message = nil
      if challenge == nil {
        note(result.words.isEmpty ? "Rien de nouveau ici. Rapproche-toi d'un objet." : "Leçon : " + result.words.map(\.hanzi).joined(separator: ", "), .success)
      }
      await speaker.speak(
        LessonVoice.scan(
          words: result.words, teacher: result.teacher, challenge: result.challenge, teacherPace: teacherPace))
    } catch {
      report(error.localizedDescription)
    }
  }

  /// Photo haute qualité si possible, sinon la dernière image du flux vidéo.
  private func takePhoto() async -> Data? {
    if let camera, camera.stream.capturePhoto(format: .jpeg) {
      photoRequest += 1
      let request = photoRequest
      let data = await withCheckedContinuation { (cont: CheckedContinuation<Data?, Never>) in
        photoWaiter = cont
        Task { @MainActor [weak self] in
          try? await Task.sleep(for: .seconds(6))
          if self?.photoRequest == request { self?.deliverPhoto(nil) }
        }
      }
      if let data { return data }
    }
    return latestFrame.jpeg()
  }

  private func deliverPhoto(_ data: Data?) {
    photoWaiter?.resume(returning: data)
    photoWaiter = nil
  }

  // MARK: Mode balade : une leçon toutes les 15 s, quand le prof a fini de parler

  private func startAutoMode() {
    autoTask?.cancel()
    autoTask = Task { [weak self] in
      while !Task.isCancelled {
        try? await Task.sleep(for: .seconds(15))
        guard let self, !Task.isCancelled else { return }
        if self.isStreaming, !self.isThinking, !self.isListening, !self.speaker.isSpeaking {
          await self.scan()
        }
      }
    }
  }

  private func stopAutoMode() {
    autoTask?.cancel()
    autoTask = nil
  }
}

/// Dernière image vidéo reçue, partagée entre le thread du flux et le thread principal.
final class FrameBox: @unchecked Sendable {
  private let lock = NSLock()
  private var frame: VideoFrame?
  private var count = 0

  /// Garde l'image et renvoie le nombre d'images reçues.
  func store(_ newFrame: VideoFrame) -> Int {
    lock.lock()
    defer { lock.unlock() }
    frame = newFrame
    count += 1
    return count
  }

  func clear() {
    lock.lock()
    frame = nil
    lock.unlock()
  }

  func jpeg() -> Data? {
    lock.lock()
    let current = frame
    lock.unlock()
    return current?.makeUIImage()?.jpegData(compressionQuality: 0.85)
  }
}
