# Playlist Sync

iOS app that syncs playlists between Apple Music and Spotify.


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

## Building without a Mac (GitHub Actions)
`.github/workflows/testflight.yml` generates the Xcode project with XcodeGen (`project.yml`), archives, and uploads to TestFlight on every push to `main`.

Add these under GitHub repo -> Settings -> Secrets and variables -> Actions:

| Secret | What |
|---|---|
| `APPLE_TEAM_ID` | 10-character Team ID (developer.apple.com -> Membership) |
| `BUNDLE_ID` | e.g. `com.yourname.playlistsync`, registered in your account |
| `ASC_KEY_ID` | App Store Connect API key ID |
| `ASC_ISSUER_ID` | Issuer ID (App Store Connect -> Users and Access -> Integrations) |
| `ASC_KEY_P8` | Full contents of the downloaded `AuthKey_XXXX.p8` file |
| `SPOTIFY_CLIENT_ID` | From the Spotify developer dashboard |

Also: create the app record in App Store Connect, and enable **MusicKit** under the App ID's App Services (developer.apple.com -> Identifiers).

## Database
`db/schema.sql` (bundled as `PlaylistSync/Resources/schema.sql`) creates a local SQLite DB on first launch. It stores a snapshot of the last agreed state plus a full `change_log` of every add/remove per sync run.

