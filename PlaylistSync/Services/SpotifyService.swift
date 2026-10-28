import Foundation
import AuthenticationServices
import CryptoKit

enum SyncError: Error, LocalizedError {
    case auth(String), http(Int, String)
    var errorDescription: String? {
        switch self { case .auth(let m): return m; case .http(let c, let b): return "HTTP \(c): \(b)" }
    }
}

/// Spotify Liked Songs via the Web API (PKCE, no client secret).
final class SpotifyService: NSObject, ASWebAuthenticationPresentationContextProviding {
    private let clientId = Bundle.main.object(forInfoDictionaryKey: "SpotifyClientID") as? String ?? ""
    private let redirect = "playlistsync://callback"
    private var token: String?

    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor { ASPresentationAnchor() }

    func authenticate() async throws {
        guard !clientId.isEmpty else { throw SyncError.auth("Missing SPOTIFY_CLIENT_ID") }
        let verifier = Data((0..<64).map { _ in UInt8.random(in: 0...255) }).base64URL
        let challenge = Data(SHA256.hash(data: Data(verifier.utf8))).base64URL
        var c = URLComponents(string: "https://accounts.spotify.com/authorize")!
        c.queryItems = [
            .init(name: "client_id", value: clientId), .init(name: "response_type", value: "code"),
            .init(name: "redirect_uri", value: redirect), .init(name: "code_challenge_method", value: "S256"),
            .init(name: "code_challenge", value: challenge),
            .init(name: "scope", value: "user-library-read user-library-modify"),
        ]
        let callback: URL = try await withCheckedThrowingContinuation { cont in
            let s = ASWebAuthenticationSession(url: c.url!, callbackURLScheme: "playlistsync") { url, err in
                if let url { cont.resume(returning: url) } else { cont.resume(throwing: err ?? SyncError.auth("Cancelled")) }
            }
            s.presentationContextProvider = self
            s.start()
        }
        guard let code = URLComponents(url: callback, resolvingAgainstBaseURL: false)?
            .queryItems?.first(where: { $0.name == "code" })?.value else { throw SyncError.auth("No code") }
        var req = URLRequest(url: URL(string: "https://accounts.spotify.com/api/token")!)
        req.httpMethod = "POST"
        req.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")
        req.httpBody = "grant_type=authorization_code&code=\(code)&redirect_uri=\(redirect)&client_id=\(clientId)&code_verifier=\(verifier)"
            .data(using: .utf8)
        let (data, _) = try await URLSession.shared.data(for: req)
        token = (try JSONSerialization.jsonObject(with: data) as? [String: Any])?["access_token"] as? String
        if token == nil { throw SyncError.auth("Token exchange failed") }
    }

    func fetchLiked() async throws -> [SyncTrack] {
        var out: [SyncTrack] = []
        var next: String? = "https://api.spotify.com/v1/me/tracks?limit=50"
        while let url = next {
            let json = try await call("GET", url)
            for item in json["items"] as? [[String: Any]] ?? [] {
                guard let t = item["track"] as? [String: Any], let id = t["id"] as? String,
                      let name = t["name"] as? String else { continue }
                let artist = (t["artists"] as? [[String: Any]])?.first?["name"] as? String ?? ""
                out.append(SyncTrack(title: name, artist: artist,
                                     album: (t["album"] as? [String: Any])?["name"] as? String,
                                     durationMs: t["duration_ms"] as? Int,
                                     isrc: (t["external_ids"] as? [String: Any])?["isrc"] as? String,
                                     spotifyId: id))
            }
            next = json["next"] as? String
        }
        return out
    }

    func add(ids: [String]) async throws { try await mutate("PUT", ids) }
    func remove(ids: [String]) async throws { try await mutate("DELETE", ids) }

    func findId(for t: SyncTrack) async throws -> String? {
        var q = "track:\(t.title) artist:\(t.artist)"
        if let i = t.isrc { q = "isrc:\(i)" }
        var c = URLComponents(string: "https://api.spotify.com/v1/search")!
        c.queryItems = [.init(name: "q", value: q), .init(name: "type", value: "track"), .init(name: "limit", value: "5")]
        let json = try await call("GET", c.url!.absoluteString)
        let items = (json["tracks"] as? [String: Any])?["items"] as? [[String: Any]] ?? []
        return items.first?["id"] as? String
    }

    private func mutate(_ method: String, _ ids: [String]) async throws {
        for chunk in stride(from: 0, to: ids.count, by: 50).map({ Array(ids[$0..<min($0 + 50, ids.count)]) }) {
            _ = try await call(method, "https://api.spotify.com/v1/me/tracks",
                               body: try JSONSerialization.data(withJSONObject: ["ids": chunk]))
        }
    }

    private func call(_ method: String, _ url: String, body: Data? = nil) async throws -> [String: Any] {
        var req = URLRequest(url: URL(string: url)!)
        req.httpMethod = method
        req.setValue("Bearer \(token ?? "")", forHTTPHeaderField: "Authorization")
        if let body { req.httpBody = body; req.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        let (data, resp) = try await URLSession.shared.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(code) else { throw SyncError.http(code, String(data: data, encoding: .utf8) ?? "") }
        return (try? JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
    }
}

private extension Data {
    var base64URL: String {
        base64EncodedString().replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_").replacingOccurrences(of: "=", with: "")
    }
}
