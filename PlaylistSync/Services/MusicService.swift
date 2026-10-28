import Foundation

protocol MusicService {
    func authenticate() async throws
    func fetchPlaylists() async throws -> [PlaylistModel]
    /// Returns tracks that could not be matched.
    func createPlaylist(_ playlist: PlaylistModel) async throws -> [Track]
}
