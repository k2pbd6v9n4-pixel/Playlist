"""Test whichever credentials are set, without changing anything.

python -m playlist_sync check
"""
from __future__ import annotations

import requests

from . import config
from .apple import AppleAuthError, AppleMusic, developer_token
from .http import ApiError, call
from .spotify import Spotify, SpotifyAuthError, client_credentials_token

OK, FAIL, SKIP = "✅", "❌", "⏭️"


def run() -> tuple[list[tuple[str, str, str]], bool]:
    rows: list[tuple[str, str, str]] = []
    session = requests.Session()
    cfg = config.settings()

    # Spotify app (Client ID + Secret)
    cid, secret = config.env("SPOTIFY_CLIENT_ID"), config.env("SPOTIFY_CLIENT_SECRET")
    if cid and secret:
        try:
            client_credentials_token(cid, secret, session)
            rows.append((OK, "Spotify app", "Client ID and Client Secret work."))
        except ApiError as e:
            if e.status == 0:
                rows.append((FAIL, "Spotify app", f"Couldn't reach Spotify ({e.message}). Run the check again."))
            else:
                rows.append((FAIL, "Spotify app", f"Spotify said {e.status}: {e.message}. Re-copy both values "
                                                  "from the app's Settings page in the Spotify developer dashboard."))
    else:
        rows.append((SKIP, "Spotify app", "Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET secrets."))

    # Spotify sign-in (refresh token) + the playlist
    refresh = config.env("SPOTIFY_REFRESH_TOKEN")
    if cid and secret and refresh:
        try:
            sp = Spotify(cid, secret, refresh, session)
            sp.authenticate()
            me = sp.me()
            who = me.get("display_name") or me.get("id")
            pl = sp.find_playlist(cfg.spotify_playlist_name, cfg.spotify_playlist_id)
            if pl is None:
                rows.append((FAIL, "Spotify playlist", f'Signed in as {who}, but there\'s no playlist named '
                                                       f'"{cfg.spotify_playlist_name}" in your library.'))
            else:
                if not pl.editable:
                    rows.append((FAIL, "Spotify playlist", f'Signed in as {who}. Found "{pl.name}", but it '
                                                           "isn't yours, and Spotify only lets apps read "
                                                           "playlists you own or collaborate on."))
                else:
                    n = len(sp.playlist_tracks(pl.id))
                    rows.append((OK, "Spotify playlist", f'Signed in as {who}. Found "{pl.name}" with {n} songs.'))
        except SpotifyAuthError as e:
            rows.append((FAIL, "Spotify sign-in", str(e)))
        except (ApiError, RuntimeError) as e:
            hint = (" If it's a 403, add your Spotify account's email under User Management in the app's "
                    "settings, and check the app owner has Premium.") if getattr(e, "status", 0) == 403 else ""
            rows.append((FAIL, "Spotify playlist", f"{e}{hint}"))
    else:
        rows.append((SKIP, "Spotify sign-in", "Run 'Connect Spotify and Apple Music' to get SPOTIFY_REFRESH_TOKEN."))

    # Apple developer token
    team, kid, key = (config.env("APPLE_TEAM_ID"), config.env("APPLE_MUSIC_KEY_ID"),
                      config.env("APPLE_MUSIC_PRIVATE_KEY"))
    dev = None
    if team and kid and key:
        try:
            dev = developer_token(team, kid, key, ttl_seconds=600)
            call(session, "Apple Music", "GET", "https://api.music.apple.com/v1/catalog/us/search",
                 params={"term": "test", "types": "songs", "limit": 1},
                 headers={"Authorization": f"Bearer {dev}"})
            rows.append((OK, "Apple MusicKit key", "Team ID, Key ID and private key work."))
        except ApiError as e:
            dev = None
            rows.append((FAIL, "Apple MusicKit key", f"Apple said {e.status}: {e.message}. Check the three "
                                                      "APPLE_ secrets and that the key has Media Services enabled."))
        except Exception as e:  # bad key format
            dev = None
            rows.append((FAIL, "Apple MusicKit key", f"Couldn't sign with the private key ({e.__class__.__name__}). "
                                                      "Paste the whole .p8 file, including the BEGIN and END lines."))
    else:
        rows.append((SKIP, "Apple MusicKit key", "Add APPLE_TEAM_ID, APPLE_MUSIC_KEY_ID and APPLE_MUSIC_PRIVATE_KEY."))

    # Apple user token + the playlist
    user = config.env("APPLE_MUSIC_USER_TOKEN")
    if dev and user:
        try:
            am = AppleMusic(dev, user, session)
            sf = am.storefront()
            pl = am.find_playlist(cfg.apple_playlist_name, cfg.apple_playlist_id)
            if pl is None:
                rows.append((OK, "Apple Music library", f'Signed in (store: {sf.upper()}). No playlist named '
                                                        f'"{cfg.apple_playlist_name}" yet; the first sync creates it.'))
            else:
                n = len(am.playlist_tracks(pl.id))
                note = "" if pl.editable else " It can't be edited, so the sync can't add to it."
                rows.append((OK if pl.editable else FAIL, "Apple Music library",
                             f'Signed in (store: {sf.upper()}). Found "{pl.name}" with {n} songs.{note}'))
        except (AppleAuthError, ApiError, RuntimeError) as e:
            rows.append((FAIL, "Apple Music library", str(e)))
    elif not user:
        rows.append((SKIP, "Apple Music library", "Run 'Connect Spotify and Apple Music' to get APPLE_MUSIC_USER_TOKEN."))

    ok = not any(r[0] == FAIL for r in rows)
    return rows, ok


def render(rows: list[tuple[str, str, str]], ok: bool) -> str:
    if not ok:
        head = "## Connection check: something needs fixing"
    elif all(r[0] == SKIP for r in rows):
        head = "## Connection check: no credentials set yet"
    elif any(r[0] == SKIP for r in rows):
        head = "## Connection check: everything set so far works"
    else:
        head = "## Connection check: all connected"
    lines = [head, "", "| | Check | Result |", "|---|---|---|"]
    lines += [f"| {icon} | {name} | {msg.replace('|', '/')} |" for icon, name, msg in rows]
    return "\n".join(lines) + "\n"
