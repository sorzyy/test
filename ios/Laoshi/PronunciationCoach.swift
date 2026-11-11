import AVFoundation
import Foundation
import Observation
import Speech

/// « Répète après moi » : l'élève prononce un mot, la reconnaissance vocale d'iOS
/// (en chinois, sur l'iPhone quand c'est possible) écoute, puis on compare syllabe par syllabe :
/// mot juste, ton raté, ou autre mot entendu.
///
/// Le micro utilisé est celui des lunettes quand elles sont connectées en Bluetooth
/// (profil mains libres), sinon celui de l'iPhone.
@Observable
@MainActor
final class PronunciationCoach {
  enum Verdict: Equatable {
    case perfect
    case wrongTone(position: Int, expected: String, heard: String)
    case different(heardHanzi: String, heardPinyin: String)
    case nothingHeard
    case unavailable(String)
  }

  private(set) var isListening = false
  private(set) var heard = ""

  @ObservationIgnored private let recognizer = SFSpeechRecognizer(locale: Locale(identifier: "zh-CN"))
  @ObservationIgnored private let engine = AVAudioEngine()
  @ObservationIgnored private var request: SFSpeechAudioBufferRecognitionRequest?
  @ObservationIgnored private var task: SFSpeechRecognitionTask?
  @ObservationIgnored private var finished: CheckedContinuation<Void, Never>?

  // MARK: Écouter

  /// Écoute jusqu'à `seconds` secondes (ou jusqu'à la fin de la phrase), puis compare au mot attendu.
  func listen(expected: String, seconds: Double = 4) async -> Verdict {
    guard !isListening else { return .nothingHeard }
    guard await Self.authorize() else {
      return .unavailable("Autorise la reconnaissance vocale et le micro pour Lǎoshī dans les réglages de l'iPhone.")
    }
    guard let recognizer, recognizer.isAvailable else {
      return .unavailable("La reconnaissance vocale en chinois n'est pas disponible sur cet iPhone pour l'instant.")
    }

    heard = ""
    let request = SFSpeechAudioBufferRecognitionRequest()
    request.shouldReportPartialResults = true
    request.contextualStrings = [expected]
    if recognizer.supportsOnDeviceRecognition { request.requiresOnDeviceRecognition = true }
    self.request = request

    do {
      let session = AVAudioSession.sharedInstance()
      try session.setCategory(.playAndRecord, mode: .measurement, options: [.allowBluetooth, .duckOthers])
      try session.setActive(true)
      let input = engine.inputNode
      let format = input.outputFormat(forBus: 0)
      input.removeTap(onBus: 0)
      input.installTap(onBus: 0, bufferSize: 1024, format: format) { buffer, _ in
        request.append(buffer)
      }
      engine.prepare()
      try engine.start()
    } catch {
      cleanup()
      return .unavailable("Micro indisponible : \(error.localizedDescription)")
    }

    isListening = true
    task = recognizer.recognitionTask(with: request) { [weak self] result, error in
      let text = result?.bestTranscription.formattedString
      let isFinal = result?.isFinal ?? false
      Task { @MainActor in
        guard let self else { return }
        if let text { self.heard = text }
        if isFinal || error != nil { self.finish() }
      }
    }

    // Fin au plus tard après `seconds` secondes.
    let deadline = Task { [weak self] in
      try? await Task.sleep(for: .seconds(seconds))
      guard !Task.isCancelled else { return }
      self?.request?.endAudio()
      try? await Task.sleep(for: .seconds(1.2))
      guard !Task.isCancelled else { return }
      self?.finish()
    }
    await withCheckedContinuation { continuation in finished = continuation }
    deadline.cancel()
    cleanup()
    return Self.compare(expected: expected, heard: heard)
  }

  func stop() {
    request?.endAudio()
  }

  private func finish() {
    finished?.resume()
    finished = nil
  }

  private func cleanup() {
    if engine.isRunning { engine.stop() }
    engine.inputNode.removeTap(onBus: 0)
    task?.cancel()
    task = nil
    request = nil
    isListening = false
    // La voix du prof reprend la sortie audio normale (Speaker remet .playback avant de parler).
    try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
  }

  private static func authorize() async -> Bool {
    let speech = await withCheckedContinuation { (continuation: CheckedContinuation<Bool, Never>) in
      SFSpeechRecognizer.requestAuthorization { status in continuation.resume(returning: status == .authorized) }
    }
    guard speech else { return false }
    return await AVAudioApplication.requestRecordPermission()
  }

  // MARK: Comparer

  static func compare(expected: String, heard: String) -> Verdict {
    let cleanHeard = heard.unicodeScalars.filter { GeminiTutor.containsHanzi(String($0)) }.map(String.init).joined()
    guard !cleanHeard.isEmpty else { return .nothingHeard }
    if cleanHeard.contains(expected) { return .perfect }

    let expectedSyllables = syllables(of: expected)
    let heardSyllables = syllables(of: cleanHeard)
    // Même nombre de syllabes et mêmes sons : seul un ton diffère.
    if expectedSyllables.count == heardSyllables.count, !expectedSyllables.isEmpty {
      var toneMistake: (Int, String, String)?
      var sameSounds = true
      for (index, (want, got)) in zip(expectedSyllables, heardSyllables).enumerated() {
        if base(want) != base(got) {
          sameSounds = false
          break
        }
        if tone(want) != tone(got), toneMistake == nil { toneMistake = (index, want, got) }
      }
      if sameSounds, let (index, want, got) = toneMistake {
        return .wrongTone(position: index, expected: want, heard: got)
      }
      if sameSounds { return .perfect }  // mêmes sons et tons, autres caractères (homophones)
    }
    return .different(heardHanzi: cleanHeard, heardPinyin: heardSyllables.joined(separator: " "))
  }

  /// Pinyin avec tons, syllabe par syllabe, calculé par iOS (« 椅子 » → ["yǐ", "zi"]).
  static func syllables(of hanzi: String) -> [String] {
    let text = NSMutableString(string: hanzi)
    CFStringTransform(text, nil, kCFStringTransformMandarinLatin, false)
    return (text as String).split(separator: " ").map { String($0).lowercased() }
  }

  /// Syllabe sans ton : « yǐ » → « yi ».
  static func base(_ syllable: String) -> String {
    let text = NSMutableString(string: syllable)
    CFStringTransform(text, nil, kCFStringTransformStripCombiningMarks, false)
    return (text as String).replacingOccurrences(of: "ü", with: "v")
  }

  /// Ton d'une syllabe (1 à 4, 5 = neutre).
  static func tone(_ syllable: String) -> Int {
    for scalar in syllable.decomposedStringWithCanonicalMapping.unicodeScalars {
      switch scalar.value {
      case 0x0304: return 1
      case 0x0301: return 2
      case 0x030C: return 3
      case 0x0300: return 4
      default: continue
      }
    }
    return 5
  }

  // MARK: Ce que dit le prof

  static func feedback(_ verdict: Verdict, word: String, pinyin: String) -> (text: String, speech: [SpeechSegment]) {
    switch verdict {
    case .perfect:
      let praise = ["Parfait !", "Excellent !", "Très bien, c'est ça !", "Bravo, impeccable !"].randomElement() ?? "Parfait !"
      return (praise + " 👏", [SpeechSegment(lang: "fr-FR", text: praise)])
    case .wrongTone(let position, let expected, let heard):
      let names = [1: "1er ton, plat et haut", 2: "2e ton, qui monte", 3: "3e ton, qui descend puis remonte", 4: "4e ton, qui tombe", 5: "ton neutre, court et léger"]
      let rank = position == 0 ? "la 1re syllabe" : "la \(position + 1)e syllabe"
      let text = "Presque ! Pour \(rank), il faut le \(names[tone(expected)] ?? "bon ton") (\(expected)). J'ai entendu \(heard)."
      return (
        text,
        [
          SpeechSegment(lang: "fr-FR", text: "Presque ! Attention au ton de \(rank). Écoute :"),
          SpeechSegment(lang: "zh-CN", text: word, slow: true, pause: 0.5),
          SpeechSegment(lang: "zh-CN", text: word),
        ]
      )
    case .different(let heardHanzi, let heardPinyin):
      return (
        "J'ai compris « \(heardHanzi) » (\(heardPinyin)). On attendait \(pinyin). Réessaie !",
        [
          SpeechSegment(lang: "fr-FR", text: "Pas tout à fait. Écoute bien :"),
          SpeechSegment(lang: "zh-CN", text: word, slow: true, pause: 0.5),
          SpeechSegment(lang: "zh-CN", text: word),
        ]
      )
    case .nothingHeard:
      return ("Je n'ai rien entendu. Parle un peu plus fort, juste après le signal.", [
        SpeechSegment(lang: "fr-FR", text: "Je n'ai rien entendu. Réessaie un peu plus fort."),
      ])
    case .unavailable(let reason):
      return (reason, [])
    }
  }
}
