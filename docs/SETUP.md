# Setup from your phone

You need about 20 minutes. Everything happens in Safari and the GitHub app.
Never paste a key into a chat, an issue or a file in this repo. Keys go only into
**repository secrets**, which GitHub hides from everyone, including the run logs.

## 0. Merge the pull request first

GitHub only shows the "Run workflow" button for workflows that are on the `main` branch.

## How to add a repository secret

1. In Safari, open github.com, go to the **Playlist** repo and tap **Settings**
   (if you don't see it, tap **aA** → **Request Desktop Website**).
2. Tap **Secrets and variables** → **Actions** → **New repository secret**.
3. Type the **Name** exactly as written below, paste the value into **Secret**, tap **Add secret**.

To change one later, tap the pencil next to it and paste the new value.

## How to run a workflow from the GitHub app

1. Open the **Playlist** repo → **Actions**.
2. Tap the workflow (for example **Check connections**).
3. Tap **Run workflow** (it may sit under the **⋯** menu), then **Run**.
4. Tap the new run, then the job, to read its log. The result is printed at the end of the log
   and on the run's summary page.

## 1. Spotify app: `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET`

These identify your Spotify developer app. You already have an app; reuse it.

1. In Safari, open developer.spotify.com/dashboard, sign in and tap your app → **Settings**.
2. Copy **Client ID** → save it as `SPOTIFY_CLIENT_ID`.
3. Tap **View client secret**, copy it → save it as `SPOTIFY_CLIENT_SECRET`.
4. Tap **Edit**. Under **Redirect URIs** add exactly `http://127.0.0.1:8888/callback`, tap **Add**,
   then **Save** at the bottom. (Spotify doesn't accept `localhost` here, so it has to be `127.0.0.1`.)
5. Make sure **Web API** is ticked under the APIs used.

Spotify requires the account that owns the app to have **Premium**. If you later see a 403
error, open **User Management** in the app's settings and add your own name and Spotify email.

**Test it now:** run **Check connections**. The first row should say
"✅ Spotify app: Client ID and Client Secret work." The other rows say ⏭️ until you add the rest.

> If your Client ID and secret were ever saved in a file in this repo, delete that file and
> tap **Rotate client secret** on the Spotify app page, then save the new secret. A file removed
> from a repo stays in its history, so the old secret should stop working.

## 2. Apple MusicKit key: `APPLE_TEAM_ID`, `APPLE_MUSIC_KEY_ID`, `APPLE_MUSIC_PRIVATE_KEY`

These let the sync talk to the Apple Music API. They need an **Apple Developer Program**
membership (paid, yearly). Your role on the team must be Account Holder or Admin.

1. In Safari, open developer.apple.com/account and sign in.
2. **Team ID:** open **Membership details** and copy the 10-character **Team ID** → save it as
   `APPLE_TEAM_ID`.
3. **Media ID:** go to **Certificates, Identifiers & Profiles** → **Identifiers** → **+** →
   **Media IDs** → **Continue**. Enter a description (Playlist Sync) and an identifier in
   reverse-domain style (for example `com.yourname.playlistsync`), tick **MusicKit**, then
   **Continue** → **Register**.
4. **Key:** go to **Keys** → **+**. Name it Playlist Sync, tick **Media Services (MusicKit,
   ShazamKit, Apple Music Feed)**, tap **Configure**, choose the Media ID from step 3, **Save** →
   **Continue** → **Register**.
5. Copy the **Key ID** shown on that page → save it as `APPLE_MUSIC_KEY_ID`.
6. Tap **Download**. Apple lets you download it **only once**, so keep the file somewhere safe
   (iCloud Drive or your password manager). It lands in **Files → Downloads** as
   `AuthKey_XXXXXXXXXX.p8`.
7. To copy its text on an iPhone: in Files, press and hold the file → **Rename**, change `.p8` to
   `.txt`, open it, press and hold the text → **Select All** → **Copy**. Save it as
   `APPLE_MUSIC_PRIVATE_KEY`, including the `-----BEGIN PRIVATE KEY-----` and
   `-----END PRIVATE KEY-----` lines.

**Test it:** run **Check connections**. "Apple MusicKit key" should show ✅.

## 3. Sign in to both services: `SPOTIFY_REFRESH_TOKEN` and `APPLE_MUSIC_USER_TOKEN`

The Client ID and secret only identify the app. To read your private Spotify playlist and add
songs to your Apple Music library, the sync also needs your permission, given once by signing in.

1. Run **Connect Spotify and Apple Music** in the GitHub app.
2. Open the run → the **connect** job → the **Open the sign-in page** step. After about 15 seconds
   it prints a link ending in `trycloudflare.com/?k=…`. Open it in Safari. (Give it a few seconds
   if it doesn't load at first.) The page stays up for 20 minutes.
3. **Spotify:** tap **Sign in to Spotify**, sign in and tap **Agree**. Safari then says it can't
   connect to the server. That's expected. Tap the address bar, select the whole address (it starts
   with `http://127.0.0.1:8888/callback?code=`), copy it, go back to the first tab, paste it in the
   box and tap **Get my Spotify token**. Tap **Copy** and save it as `SPOTIFY_REFRESH_TOKEN`.
4. **Apple Music:** tap **Sign in to Apple Music**, sign in with the Apple Account that has your Apple
   Music subscription and allow access. If nothing opens, allow pop-ups for the page and tap again.
   Tap **Copy** and save it as `APPLE_MUSIC_USER_TOKEN`.
5. Tap **I'm done, close this page**.

The page checks that each sign-in can see your "Music I like" playlist before showing the token.
Both sign-ins last about six months. When a run says one has expired, repeat this step and replace
that secret.

## 4. First sync

1. Run **Check connections**. Every row should be ✅.
2. Run **Sync Music I like to Apple Music** with **Preview only** ticked. The log lists what would be
   added and which songs aren't on Apple Music. Nothing changes.
3. Run it again without the tick. From then on it runs by itself every Sunday morning.

When a song isn't on Apple Music, the run opens an issue called **Songs not found on Apple Music**
(or adds a comment to it). GitHub notifies you about new issues in your own repo; check the GitHub app's notification settings if you don't see them. Close the issue
whenever you like; the next missing song opens a new one.

## Optional settings (repository variables, not secrets)

Same page as secrets, **Variables** tab → **New repository variable**.

| Variable | Use |
|---|---|
| `SPOTIFY_PLAYLIST_NAME` / `APPLE_PLAYLIST_NAME` | If either playlist is renamed. Default "Music I like". |
| `SPOTIFY_PLAYLIST_ID` / `APPLE_PLAYLIST_ID` | If two playlists share the name. |
| `NOTIFY_MENTION` | GitHub username to @mention in the issue. Default: the repo owner. |
