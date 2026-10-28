import Foundation

struct SyncTrack: Hashable {
    var title: String
    var artist: String
    var album: String?
    var durationMs: Int?
    var isrc: String?
    var spotifyId: String?
    var appleId: String?

    /// Normalized title|artist used to compare tracks across services.
    var key: String { SyncTrack.norm(title) + "|" + SyncTrack.norm(artist) }

    static func norm(_ s: String) -> String {
        var t = s.folding(options: [.diacriticInsensitive, .caseInsensitive], locale: .current)
        t = t.replacingOccurrences(of: "\\([^)]*\\)|\\[[^\\]]*\\]", with: "", options: .regularExpression)
        t = t.replacingOccurrences(of: "[^a-z0-9]+", with: "", options: .regularExpression)
        return t
    }
}
