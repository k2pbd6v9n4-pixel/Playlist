"""One-way sync: every song on the Spotify playlist goes into the Apple Music playlist.

Each run:
1. Reads the Spotify playlist and the Apple Music playlist.
2. Matches songs across the two by ISRC (the recording's ID), then by title + artist.
3. Adds every Spotify song that isn't in the Apple Music playlist yet, once.
4. Records songs the Apple Music catalog doesn't have, so you can be told about them.

Nothing is ever removed, on either side. Two rules keep the Apple playlist free of duplicates:
- A song Apple Music accepted but doesn't list yet isn't added again for up to 7 days
  (the library can be slow). If it still isn't there after that, the next run adds it again.
- A song the sync added that later disappears from the Apple playlist was most likely removed by
  you, so it isn't added back. It's listed in the run summary instead.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .db import Database, utcnow
from .http import ApiError
from .models import APPLE, PlaylistRef, Track, pick_best

PENDING_GRACE = timedelta(days=7)


class SyncError(Exception):
    pass


@dataclass
class Settings:
    spotify_playlist_name: str = "Music I like"
    apple_playlist_name: str = "Music I like"
    spotify_playlist_id: str | None = None
    apple_playlist_id: str | None = None
    dry_run: bool = False


Song = tuple[int, str, str]  # (track id, title, artist)


@dataclass
class Result:
    run_id: int = 0
    status: str = "running"
    dry_run: bool = False
    error: str | None = None
    spotify_playlist: PlaylistRef | None = None
    apple_playlist: PlaylistRef | None = None
    spotify_count: int = 0
    apple_count: int = 0
    already_there: int = 0
    added: list[Song] = field(default_factory=list)
    not_on_apple: list[Song] = field(default_factory=list)
    newly_not_on_apple: list[Song] = field(default_factory=list)  # not reported in an earlier run
    removed_in_apple: list[Song] = field(default_factory=list)  # added earlier, since removed by you
    waiting: list[Song] = field(default_factory=list)  # accepted by Apple, not listed yet
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    rotated_spotify_refresh_token: bool = False


class SyncEngine:
    def __init__(self, spotify, apple, db: Database, settings: Settings, now: datetime | None = None):
        self.spotify = spotify
        self.apple = apple
        self.db = db
        self.cfg = settings
        self.now = now or utcnow()

    def song(self, tid: int) -> Song:
        title, artist = self.db.track_label(tid)
        return (tid, title, artist)

    # -- entry point ------------------------------------------------------------------
    def run(self) -> Result:
        res = Result(dry_run=self.cfg.dry_run)
        res.run_id = self.db.start_run()
        try:
            self._run(res)
            res.status = "partial" if (res.not_on_apple or res.failures) else "success"
        except Exception as exc:  # recorded in the database and the run summary
            res.status = "failed"
            res.error = str(exc)
        if getattr(self.spotify, "rotated_refresh_token", None):
            res.rotated_spotify_refresh_token = True
        self.db.finish_run(
            res.run_id, res.status, spotify_count=res.spotify_count, apple_count=res.apple_count,
            added=len(res.added), unmatched=len(res.not_on_apple), error=res.error,
        )
        if self.cfg.dry_run:
            self.db.rollback()
        else:
            self.db.set_setting("last_run_at", self.now.isoformat())
            self.db.commit()
        return res

    # -- the sync ----------------------------------------------------------------------
    def _run(self, res: Result) -> None:
        cfg, db = self.cfg, self.db
        run_id = res.run_id

        # 1. Find both playlists.
        sp_key = f"spotify_playlist_id:{cfg.spotify_playlist_name}"
        sp = self.spotify.find_playlist(cfg.spotify_playlist_name, cfg.spotify_playlist_id or db.get_setting(sp_key))
        if sp is None:
            raise SyncError(f'No Spotify playlist named "{cfg.spotify_playlist_name}" in your library.')
        if not sp.editable:
            raise SyncError(f'The Spotify playlist "{sp.name}" belongs to someone else. Spotify only lets apps '
                            "read songs from playlists you own or collaborate on.")
        db.set_setting(sp_key, sp.id)
        res.spotify_playlist = sp

        ap_key = f"apple_playlist_id:{cfg.apple_playlist_name}"
        ap = self.apple.find_playlist(cfg.apple_playlist_name, cfg.apple_playlist_id or db.get_setting(ap_key))
        created = False
        if ap is None:
            if cfg.dry_run:
                res.notes.append(f'Would create the Apple Music playlist "{cfg.apple_playlist_name}".')
            else:
                ap = self.apple.create_playlist(cfg.apple_playlist_name,
                                                "Songs from my Spotify playlist, added by Playlist Sync.")
                created = True
                res.notes.append(f'Created the Apple Music playlist "{cfg.apple_playlist_name}".')
        if ap is not None:
            if not ap.editable:
                raise SyncError(f'The Apple Music playlist "{ap.name}" can\'t be edited (it may be one you '
                                "follow rather than one you made).")
            db.set_setting(ap_key, ap.id)
        res.apple_playlist = ap

        # 2. Read both sides and map every entry to a song row.
        s_tracks = self.spotify.playlist_tracks(sp.id)
        a_tracks = self.apple.playlist_tracks(ap.id) if (ap is not None and not created) else []
        res.spotify_count, res.apple_count = len(s_tracks), len(a_tracks)

        S: dict[int, list[Track]] = defaultdict(list)  # keeps Spotify's order
        for t in s_tracks:
            S[db.resolve(t)].append(t)
        on_apple = {db.resolve(t) for t in a_tracks}

        # 3. Adds from earlier runs that Apple Music doesn't list yet.
        pending = db.pending(APPLE)
        for tid, added_at in list(pending.items()):
            if tid in on_apple:
                db.clear_pending(tid)
                del pending[tid]
            elif self.now - added_at > PENDING_GRACE:
                db.clear_pending(tid)
                del pending[tid]
                db.mark_add_failed(tid, "Apple Music accepted it but never listed it; trying again")
        added_before = db.added_before(APPLE)

        to_add: list[int] = []
        for tid in S:
            if tid in on_apple:
                res.already_there += 1
            elif tid in pending:
                res.waiting.append(self.song(tid))
            elif tid in added_before:
                res.removed_in_apple.append(self.song(tid))
            else:
                to_add.append(tid)

        # 4. Match and add.
        self._add(res, ap, to_add, S)

        # 5. Songs Apple Music doesn't have: keep only those still on Spotify and still unmatched.
        missing = {s[0] for s in res.not_on_apple}
        db.clear_unmatched(missing)
        unreported = set(db.unnotified(APPLE))
        res.newly_not_on_apple = [s for s in res.not_on_apple if s[0] in unreported]

    def _add(self, res: Result, ap: PlaylistRef | None, tids: list[int], S: dict) -> None:
        if not tids:
            return
        db = self.db
        chosen: dict[int, str] = {}
        need: list[int] = []
        for tid in tids:
            ids = db.service_ids(tid, APPLE)
            known = [i for i in ids if i.isdigit()] or [i for i in ids if i.startswith("i.")]
            if known:
                chosen[tid] = known[0]
            else:
                need.append(tid)
        isrcs = sorted({S[tid][0].isrc.upper() for tid in need if S[tid][0].isrc})
        by_isrc = self.apple.songs_by_isrc(isrcs) if isrcs else {}
        for tid in need:
            src = S[tid][0]
            best = pick_best(src, by_isrc.get((src.isrc or "").upper(), []), by_isrc=True)
            method = "isrc"
            if best is None:
                best = pick_best(src, self.apple.search(src.title, src.artist))
                method = "search"
            if best is None:
                db.mark_unmatched(tid, res.run_id)
                res.not_on_apple.append(self.song(tid))
                continue
            db.add_service_id(tid, APPLE, best.service_id, method)
            chosen[tid] = best.service_id
        if not chosen:
            return
        order = [t for t in tids if t in chosen]  # Spotify's order
        try:
            if not self.cfg.dry_run and ap is not None:
                self.apple.add_tracks(ap.id, [chosen[t] for t in order])
        except ApiError as e:
            for tid in order:
                db.log(res.run_id, tid, "failed", str(e)[:300])
            res.failures.append(f"Couldn't add {len(order)} song(s) to Apple Music: {e.message}")
            return
        for tid in order:
            db.log(res.run_id, tid, "applied")
            db.add_pending(tid, res.run_id, self.now)
        res.added = [self.song(t) for t in order]
