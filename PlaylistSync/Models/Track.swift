import Foundation

struct Track: Hashable, Codable {
    var title: String
    var artist: String
    var album: String?
    var durationMs: Int?
    var isrc: String?
}

struct PlaylistModel: Codable {
    var name: String
    var tracks: [Track]
}
