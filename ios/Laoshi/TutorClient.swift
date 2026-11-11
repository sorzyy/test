import Foundation

// MARK: - Format de l'API (voir server/app/schemas.py)

struct Sentence: Codable, Hashable {
  let zh: String
  let pinyin: String
  let fr: String
}

struct PinyinCheck: Codable, Hashable {
  let ok: Bool
  let dictionary: String
  let reason: String
}

struct Word: Codable, Hashable, Identifiable {
  var id: String { hanzi }
  let hanzi: String
  let pinyin: String
  let fr: String
  let `where`: String
  let hsk: Int
  let measure: Sentence
  let example: Sentence
  let tip: String
  let status: String  // new | review | known
  /// Vérification du pinyin par dictionnaire (seulement via le serveur).
  let pinyinCheck: PinyinCheck?
}

struct ChallengeResult: Codable, Hashable {
  let target: String
  let found: Bool
  let feedback: String
}

struct SpeechSegment: Codable, Hashable {
  let lang: String  // zh-CN | fr-FR
  let text: String
}

struct ScanResult: Codable {
  let scene: String
  let words: [Word]
  let teacher: Sentence
  let challenge: ChallengeResult?
  let speech: [SpeechSegment]
  let demo: Bool
}

struct AskResult: Codable {
  let question: String
  let intro: String
  let words: [Word]
  let followup: String
  let speech: [SpeechSegment]
  let demo: Bool
}

private struct AskRequest: Encodable {
  let question: String
  let image: String?
  let level: String
  let known: [String]
  let learning: [String]
}

private struct ScanRequest: Encodable {
  let image: String
  let level: String
  let known: [String]
  let learning: [String]
  let challenge: String?
  let maxNew: Int
}

private struct APIError: Decodable { let detail: String }

// MARK: - Client

enum TutorClientError: LocalizedError {
  case badServerURL
  case server(String)

  var errorDescription: String? {
    switch self {
    case .badServerURL: return "Adresse du serveur invalide (Réglages)."
    case .server(let message): return message
    }
  }
}

struct TutorClient {
  var serverURL: String
  var token: String

  func scan(
    jpeg: Data,
    level: String,
    maxNew: Int,
    known: [String],
    learning: [String],
    challenge: String? = nil
  ) async throws -> ScanResult {
    try await post(
      "/api/scan",
      ScanRequest(
        image: jpeg.base64EncodedString(),
        level: level,
        known: Array(known.suffix(300)),
        learning: Array(learning.suffix(300)),
        challenge: challenge,
        maxNew: maxNew
      ))
  }

  /// Question orale (« que veut dire siège en chinois ? »), avec ce que voient les lunettes.
  func ask(question: String, jpeg: Data?, level: String, known: [String], learning: [String]) async throws -> AskResult {
    try await post(
      "/api/ask",
      AskRequest(
        question: question,
        image: jpeg?.base64EncodedString(),
        level: level,
        known: Array(known.suffix(300)),
        learning: Array(learning.suffix(300))
      ))
  }

  private func post<Body: Encodable, Response: Decodable>(_ path: String, _ body: Body) async throws -> Response {
    let base = serverURL.trimmingCharacters(in: CharacterSet(charactersIn: "/ "))
    guard let url = URL(string: base + path), url.scheme?.hasPrefix("http") == true else {
      throw TutorClientError.badServerURL
    }
    var request = URLRequest(url: url, timeoutInterval: 60)
    request.httpMethod = "POST"
    request.setValue("application/json", forHTTPHeaderField: "Content-Type")
    if !token.isEmpty { request.setValue(token, forHTTPHeaderField: "X-Laoshi-Token") }

    let encoder = JSONEncoder()
    encoder.keyEncodingStrategy = .convertToSnakeCase
    request.httpBody = try encoder.encode(body)

    let (data, response) = try await URLSession.shared.data(for: request)
    let decoder = JSONDecoder()
    decoder.keyDecodingStrategy = .convertFromSnakeCase
    if let http = response as? HTTPURLResponse, !(200..<300).contains(http.statusCode) {
      let message = (try? decoder.decode(APIError.self, from: data))?.detail ?? "Erreur serveur \(http.statusCode)"
      throw TutorClientError.server(message)
    }
    return try decoder.decode(Response.self, from: data)
  }
}
