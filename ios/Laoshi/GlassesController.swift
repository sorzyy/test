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
        self?.registrationState = state
      }
    })
    tasks.append(Task { [weak self] in
      guard let selector = self?.deviceSelector else { return }
      for await device in selector.activeDeviceStream() {
        self?.hasActiveDevice = device != nil
        if let device { self?.startVoiceInvocations(on: device) }
      }
    })
  }

  func report(_ text: String) { message = text }

  // MARK: 1. Enregistrement (une seule fois, ouvre l'app Meta AI)

  func register() {
    Task {
      do {
        try await wearables.startRegistration()
      } catch {
        report("Enregistrement : \(error.localizedDescription)")
      }
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
      try newSession.start()
    } catch {
      report("Session : \(error.localizedDescription)")
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
    default:
      break
    }
  }

  private func startCamera() async {
    guard let session, camera == nil else { return }
    do {
      if try await wearables.checkPermissionStatus(.camera) != .granted {
        // Ouvre l'app Meta AI pour autoriser la caméra, puis revient ici.
        guard try await wearables.requestPermission(.camera) == .granted else {
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
      if box.store(frame) % 5 == 0, let image = frame.makeUIImage() {
        Task { @MainActor in self?.preview = image }
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
      inputsTask = Task { [weak self] in
        for await event in inputs.events {
          if case .capture = event { await self?.scan() }
        }
      }
    } catch {
      NSLog("[Laoshi] Bouton des lunettes indisponible : \(error)")
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
        guard try await wearables.requestPermission(.microphone) == .granted else {
          report("Permission micro refusée dans Meta AI.")
          return
        }
      }
      if speech == nil {
        guard let newSpeech = try session.addSpeech() else {
          report("Reconnaissance vocale indisponible sur ces lunettes.")
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
    return key.isEmpty ? nil : GeminiTutor(apiKey: key, model: geminiModel)
  }

  /// Question orale : « que veut dire siège en chinois ? ».
  /// On joint la dernière image des lunettes, pour « c'est quoi ça en chinois ? ».
  func ask(_ question: String) async {
    guard !isThinking else { return }
    isThinking = true
    speaker.stop()
    defer { isThinking = false }
    do {
      let image = isStreaming ? latestFrame.jpeg() : nil
      let result: AskResult
      if let direct {
        result = try await direct.ask(
          question: question, jpeg: image, level: level, known: vocabulary.known, learning: vocabulary.learning)
      } else {
        result = try await client.ask(
          question: question, jpeg: image, level: level, known: vocabulary.known, learning: vocabulary.learning)
      }
      vocabulary.record(result.words)
      lastAnswer = result
      lastResult = nil
      message = nil
      await speaker.speak(result.speech)
    } catch {
      report(error.localizedDescription)
      await speaker.speak([SpeechSegment(lang: "fr-FR", text: "Désolé, je n'ai pas pu répondre.")])
    }
  }

  /// Prend une photo avec les lunettes, l'envoie au prof, lit la leçon.
  func scan(challenge: String? = nil) async {
    guard !isThinking else { return }
    guard isStreaming else {
      report("Lance d'abord la caméra des lunettes.")
      return
    }
    isThinking = true
    stopListening()
    speaker.stop()
    defer { isThinking = false }

    guard let jpeg = await takePhoto() else {
      report("Pas d'image des lunettes, réessaie.")
      return
    }
    do {
      let result: ScanResult
      if let direct {
        result = try await direct.scan(
          jpeg: jpeg, level: level, maxNew: maxNew, known: vocabulary.known, learning: vocabulary.learning,
          challenge: challenge)
      } else {
        result = try await client.scan(
          jpeg: jpeg, level: level, maxNew: maxNew, known: vocabulary.known, learning: vocabulary.learning,
          challenge: challenge)
      }
      vocabulary.record(result.words)
      if let challenge, result.challenge?.found == true {
        vocabulary.grade(challenge, good: true)
      }
      lastResult = result
      lastAnswer = nil
      message = nil
      await speaker.speak(result.speech)
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
