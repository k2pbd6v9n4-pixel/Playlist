# Playlist Sync

iOS app that syncs playlists between Apple Music and Spotify.

## Status
Skeleton only. Create the Xcode project (iOS App, SwiftUI) in this repo and add the files under `PlaylistSync/`.

## Design
1. Authenticate with Apple Music (MusicKit) and Spotify (PKCE).
2. Read a playlist from the source service into a neutral `Track` model (title, artist, album, duration, ISRC).
3. Match tracks on the target service by ISRC, then fall back to title + artist search.
4. Create or update the target playlist and report unmatched tracks.
5. Store a track-ID mapping so later syncs only apply differences.

## Notes
- Spotify Development Mode: Premium owner required, max 5 authorized users.
- Xcode Cloud setup: see `docs/XCODE_CLOUD_CHECKLIST.md`.
- Never commit `Secrets.xcconfig`; `ci_scripts/ci_post_clone.sh` generates it in CI.
