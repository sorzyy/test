import AVFoundation

/// Lit les segments de la leçon à voix haute (chinois / français).
/// Quand les lunettes sont connectées en Bluetooth, le son sort par leurs haut-parleurs.
///
/// Choisit automatiquement la meilleure voix installée (Premium > Améliorée > basique),
/// sauf si l'élève en a choisi une dans les réglages.
@MainActor
final class Speaker: NSObject, AVSpeechSynthesizerDelegate {
  private let synthesizer = AVSpeechSynthesizer()
  private var continuation: CheckedContinuation<Void, Never>?
  private var generation = 0

  /// Vitesse normale de la voix chinoise (AVSpeechUtteranceDefaultSpeechRate ≈ 0.5).
  var chineseRate: Float = (UserDefaults.standard.object(forKey: "voice.zh.rate") as? Float) ?? 0.45 {
    didSet { UserDefaults.standard.set(chineseRate, forKey: "voice.zh.rate") }
  }
  /// Vitesse « lente » du rythme de prof (le mot détaillé avant la vitesse normale).
  var slowRate: Float { max(0.2, chineseRate - 0.17) }

  /// Voix choisies dans les réglages (identifiants iOS) ; nil = la meilleure automatiquement.
  var chineseVoiceID: String? = UserDefaults.standard.string(forKey: "voice.zh") {
    didSet { UserDefaults.standard.set(chineseVoiceID, forKey: "voice.zh") }
  }
  var frenchVoiceID: String? = UserDefaults.standard.string(forKey: "voice.fr") {
    didSet { UserDefaults.standard.set(frenchVoiceID, forKey: "voice.fr") }
  }

  private(set) var isSpeaking = false

  override init() {
    super.init()
    synthesizer.delegate = self
  }

  // MARK: Choix des voix

  /// Voix installées pour une langue (« zh-CN », « fr-FR »), les meilleures d'abord.
  static func voices(for language: String) -> [AVSpeechSynthesisVoice] {
    AVSpeechSynthesisVoice.speechVoices()
      .filter { $0.language == language }
      .sorted { lhs, rhs in
        if lhs.quality.rawValue != rhs.quality.rawValue { return lhs.quality.rawValue > rhs.quality.rawValue }
        return lhs.name < rhs.name
      }
  }

  static func qualityLabel(_ voice: AVSpeechSynthesisVoice) -> String {
    switch voice.quality {
    case .premium: return "Premium"
    case .enhanced: return "Améliorée"
    default: return "Basique"
    }
  }

  func voice(for language: String) -> AVSpeechSynthesisVoice? {
    let chosen = language.hasPrefix("zh") ? chineseVoiceID : frenchVoiceID
    if let chosen, let voice = AVSpeechSynthesisVoice(identifier: chosen) { return voice }
    return Self.voices(for: language).first ?? AVSpeechSynthesisVoice(language: language)
  }

  /// Vrai si seule une voix basique est installée pour cette langue (conseil : télécharger mieux).
  func onlyBasicVoice(for language: String) -> Bool {
    guard let best = Self.voices(for: language).first else { return true }
    return best.quality == .default
  }

  // MARK: Lecture

  func speak(_ segments: [SpeechSegment]) async {
    stop()
    generation += 1
    let current = generation
    activateAudioSession()
    isSpeaking = true
    defer { if current == generation { isSpeaking = false } }
    for segment in segments {
      guard current == generation else { return }
      let utterance = AVSpeechUtterance(string: segment.text)
      utterance.voice = voice(for: segment.lang)
      let isChinese = segment.lang.hasPrefix("zh")
      if isChinese {
        utterance.rate = segment.slow == true ? slowRate : chineseRate
      } else {
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate
      }
      // Silence après chaque morceau : le temps de répéter dans sa tête (ou à voix haute).
      utterance.postUtteranceDelay = segment.pause ?? (isChinese ? 0.45 : 0.25)
      await withCheckedContinuation { cont in
        continuation = cont
        synthesizer.speak(utterance)
      }
    }
  }

  func stop() {
    generation += 1
    if synthesizer.isSpeaking { synthesizer.stopSpeaking(at: .immediate) }
    resume()
    isSpeaking = false
  }

  private func activateAudioSession() {
    let session = AVAudioSession.sharedInstance()
    try? session.setCategory(.playback, mode: .spokenAudio, options: [.duckOthers])
    try? session.setActive(true)
  }

  private func resume() {
    continuation?.resume()
    continuation = nil
  }

  nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
    Task { @MainActor in self.resume() }
  }

  nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
    Task { @MainActor in self.resume() }
  }
}
