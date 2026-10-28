# Xcode Cloud -> TestFlight Checklist

## Accounts and records
- [ ] Paid Apple Developer Program membership
- [ ] App record created in App Store Connect (bundle ID matches the Xcode project)
- [ ] Your role is Admin or App Manager
- [ ] Internal tester group created in App Store Connect, testers added

## Xcode project
- [ ] Automatic signing enabled, correct Team selected
- [ ] MusicKit capability enabled (Signing & Capabilities) and on the App ID (App Services)
- [ ] Custom URL scheme registered for the Spotify redirect (e.g. `playlistsync://callback`)
- [ ] `Secrets.xcconfig` added to `.gitignore`
- [ ] `NSAppleMusicUsageDescription` set in Info.plist
- [ ] Scheme is shared (Product -> Scheme -> Manage Schemes -> Shared)

## Spotify dashboard
- [ ] App created, owner has Premium
- [ ] Redirect URI registered exactly as used in the app
- [ ] Testers added to the allowlist (max 5 in Development Mode)
- [ ] Scopes requested: `playlist-read-private`, `playlist-modify-private`, `playlist-modify-public`

## Xcode Cloud workflow
- [ ] Product -> Xcode Cloud -> Create Workflow, repo access granted
- [ ] Start condition: branch changes (e.g. `main`)
- [ ] Action: Archive (iOS), distribution preparation: App Store Connect
- [ ] Post-action: TestFlight (Internal Testing) with your tester group
- [ ] Environment variable: `SPOTIFY_CLIENT_ID`
- [ ] Optional environment variable (Secret): `BACKEND_API_KEY`
- [ ] `ci_scripts/ci_post_clone.sh` committed and executable

## Keys you do NOT need for this pipeline
- Distribution certificate or provisioning profile (cloud-managed signing)
- App Store Connect API key (only for external CI such as Fastlane)
- Spotify client secret (PKCE flow)
- MusicKit .p8 key (only if a backend calls the Apple Music REST API)

## First run
- [ ] Push to the trigger branch
- [ ] Watch the build in Xcode -> Report navigator -> Cloud
- [ ] Build appears in TestFlight after processing (usually 10-30 min)
- [ ] Accept the invite in the TestFlight app on a device
