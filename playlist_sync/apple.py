"""Apple Music API client for one library playlist.

Docs: https://developer.apple.com/documentation/applemusicapi/
- Every request needs a developer token (a JWT you sign with your MusicKit private key).
- Library requests also need a Music User Token, which only comes from MusicKit
  (here: MusicKit on the web, see playlist_sync/connect.py).
- The API can create library playlists and add tracks to them, but it has no endpoint to
  remove tracks, rename or delete a library playlist. Removals are reported instead.
"""
from __future__ import annotations

import re
import textwrap
import time
from urllib.parse import parse_qsl, urlencode, urlsplit

import jwt
import requests

from .http import ApiError, call
from .models import APPLE, PlaylistRef, Track

API = "https://api.music.apple.com"
MAX_DEV_TOKEN_SECONDS = 15_777_000  # Apple's maximum, about 6 months


class AppleAuthError(Exception):
    pass


def normalize_private_key(raw: str) -> str:
    """Accept the .p8 file contents however they were pasted into a secret."""
    key = (raw or "").strip().replace("\\n", "\n").replace("\r", "")
    if "-----BEGIN" in key and "\n" not in key.strip():
        # Pasted on one line: re-wrap the base64 body.
        body = re.sub(r"-----(BEGIN|END) [A-Z ]+-----", "", key).replace(" ", "")
        key = body
    if "-----BEGIN" not in key:
        body = re.sub(r"\s+", "", key)
        key = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(textwrap.wrap(body, 64)) + "\n-----END PRIVATE KEY-----"
    return key + ("\n" if not key.endswith("\n") else "")


def developer_token(team_id: str, key_id: str, private_key: str, ttl_seconds: int = 12 * 3600) -> str:
    now = int(time.time())
    ttl = min(ttl_seconds, MAX_DEV_TOKEN_SECONDS)
    return jwt.encode(
        {"iss": team_id.strip(), "iat": now, "exp": now + ttl},
        normalize_private_key(private_key),
        algorithm="ES256",
        headers={"kid": key_id.strip()},
    )


def _with_params(path: str, extra: dict) -> str:
    """Add params to a relative "next" path without dropping the ones it has."""
    parts = urlsplit(path)
    q = dict(parse_qsl(parts.query))
    for k, v in extra.items():
        q.setdefault(k, v)
    return f"{parts.path}?{urlencode(q)}"


def _song(d: dict, *, library: bool = False) -> Track:
    a = d.get("attributes") or {}
    play = a.get("playParams") or {}
    isrc = a.get("isrc")
    catalog_id = None
    if library:
        catalog = ((d.get("relationships") or {}).get("catalog") or {}).get("data") or []
        if catalog:
            catalog_id = catalog[0].get("id")
            isrc = isrc or (catalog[0].get("attributes") or {}).get("isrc")
        catalog_id = catalog_id or play.get("catalogId")
        sid = catalog_id or d.get("id")
    else:
        sid = d.get("id")
    return Track(
        service=APPLE,
        service_id=str(sid),
        title=a.get("name") or "",
        artist=a.get("artistName") or "",
        album=a.get("albumName"),
        duration_ms=a.get("durationInMillis"),
        isrc=isrc or None,
        is_local=library and not catalog_id,
        extra={"library_id": d.get("id")} if library else {},
    )


class AppleMusic:
    def __init__(self, developer_token: str, user_token: str, session: requests.Session | None = None,
                 storefront: str | None = None):
        self.session = session or requests.Session()
        self.headers = {"Authorization": f"Bearer {developer_token}", "Music-User-Token": user_token}
        self._storefront = storefront

    def _req(self, method: str, path: str, *, params: dict | None = None, json=None) -> dict:
        try:
            return call(self.session, "Apple Music", method, API + path, params=params, json=json,
                        headers=self.headers)
        except ApiError as e:
            if e.status == 401:
                raise AppleAuthError(
                    "Apple Music rejected the developer token. Check APPLE_TEAM_ID, APPLE_MUSIC_KEY_ID and "
                    "APPLE_MUSIC_PRIVATE_KEY (the key needs Media Services / MusicKit enabled)."
                ) from e
            if e.status == 403 and path.startswith("/v1/me/storefront"):
                raise AppleAuthError(
                    "Apple Music rejected the Music User Token (it lasts about 6 months, and needs an active "
                    "Apple Music subscription). Run the 'Connect Spotify and Apple Music' workflow again and "
                    "update the APPLE_MUSIC_USER_TOKEN secret."
                ) from e
            raise

    def _paged(self, path: str, params: dict) -> list[dict]:
        out: list[dict] = []
        body = self._req("GET", path, params=params)
        while True:
            out.extend(body.get("data") or [])
            nxt = body.get("next")
            if not nxt:
                return out
            body = self._req("GET", _with_params(nxt, params))

    # -- user -----------------------------------------------------------------
    def storefront(self) -> str:
        if not self._storefront:
            body = self._req("GET", "/v1/me/storefront")
            self._storefront = (body.get("data") or [{}])[0].get("id") or "us"
        return self._storefront

    # -- playlists --------------------------------------------------------------
    def find_playlist(self, name: str, playlist_id: str | None = None) -> PlaylistRef | None:
        if playlist_id:
            try:
                body = self._req("GET", f"/v1/me/library/playlists/{playlist_id}")
                data = (body.get("data") or [None])[0]
                if data:
                    return self._ref(data)
            except ApiError as e:
                if e.status != 404:
                    raise
        items = self._paged("/v1/me/library/playlists", {"limit": 100})
        exact = [p for p in items if (p.get("attributes") or {}).get("name") == name]
        loose = [p for p in items if ((p.get("attributes") or {}).get("name") or "").strip().casefold()
                 == name.strip().casefold()]
        hits = exact or loose
        editable = [p for p in hits if (p.get("attributes") or {}).get("canEdit")]
        hits = editable or hits
        if not hits:
            return None
        if len(hits) > 1:
            raise RuntimeError(
                f'You have {len(hits)} Apple Music playlists named "{name}". Rename the extra one, or set the '
                "APPLE_PLAYLIST_ID repository variable (shown in the sync log) to the one to use."
            )
        return self._ref(hits[0])

    @staticmethod
    def _ref(p: dict) -> PlaylistRef:
        a = p.get("attributes") or {}
        return PlaylistRef(p["id"], a.get("name", ""), bool(a.get("canEdit", True)))

    def create_playlist(self, name: str, description: str = "") -> PlaylistRef:
        body = self._req("POST", "/v1/me/library/playlists",
                         json={"attributes": {"name": name, "description": description}})
        data = (body.get("data") or [{}])[0]
        return PlaylistRef(data.get("id", ""), name, True)

    def playlist_tracks(self, playlist_id: str) -> list[Track]:
        try:
            rows = self._paged(f"/v1/me/library/playlists/{playlist_id}/tracks",
                               {"limit": 100, "include": "catalog"})
        except ApiError as e:
            if e.status == 404:  # a brand-new or empty playlist has no tracks relationship yet
                return []
            raise
        tracks = [_song(r, library=True) for r in rows if r.get("type", "library-songs") == "library-songs"]
        # Fill in ISRCs we didn't get from the included catalog data.
        need = sorted({t.service_id for t in tracks if not t.isrc and t.service_id.isdigit()})
        if need:
            found = self.songs_by_ids(need)
            for t in tracks:
                s = found.get(t.service_id)
                if s and not t.isrc:
                    t.isrc = s.isrc
        return tracks

    def add_tracks(self, playlist_id: str, ids: list[str]) -> None:
        """Add catalog song IDs (numeric) or library song IDs ("i.…") to the end of the playlist."""
        data = [{"id": i, "type": "songs" if i.isdigit() else "library-songs"} for i in ids]
        for i in range(0, len(data), 50):
            self._req("POST", f"/v1/me/library/playlists/{playlist_id}/tracks", json={"data": data[i:i + 50]})

    # -- catalog ------------------------------------------------------------------
    def songs_by_ids(self, ids: list[str]) -> dict[str, Track]:
        out: dict[str, Track] = {}
        sf = self.storefront()
        for i in range(0, len(ids), 300):
            body = self._req("GET", f"/v1/catalog/{sf}/songs", params={"ids": ",".join(ids[i:i + 300])})
            for d in body.get("data") or []:
                out[d["id"]] = _song(d)
        return out

    def songs_by_isrc(self, isrcs: list[str]) -> dict[str, list[Track]]:
        out: dict[str, list[Track]] = {}
        sf = self.storefront()
        for i in range(0, len(isrcs), 25):
            body = self._req("GET", f"/v1/catalog/{sf}/songs", params={"filter[isrc]": ",".join(isrcs[i:i + 25])})
            for d in body.get("data") or []:
                t = _song(d)
                if t.isrc:
                    out.setdefault(t.isrc.upper(), []).append(t)
        return out

    def search(self, title: str, artist: str) -> list[Track]:
        sf = self.storefront()
        body = self._req("GET", f"/v1/catalog/{sf}/search",
                         params={"term": f"{title} {artist}"[:200], "types": "songs", "limit": 10})
        data = (((body.get("results") or {}).get("songs") or {}).get("data")) or []
        return [_song(d) for d in data]
