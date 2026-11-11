import Foundation
import Security

/// Mode direct : l'app parle elle-même à Gemini, sans serveur.
/// La clé reste dans le trousseau de l'iPhone (voir `KeyStore`).
/// Mêmes consignes, même format de réponse et mêmes règles que le serveur (server/app/tutor.py),
/// sauf la vérification du pinyin par dictionnaire, qui n'existe que côté serveur.
struct GeminiTutor {
  var apiKey: String
  var model: String = "gemini-3.5-flash"

  // MARK: API publique

  func scan(
    jpeg: Data,
    level: String,
    maxNew: Int,
    known: [String],
    learning: [String],
    challenge: String? = nil
  ) async throws -> ScanResult {
    var lines = Self.learnerLines(level: level, known: known, learning: learning)
    lines.append("Mots nouveaux maximum : \(maxNew)")
    lines.append(challenge.map { "Défi : trouver « \($0) »" } ?? "Défi : aucun")
    lines.append("Fais la mini-leçon pour cette photo.")
    let raw: RawScan = try await generate(
      system: Self.teachingRules + "\n" + Self.scanTask,
      text: lines.joined(separator: "\n"),
      schema: Self.scanSchema,
      jpeg: jpeg
    )
    let words = Self.buildWords(raw.objects ?? [], known: known, learning: learning, maxNew: maxNew, limit: 6)
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
      speech: Self.scanSpeech(words: words, teacher: teacher, challenge: challengeResult),
      demo: false
    )
  }

  func ask(question: String, jpeg: Data?, level: String, known: [String], learning: [String]) async throws -> AskResult {
    var lines = Self.learnerLines(level: level, known: known, learning: learning)
    lines.append(jpeg == nil ? "Photo jointe : non" : "Photo jointe : oui")
    lines.append("Question de l'élève : « \(question.trimmingCharacters(in: .whitespacesAndNewlines)) »")
    let raw: RawAsk = try await generate(
      system: Self.teachingRules + "\n" + Self.askTask,
      text: lines.joined(separator: "\n"),
      schema: Self.askSchema,
      jpeg: jpeg
    )
    let words = Self.buildWords(raw.words ?? [], known: known, learning: learning, maxNew: nil, limit: 2)
    var intro = (raw.intro ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    let followup = (raw.followup ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    if words.isEmpty && intro.isEmpty { intro = "Je n'ai pas compris la question, tu peux répéter ?" }
    return AskResult(
      question: question,
      intro: intro,
      words: words,
      followup: followup,
      speech: Self.askSpeech(intro: intro, words: words, followup: followup),
      demo: false
    )
  }

  // MARK: Appel HTTP à Gemini

  private func generate<T: Decodable>(system: String, text: String, schema: String, jpeg: Data?) async throws -> T {
    guard !apiKey.isEmpty else { throw TutorClientError.server("Ajoute ta clé Gemini dans les réglages.") }
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

    // Dans des lunettes, une réponse qui arrive après 30 s ne sert plus à rien.
    var request = URLRequest(url: url, timeoutInterval: 30)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    request.setValue(apiKey, forHTTPHeaderField: "x-goog-api-key")
    request.httpBody = try JSONSerialization.data(withJSONObject: body)

    let (data, response) = try await URLSession.shared.data(for: request)
    let status = (response as? HTTPURLResponse)?.statusCode ?? 0
    guard (200..<300).contains(status) else {
      switch status {
      case 400, 401, 403: throw TutorClientError.server("Clé Gemini refusée. Vérifie-la dans les réglages.")
      case 404: throw TutorClientError.server("Modèle Gemini introuvable : \(model).")
      case 429: throw TutorClientError.server("Quota Gemini atteint, réessaie dans un moment.")
      default: throw TutorClientError.server("Gemini est indisponible (\(status)), réessaie.")
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
    if finish == "MAX_TOKENS" { throw TutorClientError.server("Réponse trop longue, réessaie.") }
    let json = (candidate.content?.parts ?? [])
      .filter { $0.thought != true }
      .compactMap(\.text)
      .joined()
    guard let jsonData = json.data(using: .utf8), let value = try? JSONDecoder().decode(T.self, from: jsonData) else {
      throw TutorClientError.server("Réponse illisible, réessaie.")
    }
    return value
  }

  // MARK: Mise en forme (identique au serveur)

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
          measure: object.measure?.sentence ?? Sentence(zh: "", pinyin: "", fr: ""),
          example: object.example?.sentence ?? Sentence(zh: "", pinyin: "", fr: ""),
          tip: (object.tip ?? "").trimmingCharacters(in: .whitespaces),
          status: status,
          pinyinCheck: nil
        ))
      if words.count >= limit { break }
    }
    return words
  }

  static func scanSpeech(words: [Word], teacher: Sentence, challenge: ChallengeResult?) -> [SpeechSegment] {
    var segments: [SpeechSegment] = []
    if let challenge { segments.append(SpeechSegment(lang: "fr-FR", text: challenge.feedback)) }
    for word in words {
      switch word.status {
      case "new":
        segments += [
          SpeechSegment(lang: "zh-CN", text: word.hanzi),
          SpeechSegment(lang: "fr-FR", text: word.fr),
          SpeechSegment(lang: "zh-CN", text: word.measure.zh),
          SpeechSegment(lang: "zh-CN", text: word.example.zh),
          SpeechSegment(lang: "fr-FR", text: word.example.fr),
        ]
      case "review":
        segments += [
          SpeechSegment(lang: "zh-CN", text: word.hanzi),
          SpeechSegment(lang: "fr-FR", text: "… \(word.fr)"),
        ]
      default:
        break
      }
    }
    segments.append(SpeechSegment(lang: "zh-CN", text: teacher.zh))
    return segments.filter { !$0.text.isEmpty }
  }

  static func askSpeech(intro: String, words: [Word], followup: String) -> [SpeechSegment] {
    var spokenIntro = intro
    if containsHanzi(spokenIntro) { spokenIntro = words.isEmpty ? "" : "Voici la réponse :" }
    var segments: [SpeechSegment] = spokenIntro.isEmpty ? [] : [SpeechSegment(lang: "fr-FR", text: spokenIntro)]
    for (index, word) in words.enumerated() {
      if index > 0 { segments.append(SpeechSegment(lang: "fr-FR", text: "Et aussi, pour « \(word.fr) » :")) }
      segments += [
        SpeechSegment(lang: "zh-CN", text: word.hanzi),
        SpeechSegment(lang: "zh-CN", text: word.hanzi),
        SpeechSegment(lang: "zh-CN", text: word.example.zh),
        SpeechSegment(lang: "fr-FR", text: word.example.fr),
      ]
    }
    if !followup.isEmpty, !containsHanzi(followup) { segments.append(SpeechSegment(lang: "fr-FR", text: followup)) }
    return segments.filter { !$0.text.isEmpty }
  }

  private static func learnerLines(level: String, known: [String], learning: [String]) -> [String] {
    let knownText = known.suffix(300).joined(separator: "、")
    let learningText = learning.suffix(300).joined(separator: "、")
    return [
      "Niveau : \(level)",
      "Mots déjà connus : \(knownText.isEmpty ? "(aucun)" : knownText)",
      "Mots en cours d'apprentissage : \(learningText.isEmpty ? "(aucun)" : learningText)",
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

  // MARK: Consignes (copie de server/app/tutor.py)

  static let teachingRules = """
    Tu es Lǎoshī (老师), un professeur de chinois mandarin bienveillant qui vit dans les lunettes connectées d'un élève francophone. Tu lui parles à l'oreille.

    Ce que tu enseignes doit être fiable : l'élève apprend sur cette base.
    - Chinois standard de Chine continentale (普通话), caractères simplifiés.
    - Pinyin avec accents de ton, syllabes séparées par une espace (« yǐ zi »), ton neutre sans accent. Pour le mot seul, pinyin du dictionnaire sans sandhi. Dans les phrases (classificateur, exemple), applique le sandhi de 一 et 不 (« yí ge », « yì bǎ », « bú shì »). Vérifie chaque syllabe et chaque ton.
    - Choisis le mot le plus courant (杯子 plutôt que 玻璃杯, sauf si la précision est utile). Pas de mots rares ou littéraires.
    - « tip » : une phrase en français pour retenir le mot. Décomposition du caractère (clé et sens) seulement si tu en es sûr (ex. 椅 contient la clé 木, le bois). N'invente jamais d'étymologie : si tu n'es pas sûr, donne plutôt une astuce d'usage.
    - « measure » : le classificateur le plus courant, sous la forme « 一 + classificateur + mot » (一把椅子), avec pinyin et traduction.
    - « example » : une phrase courte et naturelle. Elle réutilise surtout des mots que l'élève connaît déjà, plus le mot cible (un seul élément nouveau à la fois).
    - « hsk » : niveau HSK (1 à 6) du mot, 7 s'il est hors liste HSK.

    Niveau de l'élève :
    - debutant : phrases de 4 à 8 caractères, structures 这是…、…在…上、有…, vocabulaire HSK 1-2.
    - intermediaire : phrases jusqu'à 15 caractères, vocabulaire HSK 3-4.
    - avance : phrases naturelles et idiomatiques, vocabulaire libre.

    Confidentialité : ne décris pas et n'identifie pas les personnes, ne recopie pas le contenu des écrans ni des documents.
    """

  static let scanTask = """
    TÂCHE : MINI-LEÇON SUR CE QUE VOIT L'ÉLÈVE.
    Tu reçois une photo de ce qu'il regarde.
    - Ne nomme que des objets clairement visibles. Dans le doute, ignore l'objet.
    - « where » : position de l'objet sur la photo en quelques mots de français.
    - « example » parle de la scène photographiée.
    - « objects » (du plus visible au moins visible) : d'abord les mots « en cours d'apprentissage » visibles (les revoir en contexte les ancre), puis au plus le nombre demandé de mots nouveaux, éventuellement un ou deux mots connus. Maximum 6.
    - « teacher » : une seule phrase que tu dis à voix haute, en chinois, à son niveau, à propos de la scène. De préférence une petite question qui le fait réutiliser un mot (« 桌子上有什么？»).
    - « scene » : la scène en une courte phrase de français.
    - « challenge » : null s'il n'y a pas de défi. Sinon l'élève devait trouver l'objet cible : « found » dit s'il est visible sur la photo, « feedback » le félicite (une phrase en français, avec le mot chinois) ou l'aide à chercher.
    """

  static let askTask = """
    TÂCHE : RÉPONDRE À UNE QUESTION ORALE.
    L'élève te pose une question à voix haute (transcrite automatiquement, donc parfois mal orthographiée : « que veut dire siège en chinois », « comment on dit fourchette », « c'est quoi yizi », « c'est quoi ça en chinois »). Une photo de ce qu'il regarde peut être jointe : utilise-la si la question parle de « ça », ou pour choisir le bon sens d'un mot ambigu (le siège d'une voiture n'est pas un siège social).
    - « words » : le ou les mots chinois qui répondent (1 en général, 2 au maximum si le mot français a deux sens courants). Mêmes règles que plus haut ; « where » vide.
    - « intro » : la réponse parlée, en français, une phrase courte qui sera lue par une voix française juste AVANT le mot chinois. Elle ne contient NI caractères chinois NI pinyin. Ex. : « Siège, en chinois, se dit : ».
    - « followup » : une phrase en français dite après le mot, pour une nuance utile (« Le deuxième mot désigne plutôt une chaise. »). Ni caractères chinois ni pinyin non plus. Vide s'il n'y a rien d'utile à ajouter.
    - Si la question n'a rien à voir avec le chinois : « words » vide, « intro » rappelle gentiment que tu es son prof de chinois, « followup » vide.
    """

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
