import Foundation
import MusicKit

/// Apple Music playlist "Spotify Sync" via MusicKit.
/// NOTE: MusicKit has no API to remove tracks from a library playlist, so removals are reported as unsupported.
final class AppleMusicService {
    static let playlistName = "Spotify Sync"

    func authenticate() async throws {
        guard await MusicAuthorization.request() == .authorized else { throw SyncError.auth("Apple Music access denied") }
    }

    private func findPlaylist() async throws -> Playlist? {
        var req = MusicLibraryRequest<Playlist>()
        req.filter(matching: \.name, equalTo: Self.playlistName)
        return try await req.response().items.first
    }

    func fetchTracks() async throws -> [SyncTrack] {
        guard let p = try await findPlaylist() else { return [] }
        let full = try await p.with([.tracks])
        return (full.tracks ?? []).map {
            SyncTrack(title: $0.title, artist: $0.artistName, album: $0.albumTitle,
                      durationMs: $0.duration.map { Int($0 * 1000) }, appleId: $0.id.rawValue)
        }
    }

    /// Finds a catalog song by ISRC, falling back to a title + artist search.
    func findSong(for t: SyncTrack) async throws -> Song? {
        if let isrc = t.isrc {
            let r = MusicCatalogResourceRequest<Song>(matching: \.isrc, equalTo: isrc)
            if let s = try await r.response().items.first { return s }
        }
        var r = MusicCatalogSearchRequest(term: "\(t.title) \(t.artist)", types: [Song.self])
        r.limit = 5
        return try await r.response().songs.first { SyncTrack.norm($0.title) == SyncTrack.norm(t.title) }
    }

    func add(songs: [Song]) async throws {
        guard !songs.isEmpty else { return }
        if let p = try await findPlaylist() {
            for s in songs { try await MusicLibrary.shared.add(s, to: p) }
        } else {
            _ = try await MusicLibrary.shared.createPlaylist(name: Self.playlistName, items: songs)
        }
    }

    func ensurePlaylist() async throws {
        if try await findPlaylist() == nil {
            _ = try await MusicLibrary.shared.createPlaylist(name: Self.playlistName)
        }
    }
}
