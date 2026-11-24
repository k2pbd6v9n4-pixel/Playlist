"""Spotify Web API client: reads one playlist (read-only).

Docs: https://developer.spotify.com/documentation/web-api
- Playlist items live at /playlists/{id}/items (the old /tracks paths are deprecated since the
  February 2026 changes), and only for playlists you own or collaborate on.
- Each playlist entry carries the track under "item" (the old "track" field is deprecated).
"""
from __future__ import annotations

import base64
from urllib.parse import quote, urlencode

import requests

from .http import ApiError, call
from .models import SPOTIFY, PlaylistRef, Track

API = "https://api.spotify.com/v1"
ACCOUNTS = "https://accounts.spotify.com"

# Read your playlists, public or private. The sync never changes anything on Spotify.
SCOPES = "playlist-read-private playlist-read-collaborative"
REDIRECT_URI = "http://127.0.0.1:8888/callback"


class SpotifyAuthError(Exception):
    pass


def _basic(client_id: str, client_secret: str) -> str:
    return "Basic " + base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()


def client_credentials_token(client_id: str, client_secret: str, session: requests.Session | None = None) -> dict:
    """App-only token. Proves the Client ID and Secret work; can't read private playlists."""
    s = session or requests.Session()
    return call(
        s, "Spotify", "POST", f"{ACCOUNTS}/api/token",
        data={"grant_type": "client_credentials"},
        headers={"Authorization": _basic(client_id, client_secret)},
    )


def exchange_code(client_id: str, client_secret: str, code: str, session: requests.Session | None = None,
                  redirect_uri: str = REDIRECT_URI) -> dict:
    """Swap the one-time code from the sign-in redirect for an access + refresh token."""
    s = session or requests.Session()
    return call(
        s, "Spotify", "POST", f"{ACCOUNTS}/api/token",
        data={"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri},
        headers={"Authorization": _basic(client_id, client_secret)},
    )


def authorize_url(client_id: str, state: str, redirect_uri: str = REDIRECT_URI) -> str:
    q = urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SCOPES,
        "state": state,
        "show_dialog": "true",
    }, quote_via=quote)
    return f"{ACCOUNTS}/authorize?{q}"


def _track_from_item(t: dict) -> Track | None:
    if not t or t.get("type", "track") != "track" or not t.get("uri"):
        return None
    artists = ", ".join(a.get("name", "") for a in t.get("artists") or [] if a.get("name"))
    return Track(
        service=SPOTIFY,
        service_id=t["uri"],
        title=t.get("name") or "",
        artist=artists,
        album=(t.get("album") or {}).get("name"),
        duration_ms=t.get("duration_ms"),
        isrc=((t.get("external_ids") or {}).get("isrc") or None),
        is_local=bool(t.get("is_local")) or t["uri"].startswith("spotify:local:"),
    )


class Spotify:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str,
                 session: requests.Session | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.session = session or requests.Session()
        self.access_token: str | None = None
        self.rotated_refresh_token: str | None = None
        self._me: dict | None = None

    # -- auth -------------------------------------------------------------
    def authenticate(self) -> None:
        try:
            body = call(
                self.session, "Spotify", "POST", f"{ACCOUNTS}/api/token",
                data={"grant_type": "refresh_token", "refresh_token": self.refresh_token},
                headers={"Authorization": _basic(self.client_id, self.client_secret)},
            )
        except ApiError as e:
            if e.status in (400, 401):
                raise SpotifyAuthError(
                    "Spotify refused the saved sign-in (" + e.message + "). Check SPOTIFY_CLIENT_ID and "
                    "SPOTIFY_CLIENT_SECRET, then run the 'Connect Spotify and Apple Music' workflow again "
                    "and update the SPOTIFY_REFRESH_TOKEN secret."
                ) from e
            raise
        self.access_token = body["access_token"]
        new = body.get("refresh_token")
        if new and new != self.refresh_token:
            self.rotated_refresh_token = new

    def _get(self, url: str, params: dict | None = None) -> dict:
        return call(self.session, "Spotify", "GET", url, params=params, headers=self._auth())

    def _auth(self) -> dict:
        if not self.access_token:
            self.authenticate()
        return {"Authorization": f"Bearer {self.access_token}"}

    # -- user & playlists ---------------------------------------------------
    def me(self) -> dict:
        if self._me is None:
            self._me = self._get(f"{API}/me")
        return self._me

    def find_playlist(self, name: str, playlist_id: str | None = None) -> PlaylistRef | None:
        my_id = self.me().get("id")
        if playlist_id:
            try:
                p = self._get(f"{API}/playlists/{playlist_id}", {"fields": "id,name,owner(id),collaborative,items(total),tracks(total)"})
                return PlaylistRef(p["id"], p.get("name", ""), self._can_edit(p, my_id), _total(p))
            except ApiError as e:
                if e.status not in (400, 404):
                    raise
        exact, loose = [], []
        url: str | None = f"{API}/me/playlists"
        params: dict | None = {"limit": 50}
        while url:
            page = self._get(url, params)
            params = None  # "next" already carries the query
            for p in page.get("items") or []:
                if not p:
                    continue
                pname = p.get("name") or ""
                if pname == name:
                    exact.append(p)
                elif pname.strip().casefold() == name.strip().casefold():
                    loose.append(p)
            url = page.get("next")
        hits = exact or loose
        # Prefer playlists you own over ones you only follow.
        owned = [p for p in hits if self._can_edit(p, my_id)]
        hits = owned or hits
        if not hits:
            return None
        if len(hits) > 1:
            raise RuntimeError(
                f'You have {len(hits)} Spotify playlists named "{name}". Set the SPOTIFY_PLAYLIST_ID '
                "repository variable to the one to sync (it's in the playlist's share link)."
            )
        p = hits[0]
        return PlaylistRef(p["id"], p.get("name", ""), self._can_edit(p, my_id), _total(p))

    @staticmethod
    def _can_edit(p: dict, my_id: str | None) -> bool:
        return bool(p.get("collaborative")) or (p.get("owner") or {}).get("id") == my_id

    def playlist_tracks(self, playlist_id: str) -> list[Track]:
        out: list[Track] = []
        url: str | None = f"{API}/playlists/{playlist_id}/items"
        params: dict | None = {"limit": 50, "additional_types": "track", "market": "from_token"}
        while url:
            page = self._get(url, params)
            params = None
            for entry in page.get("items") or []:
                t = _track_from_item(entry.get("item") or entry.get("track") or {})
                if t:
                    out.append(t)
            url = page.get("next")
        return out


def _total(p: dict) -> int | None:
    for k in ("items", "tracks"):
        v = p.get(k)
        if isinstance(v, dict) and isinstance(v.get("total"), int):
            return v["total"]
    return None
