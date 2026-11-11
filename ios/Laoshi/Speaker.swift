import AVFoundation

/// Lit les segments de la leçon à voix haute (chinois / français).
/// Quand les lunettes sont connectées en Bluetooth, le son sort par leurs haut-parleurs.
@MainActor
final class Speaker: NSObject, AVSpeechSynthesizerDelegate {
  private let synthesizer = AVSpeechSynthesizer()
  private var continuation: CheckedContinuation<Void, Never>?
  private var generation = 0

  /// Vitesse de la voix chinoise (AVSpeechUtteranceDefaultSpeechRate ≈ 0.5).
  var chineseRate: Float = 0.42

  private(set) var isSpeaking = false

  override init() {
    super.init()
    synthesizer.delegate = self
  }

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
      utterance.voice = AVSpeechSynthesisVoice(language: segment.lang)
      let isChinese = segment.lang.hasPrefix("zh")
      utterance.rate = isChinese ? chineseRate : AVSpeechUtteranceDefaultSpeechRate
      // Petit silence après le chinois : le temps de répéter dans sa tête.
      utterance.postUtteranceDelay = isChinese ? 0.45 : 0.25
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
