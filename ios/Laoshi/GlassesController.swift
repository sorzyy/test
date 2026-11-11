import Foundation
import MWDATCamera
import MWDATCore
import Observation
import UIKit

#if canImport(MWDATInputs)
import MWDATInputs
#endif

/// Pilote les lunettes : enregistrement auprès de Meta AI, session, flux caméra,
/// bouton photo, puis envoi de l'image au prof et lecture de la leçon.
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
  var lastResult: ScanResult?
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

  var isStreaming: Bool { streamState == .streaming }
  var isRegistered: Bool { registrationState == .registered }

  // MARK: Privé

  @ObservationIgnored private let wearables: WearablesInterface
  @ObservationIgnored private let deviceSelector: AutoDeviceSelector
  @ObservationIgnored private var session: DeviceSession?
  @ObservationIgnored private var camera: MWDATCamera.Camera?
  @ObservationIgnored private let sessionTokens = ListenerTokenBag()
  @ObservationIgnored private let streamTokens = ListenerTokenBag()
  @ObservationIgnored private let latestFrame = FrameBox()
  @ObservationIgnored private var photoWaiter: CheckedContinuation<Data?, Never>?
  @ObservationIgnored private var photoRequest = 0
  @ObservationIgnored private var tasks: [Task<Void, Never>] = []
  @ObservationIgnored private var autoTask: Task<Void, Never>?
  @ObservationIgnored private var inputsTask: Task<Void, Never>?
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

  // MARK: 2. Session + caméra

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
    speaker.stop()
    session?.stop()
  }

  private func sessionChanged(_ state: DeviceSessionState) {
    sessionState = state
    switch state {
    case .started:
      Task { await startCamera() }
      attachCaptureButton()
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
  /// Fonction expérimentale du SDK : elle doit être activée pour l'app dans le
  /// Wearables Developer Center. Sans elle, on utilise le bouton du téléphone ou le mode balade.
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
    inputsTask?.cancel()
    inputsTask = nil
    sessionTokens.clear()
    session = nil
    sessionState = .idle
    streamState = .stopped
  }

  // MARK: 3. Leçon

  /// Prend une photo avec les lunettes, l'envoie au prof, lit la leçon.
  func scan(challenge: String? = nil) async {
    guard !isThinking else { return }
    guard isStreaming else {
      report("Lance d'abord la caméra des lunettes.")
      return
    }
    isThinking = true
    speaker.stop()
    defer { isThinking = false }

    guard let jpeg = await takePhoto() else {
      report("Pas d'image des lunettes, réessaie.")
      return
    }
    do {
      let client = TutorClient(serverURL: serverURL, token: token)
      let result = try await client.scan(
        jpeg: jpeg,
        level: level,
        maxNew: maxNew,
        known: vocabulary.known,
        learning: vocabulary.learning,
        challenge: challenge
      )
      vocabulary.record(result.words)
      if let challenge, result.challenge?.found == true {
        vocabulary.grade(challenge, good: true)
      }
      lastResult = result
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
        if self.isStreaming, !self.isThinking, !self.speaker.isSpeaking {
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
