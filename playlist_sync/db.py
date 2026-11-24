"""SQLite change log (data/playlist_sync.db, committed back to the repo by the sync workflow).

Schema: db/schema.sql.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Track

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "playlist_sync.db"
SCHEMA = ROOT / "db" / "schema.sql"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class Database:
    def __init__(self, path: str | Path = DEFAULT_DB, schema: str | Path = SCHEMA):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(Path(schema).read_text(encoding="utf-8"))
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.commit()

    # -- transactions -------------------------------------------------------------
    def commit(self) -> None:
        self.conn.commit()

    def rollback(self) -> None:
        self.conn.rollback()

    def close(self) -> None:
        self.conn.close()

    def _one(self, sql: str, params: tuple = ()):
        row = self.conn.execute(sql, params).fetchone()
        return row[0] if row else None

    # -- tracks -------------------------------------------------------------------
    def resolve(self, t: Track) -> int:
        """Find (or create) the song row for a track seen on one service."""
        tid = self._one("SELECT track_id FROM track_ids WHERE service = ? AND service_id = ?",
                        (t.service, t.service_id))
        method = None
        if tid is None and t.isrc:
            tid = self._one("SELECT id FROM tracks WHERE isrc = ? ORDER BY id LIMIT 1", (t.isrc.upper(),))
            method = "isrc"
        if tid is None:
            tid = self._one("SELECT id FROM tracks WHERE match_key = ?", (t.key,))
            method = "search"
        if tid is None:
            cur = self.conn.execute(
                "INSERT INTO tracks (match_key, title, artist, album, duration_ms, isrc) VALUES (?,?,?,?,?,?)",
                (t.key, t.title, t.artist, t.album, t.duration_ms, t.isrc.upper() if t.isrc else None),
            )
            tid = cur.lastrowid
            method = None  # first time we've seen this song: it's the source, not a match
        elif t.isrc:
            self.conn.execute("UPDATE tracks SET isrc = COALESCE(isrc, ?) WHERE id = ?", (t.isrc.upper(), tid))
        self.add_service_id(tid, t.service, t.service_id, method)
        return int(tid)

    def add_service_id(self, tid: int, service: str, service_id: str, method: str | None) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO track_ids (track_id, service, service_id, match_method) VALUES (?,?,?,?)",
            (tid, service, service_id, method),
        )

    def service_ids(self, tid: int, service: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT service_id FROM track_ids WHERE track_id = ? AND service = ? ORDER BY rowid",
            (tid, service),
        ).fetchall()
        return [r[0] for r in rows]

    def track_label(self, tid: int) -> tuple[str, str]:
        row = self.conn.execute("SELECT title, artist FROM tracks WHERE id = ?", (tid,)).fetchone()
        return (row["title"], row["artist"]) if row else ("?", "?")

    # -- runs and the change log ----------------------------------------------------
    def start_run(self) -> int:
        return int(self.conn.execute("INSERT INTO sync_runs DEFAULT VALUES").lastrowid)

    def finish_run(self, run_id: int, status: str, *, spotify_count: int | None, apple_count: int | None,
                   added: int, unmatched: int, error: str | None = None) -> None:
        self.conn.execute(
            "UPDATE sync_runs SET finished_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), status = ?, "
            "spotify_count = ?, apple_count = ?, added_count = ?, unmatched_count = ?, error = ? WHERE id = ?",
            (status, spotify_count, apple_count, added, unmatched, error, run_id),
        )

    def log(self, run_id: int, tid: int, status: str, detail: str | None = None,
            origin: str = "spotify", target: str = "apple") -> None:
        self.conn.execute(
            "INSERT INTO change_log (run_id, track_id, action, origin, target, status, detail) "
            "VALUES (?,?,'add',?,?,?,?)",
            (run_id, tid, origin, target, status, detail),
        )

    def added_before(self, target: str = "apple") -> set[int]:
        """Songs the sync has successfully added to `target` at some point."""
        rows = self.conn.execute(
            "SELECT DISTINCT track_id FROM change_log WHERE action = 'add' AND target = ? AND status = 'applied'",
            (target,),
        )
        return {r[0] for r in rows}

    def mark_add_failed(self, tid: int, detail: str, target: str = "apple") -> None:
        self.conn.execute(
            "UPDATE change_log SET status = 'failed', detail = ? WHERE track_id = ? AND action = 'add' "
            "AND target = ? AND status = 'applied'",
            (detail, tid, target),
        )

    # -- adds that Apple Music accepted but doesn't show yet ---------------------------
    def pending(self, target: str = "apple") -> dict[int, datetime]:
        rows = self.conn.execute("SELECT track_id, added_at FROM pending_adds WHERE target = ?", (target,))
        return {r[0]: parse_iso(r[1]) for r in rows}

    def add_pending(self, tid: int, run_id: int, when: datetime, target: str = "apple") -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO pending_adds (track_id, target, run_id, added_at) VALUES (?,?,?,?)",
            (tid, target, run_id, iso(when)),
        )

    def clear_pending(self, tid: int, target: str = "apple") -> None:
        self.conn.execute("DELETE FROM pending_adds WHERE track_id = ? AND target = ?", (tid, target))

    # -- songs with no match on Apple Music ----------------------------------------------
    def mark_unmatched(self, tid: int, run_id: int, missing_on: str = "apple") -> None:
        self.conn.execute(
            "INSERT INTO unmatched (run_id, track_id, missing_on) VALUES (?,?,?) "
            "ON CONFLICT(track_id, missing_on) DO UPDATE SET run_id = excluded.run_id",
            (run_id, tid, missing_on),
        )

    def clear_unmatched(self, keep: set[int], missing_on: str = "apple") -> None:
        rows = self.conn.execute("SELECT track_id FROM unmatched WHERE missing_on = ?", (missing_on,))
        gone = [r[0] for r in rows if r[0] not in keep]
        self.conn.executemany("DELETE FROM unmatched WHERE track_id = ? AND missing_on = ?",
                              [(g, missing_on) for g in gone])

    def unnotified(self, missing_on: str = "apple") -> list[int]:
        rows = self.conn.execute(
            "SELECT track_id FROM unmatched WHERE missing_on = ? AND notified_at IS NULL ORDER BY id",
            (missing_on,),
        )
        return [r[0] for r in rows]

    def mark_notified(self, tids: list[int], when: datetime, missing_on: str = "apple") -> None:
        self.conn.executemany(
            "UPDATE unmatched SET notified_at = ? WHERE track_id = ? AND missing_on = ?",
            [(iso(when), t, missing_on) for t in tids],
        )

    # -- settings -----------------------------------------------------------------------
    def get_setting(self, key: str) -> str | None:
        return self._one("SELECT value FROM settings WHERE key = ?", (key,))

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
