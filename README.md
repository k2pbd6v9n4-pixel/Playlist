# Playlist Sync

A background job that copies the songs on the Spotify playlist **Music I like** into the
Apple Music playlist **Music I like**. It runs on GitHub Actions every Sunday morning and
whenever you start it from the GitHub app. There's no app to install.

- **One way, additions only.** Songs on the Spotify playlist are added to Apple Music.
  Nothing is ever removed from either playlist.
- **Missing songs.** When a song isn't on Apple Music, the run opens an issue called
  "Songs not found on Apple Music" in this repo (or comments on the open one), so GitHub
  notifies you. Each song is reported once. The run summary lists them too.
- **Log.** Every run, every song added and every song not found is recorded in
  `data/playlist_sync.db` (SQLite), which the workflow commits back after each run.

Set it up from your phone with [docs/SETUP.md](docs/SETUP.md).

## Workflows

| Workflow | When | What it does |
|---|---|---|
| Sync Music I like to Apple Music | Sundays 15:00 UTC (8 AM Denver in winter, 9 AM in summer), and on demand | The sync. Tick "Preview only" to see what would be added without changing anything. |
| Check connections | On demand | Tests whichever credentials are set, changes nothing. |
| Connect Spotify and Apple Music | On demand | Opens a temporary sign-in page for your phone that gives you the two user tokens. |
| Tests | Pull requests | Runs the unit tests. |

## How a run works

1. Signs in to Spotify with the refresh token and reads every song on the playlist.
2. Signs an Apple Music developer token from the MusicKit key, then reads the Apple Music
   playlist (and creates it the first time if it doesn't exist).
3. For each Spotify song that isn't in the Apple Music playlist yet, it finds the song in
   the Apple Music catalog by ISRC (the recording's industry code), then by title and main
   artist within 20 seconds of the same length, and adds it.
4. Songs it can't find are logged and reported in the issue.

Songs the sync added that you later delete in Apple Music are **not** added again.
Songs added in the last 7 days that Apple Music hasn't listed yet aren't added twice.

## API limits that shape this

- **Apple Music can't remove songs.** The Apple Music API only adds to library playlists;
  there's no endpoint to remove songs, rename or delete a playlist. That's why it's
  additions-only and why a wrong match has to be removed by hand in the Music app.
- **Spotify only reads playlists you own or collaborate on** (Spotify's February 2026 change for
  apps in development mode). The app owner's account needs Spotify Premium.
- **Catalog gaps.** Some songs aren't in the Apple Music catalog or not in your country's store.
  Those land in the issue.
- **Sign-ins expire.** Both user tokens last about six months. When a run says one expired,
  run "Connect Spotify and Apple Music" again and replace the secret.

## Credentials

All credentials are GitHub repository secrets (Settings → Secrets and variables → Actions).
None are stored in the repo. See [docs/SETUP.md](docs/SETUP.md) for how to get each one.

| Secret | What it is |
|---|---|
| `SPOTIFY_CLIENT_ID` | Your Spotify app's Client ID |
| `SPOTIFY_CLIENT_SECRET` | Your Spotify app's Client secret |
| `SPOTIFY_REFRESH_TOKEN` | Lets the sync read your private playlist (from the Connect workflow) |
| `APPLE_TEAM_ID` | Your Apple Developer Team ID |
| `APPLE_MUSIC_KEY_ID` | Key ID of your MusicKit key |
| `APPLE_MUSIC_PRIVATE_KEY` | The text of that key's `.p8` file |
| `APPLE_MUSIC_USER_TOKEN` | Lets the sync add to your Apple Music library (from the Connect workflow) |

Optional repository variables: `SPOTIFY_PLAYLIST_NAME`, `APPLE_PLAYLIST_NAME` (both default to
"Music I like"), `SPOTIFY_PLAYLIST_ID`, `APPLE_PLAYLIST_ID` (if two playlists share the name),
and `NOTIFY_MENTION` (GitHub username to @mention in the issue; defaults to the repo owner).

## Code

```
playlist_sync/
  __main__.py  python -m playlist_sync run | check | connect
  engine.py    the one-way sync
  spotify.py   Spotify Web API (read only)
  apple.py     Apple Music API (developer token, catalog lookup, add to playlist)
  models.py    track model and matching
  db.py        SQLite log (schema in db/schema.sql)
  notify.py    GitHub issue for songs not on Apple Music
  check.py     connection check
  connect.py   phone sign-in page for the two user tokens
  report.py    run summary
tests/         python -m unittest discover -s tests -t .
```

Local runs read the same names from environment variables. Keep any key files out of the repo;
`.gitignore` already ignores `*.p8`, `.env` and `*keys*.txt`.
