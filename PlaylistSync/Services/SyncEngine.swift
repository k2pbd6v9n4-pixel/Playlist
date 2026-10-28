import Foundation
import MusicKit

struct SyncSummary {
    var added = 0, removed = 0, unmatched = 0, unsupported = 0
    var text: String {
        "Added \(added), removed \(removed), unmatched \(unmatched), removals Apple can't do \(unsupported)"
    }
}

/// Three-way sync: last snapshot vs current Spotify Liked Songs vs current Apple "Spotify Sync" playlist.
final class SyncEngine {
    let spotify = SpotifyService()
    let apple = AppleMusicService()
    let db: Database

    init(db: Database) { self.db = db }

    func run(progress: @escaping (String) -> Void) async throws -> SyncSummary {
        let runId = try db.startRun()
        var sum = SyncSummary()
        do {
            progress("Signing in…")
            try await apple.authenticate()
            try await spotify.authenticate()
            try await apple.ensurePlaylist()

            progress("Reading both libraries…")
            let s = Dictionary(try await spotify.fetchLiked().map { ($0.key, $0) }, uniquingKeysWith: { a, _ in a })
            let a = Dictionary(try await apple.fetchTracks().map { ($0.key, $0) }, uniquingKeysWith: { a, _ in a })
            let snap = try db.snapshotKeys()
            let sK = Set(s.keys), aK = Set(a.keys)

            let addToApple = sK.subtracting(aK).subtracting(snap)       // new on Spotify
            let addToSpotify = aK.subtracting(sK).subtracting(snap)     // new on Apple
            let removeFromSpotify = sK.subtracting(aK).intersection(snap)   // deleted on Apple
            let removeFromApple = aK.subtracting(sK).intersection(snap)     // deleted on Spotify

            var keep = sK.intersection(aK)

            // Spotify -> Apple adds
            progress("Adding \(addToApple.count) to Apple Music…")
            var songs: [Song] = []
            for k in addToApple {
                let t = s[k]!, id = try db.upsertTrack(t)
                if let song = try await apple.findSong(for: t) {
                    songs.append(song); keep.insert(k)
                    try db.log(run: runId, trackId: id, action: "add", origin: "spotify", target: "apple", status: "applied")
                    sum.added += 1
                } else {
                    try db.log(run: runId, trackId: id, action: "add", origin: "spotify", target: "apple", status: "failed", detail: "no match")
                    sum.unmatched += 1
                }
            }
            try await apple.add(songs: songs)

            // Apple -> Spotify adds
            progress("Adding \(addToSpotify.count) to Spotify…")
            var addIds: [String] = []
            for k in addToSpotify {
                let t = a[k]!, id = try db.upsertTrack(t)
                if let sid = try await spotify.findId(for: t) {
                    addIds.append(sid); keep.insert(k)
                    try db.log(run: runId, trackId: id, action: "add", origin: "apple", target: "spotify", status: "applied")
                    sum.added += 1
                } else {
                    try db.log(run: runId, trackId: id, action: "add", origin: "apple", target: "spotify", status: "failed", detail: "no match")
                    sum.unmatched += 1
                }
            }
            try await spotify.add(ids: addIds)

            // Removals
            let rmIds = removeFromSpotify.compactMap { s[$0]?.spotifyId }
            try await spotify.remove(ids: rmIds)
            for k in removeFromSpotify {
                try db.log(run: runId, trackId: try db.upsertTrack(s[k]!), action: "remove", origin: "apple", target: "spotify", status: "applied")
                sum.removed += 1
            }
            for k in removeFromApple {   // keep in snapshot so it stays flagged and is not re-added
                try db.log(run: runId, trackId: try db.upsertTrack(a[k]!), action: "remove", origin: "spotify", target: "apple",
                           status: "unsupported", detail: "MusicKit cannot remove playlist tracks")
                keep.insert(k); sum.unsupported += 1
            }

            for k in keep { if let t = s[k] ?? a[k] { _ = try db.upsertTrack(t) } }
            try db.replaceSnapshot(keys: keep, run: runId)
            try db.finish(run: runId, status: sum.unmatched + sum.unsupported > 0 ? "partial" : "success",
                          added: sum.added, removed: sum.removed, unmatched: sum.unmatched)
            return sum
        } catch {
            try? db.finish(run: runId, status: "failed", added: sum.added, removed: sum.removed,
                           unmatched: sum.unmatched, error: error.localizedDescription)
            throw error
        }
    }
}
