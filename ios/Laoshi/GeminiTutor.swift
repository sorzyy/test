import Foundation
import Security

/// Mode direct : l'app parle elle-même à Gemini, sans serveur.
/// La clé reste dans le trousseau de l'iPhone (voir `KeyStore`).
/// Le « skill prof » (`TeacherSkill`) donne à Gemini sa personnalité et sa méthode ;
/// le profil de l'élève (`LearnerProfile`) lui dit où en est l'élève.
struct GeminiTutor {
  var apiKey: String
  var model: String = "gemini-3.5-flash"
  /// Prévenu quand Gemini est surchargé et qu'on bascule sur un autre modèle.
  var onFallback: (@MainActor (String) -> Void)? = nil

  /// Modèles de secours, essayés dans l'ordre si le premier est surchargé ou indisponible.
  static let fallbackModels = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]

  // MARK: API publique

  func scan(jpeg: Data, profile: LearnerProfile, maxNew: Int, challenge: String? = nil) async throws -> ScanResult {
    var lines = Self.profileLines(profile)
    lines.append("Mots nouveaux maximum : \(maxNew)")
    lines.append(challenge.map { "Défi : trouver « \($0) »" } ?? "Défi : aucun")
    lines.append("Fais la mini-leçon pour cette photo.")
    let raw: RawScan = try await generate(
      system: TeacherSkill.skill + "\n\n" + TeacherSkill.scanTask,
      text: lines.joined(separator: "\n"),
      schema: Self.scanSchema,
      jpeg: jpeg
    )
    let words = Self.buildWords(
      raw.objects ?? [], known: profile.known, learning: profile.learning, maxNew: maxNew, limit: 6)
    let teacher = raw.teacher?.sentence ?? Sentence(zh: "", pinyin: "", fr: "")
    var challengeResult: ChallengeResult?
    if let challenge {
      challengeResult = ChallengeResult(
        target: challenge,
        found: raw.challenge?.found ?? false,
        feedback: raw.challenge?.feedback ?? "Je n'ai pas pu vérifier le défi."
      )
    }
    return ScanResult(
      scene: raw.scene ?? "",
      words: words,
      teacher: teacher,
      challenge: challengeResult,
      speech: LessonVoice.scan(words: words, teacher: teacher, challenge: challengeResult, teacherPace: true),
      demo: false
    )
  }

  func ask(question: String, jpeg: Data?, profile: LearnerProfile) async throws -> AskResult {
    var lines = Self.profileLines(profile)
    lines.append(jpeg == nil ? "Photo jointe : non" : "Photo jointe : oui")
    lines.append("Question de l'élève : « \(question.trimmingCharacters(in: .whitespacesAndNewlines)) »")
    let raw: RawAsk = try await generate(
      system: TeacherSkill.skill + "\n\n" + TeacherSkill.askTask,
      text: lines.joined(separator: "\n"),
      schema: Self.askSchema,
      jpeg: jpeg
    )
    let words = Self.buildWords(raw.words ?? [], known: profile.known, learning: profile.learning, maxNew: nil, limit: 2)
    var intro = (raw.intro ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    let followup = (raw.followup ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    if words.isEmpty && intro.isEmpty { intro = "Je n'ai pas compris la question, tu peux répéter ?" }
    return AskResult(
      question: question,
      intro: intro,
      words: words,
      followup: followup,
      speech: LessonVoice.ask(intro: intro, words: words, followup: followup, teacherPace: true),
      demo: false
    )
  }

  // MARK: Appel HTTP à Gemini, avec bascule automatique

  private enum Attempt: Error {
    case retryable(String)
  }

  private func generate<T: Decodable>(system: String, text: String, schema: String, jpeg: Data?) async throws -> T {
    guard !apiKey.isEmpty else { throw TutorClientError.server("Ajoute ta clé Gemini dans les réglages.") }
    var models = [model]
    for candidate in Self.fallbackModels where !models.contains(candidate) { models.append(candidate) }

    var lastProblem = "Gemini est indisponible, réessaie."
    for (index, candidate) in models.enumerated() {
      do {
        let value: T = try await generateOnce(model: candidate, system: system, text: text, schema: schema, jpeg: jpeg)
        return value
      } catch Attempt.retryable(let problem) {
        lastProblem = problem
        if index + 1 < models.count, let onFallback {
          await onFallback("Gemini surchargé (\(candidate)), j'essaie \(models[index + 1])…")
        }
        continue
      }
    }
    throw TutorClientError.server(lastProblem)
  }

  private func generateOnce<T: Decodable>(
    model: String, system: String, text: String, schema: String, jpeg: Data?
  ) async throws -> T {
    guard let url = URL(string: "https://generativelanguage.googleapis.com/v1beta/models/\(model):generateContent") else {
      throw TutorClientError.server("Nom de modèle Gemini invalide.")
    }
    var parts: [[String: Any]] = []
    if let jpeg {
      parts.append(["inlineData": ["mimeType": "image/jpeg", "data": jpeg.base64EncodedString()]])
    }
    parts.append(["text": text])
    let schemaObject = try JSONSerialization.jsonObject(with: Data(schema.utf8))
    let body: [String: Any] = [
      "systemInstruction": ["parts": [["text": system]]],
      "contents": [["role": "user", "parts": parts]],
      "generationConfig": [
        "responseMimeType": "application/json",
        "responseJsonSchema": schemaObject,
        "maxOutputTokens": 8000,
        "thinkingConfig": ["thinkingLevel": "LOW"],
      ],
    ]

    // Dans des lunettes, une réponse trop lente ne sert plus à rien : on passe au modèle suivant.
    var request = URLRequest(url: url, timeoutInterval: 20)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue(apiKey, forHTTPHeaderField: "x-goog-api-key")
    request.httpBody = try JSONSerialization.data(withJSONObject: body)

    let data: Data
    let response: URLResponse
    do {
      (data, response) = try await URLSession.shared.data(for: request)
    } catch let error as URLError where error.code == .timedOut || error.code == .networkConnectionLost {
      throw Attempt.retryable("Gemini met trop de temps à répondre, réessaie.")
    } catch let error as URLError where error.code == .notConnectedToInternet {
      throw TutorClientError.server("Pas de connexion internet.")
    }
    let status = (response as? HTTPURLResponse)?.statusCode ?? 0
    guard (200..<300).contains(status) else {
      switch status {
      case 400, 401, 403: throw TutorClientError.server("Clé Gemini refusée. Vérifie-la dans les réglages.")
      case 404: throw Attempt.retryable("Modèle Gemini introuvable : \(model).")
      case 429: throw Attempt.retryable("Quota Gemini atteint, réessaie dans un moment.")
      default: throw Attempt.retryable("Gemini est indisponible (\(status)), réessaie.")
      }
    }
    let reply = try JSONDecoder().decode(GeminiResponse.self, from: data)
    guard let candidate = reply.candidates?.first else {
      throw TutorClientError.server("Je ne peux pas analyser ça. Vise plutôt des objets.")
    }
    let finish = candidate.finishReason ?? ""
    if ["SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "IMAGE_SAFETY"].contains(finish) {
      throw TutorClientError.server("Je ne peux pas analyser ça. Vise plutôt des objets.")
    }
    if finish == "MAX_TOKENS" { throw Attempt.retryable("Réponse trop longue, réessaie.") }
    let json = (candidate.content?.parts ?? [])
      .filter { $0.thought != true }
      .compactMap(\.text)
      .joined()
    guard let jsonData = json.data(using: .utf8), let value = try? JSONDecoder().decode(T.self, from: jsonData) else {
      throw Attempt.retryable("Réponse illisible, réessaie.")
    }
    return value
  }

  // MARK: Mise en forme

  static func isHanzi(_ text: String) -> Bool {
    !text.isEmpty
      && text.unicodeScalars.allSatisfy {
        (0x3400...0x4DBF).contains($0.value) || (0x4E00...0x9FFF).contains($0.value) || (0xF900...0xFAFF).contains($0.value)
      }
  }

  static func containsHanzi(_ text: String) -> Bool {
    text.unicodeScalars.contains { (0x3400...0x4DBF).contains($0.value) || (0x4E00...0x9FFF).contains($0.value) }
  }

  static func buildWords(_ objects: [RawWord], known: [String], learning: [String], maxNew: Int?, limit: Int) -> [Word] {
    let knownSet = Set(known)
    let learningSet = Set(learning)
    var seen = Set<String>()
    var newCount = 0
    var words: [Word] = []
    for object in objects {
      let hanzi = (object.hanzi ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
      guard isHanzi(hanzi), !seen.contains(hanzi) else { continue }
      let status = knownSet.contains(hanzi) ? "known" : learningSet.contains(hanzi) ? "review" : "new"
      if status == "new", let maxNew {
        if newCount >= maxNew { continue }
        newCount += 1
      }
      seen.insert(hanzi)
      words.append(
        Word(
          hanzi: hanzi,
          pinyin: (object.pinyin ?? "").trimmingCharacters(in: .whitespaces),
          fr: (object.fr ?? "").trimmingCharacters(in: .whitespaces),
          where: (object.where ?? "").trimmingCharacters(in: .whitespaces),
          hsk: max(1, min(7, object.hsk ?? 7)),
          measure: fixedMeasure(object.measure?.sentence ?? Sentence(zh: "", pinyin: "", fr: "")),
          example: object.example?.sentence ?? Sentence(zh: "", pinyin: "", fr: ""),
          tip: (object.tip ?? "").trimmingCharacters(in: .whitespaces),
          status: status,
          pinyinCheck: nil
        ))
      if words.count >= limit { break }
    }
    return words
  }

  /// « 扇窗户 » + « yí shàn chuāng hu » → « 一扇窗户 » : le 一 oublié dans les caractères.
  static func fixedMeasure(_ measure: Sentence) -> Sentence {
    let pinyin = measure.pinyin.lowercased()
    guard !measure.zh.isEmpty, !measure.zh.hasPrefix("一"),
      pinyin.hasPrefix("yí ") || pinyin.hasPrefix("yì ") || pinyin.hasPrefix("yī ")
    else { return measure }
    return Sentence(zh: "一" + measure.zh, pinyin: measure.pinyin, fr: measure.fr)
  }

  static func profileLines(_ profile: LearnerProfile) -> [String] {
    func list(_ items: [String], max: Int = 300) -> String {
      let text = items.suffix(max).joined(separator: "、")
      return text.isEmpty ? "(aucun)" : text
    }
    return [
      "Profil de l'élève :",
      "- Niveau : \(profile.level) ; \(profile.totalWords) mots rencontrés, dont \(profile.known.count) maîtrisés ; série : \(profile.streakDays) jour(s)",
      "- Mots déjà connus : \(list(profile.known))",
      "- Mots en cours d'apprentissage : \(list(profile.learning))",
      "- Mots qu'il oublie souvent (réutilise-les dès que c'est naturel) : \(list(profile.struggling, max: 15))",
      "- Derniers mots vus : \(list(profile.recent, max: 10))",
    ]
  }

  // MARK: Format brut renvoyé par Gemini (tous les champs optionnels : on ne fait pas confiance)

  struct RawSentence: Decodable {
    let zh: String?
    let pinyin: String?
    let fr: String?
    var sentence: Sentence { Sentence(zh: zh ?? "", pinyin: pinyin ?? "", fr: fr ?? "") }
  }

  struct RawWord: Decodable {
    let hanzi: String?
    let pinyin: String?
    let fr: String?
    let `where`: String?
    let hsk: Int?
    let measure: RawSentence?
    let example: RawSentence?
    let tip: String?
  }

  struct RawChallenge: Decodable {
    let found: Bool?
    let feedback: String?
  }

  struct RawScan: Decodable {
    let scene: String?
    let objects: [RawWord]?
    let teacher: RawSentence?
    let challenge: RawChallenge?
  }

  struct RawAsk: Decodable {
    let intro: String?
    let words: [RawWord]?
    let followup: String?
  }

  private struct GeminiResponse: Decodable {
    struct Part: Decodable {
      let text: String?
      let thought: Bool?
    }
    struct Content: Decodable { let parts: [Part]? }
    struct Candidate: Decodable {
      let content: Content?
      let finishReason: String?
    }
    let candidates: [Candidate]?
  }

  // MARK: Schémas JSON (format Gemini, sans « additionalProperties »)

  private static let sentenceSchema = """
    {"type":"object","properties":{"zh":{"type":"string"},"pinyin":{"type":"string"},"fr":{"type":"string"}},"required":["zh","pinyin","fr"]}
    """

  private static let wordSchema = """
    {"type":"object","properties":{"hanzi":{"type":"string"},"pinyin":{"type":"string"},"fr":{"type":"string"},"where":{"type":"string"},"hsk":{"type":"integer"},"measure":\(sentenceSchema),"example":\(sentenceSchema),"tip":{"type":"string"}},"required":["hanzi","pinyin","fr","where","hsk","measure","example","tip"]}
    """

  static let scanSchema = """
    {"type":"object","properties":{"scene":{"type":"string"},"objects":{"type":"array","items":\(wordSchema)},"teacher":\(sentenceSchema),"challenge":{"anyOf":[{"type":"object","properties":{"found":{"type":"boolean"},"feedback":{"type":"string"}},"required":["found","feedback"]},{"type":"null"}]}},"required":["scene","objects","teacher","challenge"]}
    """

  static let askSchema = """
    {"type":"object","properties":{"intro":{"type":"string"},"words":{"type":"array","items":\(wordSchema)},"followup":{"type":"string"}},"required":["intro","words","followup"]}
    """
}

// MARK: - Ce que les lunettes disent, et dans quel ordre

/// Le « rythme de prof » : le mot lentement, puis à vitesse normale, le sens,
/// un exemple, puis « À toi ! » avec un vrai silence pour répéter à voix haute.
enum LessonVoice {
  static func scan(words: [Word], teacher: Sentence, challenge: ChallengeResult?, teacherPace: Bool) -> [SpeechSegment] {
    var segments: [SpeechSegment] = []
    if let challenge { segments.append(SpeechSegment(lang: "fr-FR", text: challenge.feedback)) }
    var invitedToRepeat = false
    for word in words {
      switch word.status {
      case "new":
        if teacherPace {
          segments.append(SpeechSegment(lang: "zh-CN", text: word.hanzi, slow: true, pause: 0.6))
        }
        segments += [
          SpeechSegment(lang: "zh-CN", text: word.hanzi),
          SpeechSegment(lang: "fr-FR", text: word.fr),
        ]
        if teacherPace && !invitedToRepeat {
          // Une seule fois par leçon, pour ne pas lasser.
          invitedToRepeat = true
          segments.append(SpeechSegment(lang: "fr-FR", text: "À toi !", pause: 2.2))
          segments.append(SpeechSegment(lang: "zh-CN", text: word.hanzi, pause: 0.8))
        }
        segments += [
          SpeechSegment(lang: "zh-CN", text: word.measure.zh),
          SpeechSegment(lang: "zh-CN", text: word.example.zh),
          SpeechSegment(lang: "fr-FR", text: word.example.fr),
        ]
      case "review":
        // Rappel actif : le chinois, un temps pour chercher, puis la réponse.
        segments += [
          SpeechSegment(lang: "zh-CN", text: word.hanzi, pause: teacherPace ? 1.6 : 0.6),
          SpeechSegment(lang: "fr-FR", text: word.fr),
        ]
      default:
        break
      }
    }
    if !teacher.zh.isEmpty {
      // La question du prof, un temps pour répondre, puis la traduction en aide.
      segments.append(SpeechSegment(lang: "zh-CN", text: teacher.zh, pause: teacherPace ? 2.5 : 0.45))
      if teacherPace, !teacher.fr.isEmpty { segments.append(SpeechSegment(lang: "fr-FR", text: teacher.fr)) }
    }
    return segments.filter { !$0.text.isEmpty }
  }

  static func ask(intro: String, words: [Word], followup: String, teacherPace: Bool) -> [SpeechSegment] {
    var spokenIntro = intro
    if GeminiTutor.containsHanzi(spokenIntro) { spokenIntro = words.isEmpty ? "" : "Voici la réponse :" }
    var segments: [SpeechSegment] = spokenIntro.isEmpty ? [] : [SpeechSegment(lang: "fr-FR", text: spokenIntro)]
    for (index, word) in words.enumerated() {
      if index > 0 { segments.append(SpeechSegment(lang: "fr-FR", text: "Et aussi, pour « \(word.fr) » :")) }
      if teacherPace {
        segments += [
          SpeechSegment(lang: "zh-CN", text: word.hanzi, slow: true, pause: 0.6),
          SpeechSegment(lang: "zh-CN", text: word.hanzi),
        ]
        if index == 0 {
          segments.append(SpeechSegment(lang: "fr-FR", text: "À toi !", pause: 2.2))
        }
      } else {
        segments += [SpeechSegment(lang: "zh-CN", text: word.hanzi), SpeechSegment(lang: "zh-CN", text: word.hanzi)]
      }
      segments += [
        SpeechSegment(lang: "zh-CN", text: word.example.zh),
        SpeechSegment(lang: "fr-FR", text: word.example.fr),
      ]
    }
    if !followup.isEmpty, !GeminiTutor.containsHanzi(followup) { segments.append(SpeechSegment(lang: "fr-FR", text: followup)) }
    return segments.filter { !$0.text.isEmpty }
  }
}

/// Petit coffre pour la clé Gemini : le trousseau iOS (chiffré, propre à l'app).
enum KeyStore {
  private static let service = "laoshi.gemini"

  static func load() -> String {
    let query: [String: Any] = [
      kSecClass as String: kSecClassGenericPassword,
      kSecAttrService as String: service,
      kSecReturnData as String: true,
      kSecMatchLimit as String: kSecMatchLimitOne,
    ]
    var item: CFTypeRef?
    guard SecItemCopyMatching(query as CFDictionary, &item) == errSecSuccess, let data = item as? Data else { return "" }
    return String(decoding: data, as: UTF8.self)
  }

  static func save(_ key: String) {
    let base: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: service]
    SecItemDelete(base as CFDictionary)
    guard !key.isEmpty else { return }
    var add = base
    add[kSecValueData as String] = Data(key.utf8)
    add[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
    SecItemAdd(add as CFDictionary, nil)
  }
}
