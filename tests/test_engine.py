import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playlist_sync.db import Database
from playlist_sync.engine import Settings, SyncEngine
from tests.fakes import FakeApple, FakeSpotify, am, sp

T0 = datetime(2026, 11, 29, 15, 0, tzinfo=timezone.utc)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sync.db"
        self.db = Database(self.path)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def run_sync(self, spotify, apple, now=T0, **kw):
        return SyncEngine(spotify, apple, self.db, Settings(**kw), now=now).run()

    def test_adds_missing_songs_by_isrc_then_search(self):
        spotify = FakeSpotify([sp("a", "Alpha", "Ann", "ISRC1"), sp("b", "Beta - 2011 Remaster", "Bob"),
                               sp("c", "Gamma", "Cat")])
        apple = FakeApple(catalog=[am(101, "Alpha", "Ann", "ISRC1"), am(102, "Beta", "Bob", "ISRC9"),
                                   am(103, "Gamma", "Cat", "ISRC3")],
                          playlist=[am(103, "Gamma", "Cat", "ISRC3")])
        res = self.run_sync(spotify, apple)
        self.assertEqual(res.status, "success", res.error)
        self.assertEqual(apple.added_calls, [["101", "102"]])
        self.assertEqual(res.already_there, 1)
        rows = self.db.conn.execute("SELECT status FROM change_log").fetchall()
        self.assertEqual([r[0] for r in rows], ["applied", "applied"])

    def test_second_run_adds_nothing(self):
        spotify = FakeSpotify([sp("a", "Alpha", "Ann", "ISRC1")])
        apple = FakeApple(catalog=[am(101, "Alpha", "Ann", "ISRC1")])
        self.run_sync(spotify, apple)
        res = self.run_sync(spotify, apple, now=T0 + timedelta(days=7))
        self.assertEqual(apple.added_calls, [["101"]])
        self.assertEqual(res.already_there, 1)
        self.assertEqual(res.added, [])

    def test_slow_library_does_not_cause_duplicates_then_retries_after_a_week(self):
        spotify = FakeSpotify([sp("a", "Alpha", "Ann", "ISRC1")])
        apple = FakeApple(catalog=[am(101, "Alpha", "Ann", "ISRC1")], visible_after_add=False)
        self.run_sync(spotify, apple)
        res = self.run_sync(spotify, apple, now=T0 + timedelta(days=1))
        self.assertEqual(apple.added_calls, [["101"]])
        self.assertEqual(len(res.waiting), 1)
        res = self.run_sync(spotify, apple, now=T0 + timedelta(days=8))
        self.assertEqual(apple.added_calls, [["101"], ["101"]])

    def test_song_removed_in_apple_is_not_added_back(self):
        spotify = FakeSpotify([sp("a", "Alpha", "Ann", "ISRC1")])
        apple = FakeApple(catalog=[am(101, "Alpha", "Ann", "ISRC1")])
        self.run_sync(spotify, apple)
        self.run_sync(spotify, apple, now=T0 + timedelta(days=1))  # it showed up
        apple.playlist = []  # you removed it in the Music app
        res = self.run_sync(spotify, apple, now=T0 + timedelta(days=2))
        self.assertEqual(apple.added_calls, [["101"]])
        self.assertEqual([s[1] for s in res.removed_in_apple], ["Alpha"])

    def test_unmatched_songs_are_reported_once_and_retried(self):
        spotify = FakeSpotify([sp("x", "Rare Demo", "Nobody")])
        apple = FakeApple(catalog=[])
        res = self.run_sync(spotify, apple)
        self.assertEqual(res.status, "partial")
        self.assertEqual([s[1] for s in res.newly_not_on_apple], ["Rare Demo"])
        self.db.mark_notified([s[0] for s in res.newly_not_on_apple], T0)
        self.db.commit()
        res = self.run_sync(spotify, apple, now=T0 + timedelta(days=7))
        self.assertEqual(len(res.not_on_apple), 1)
        self.assertEqual(res.newly_not_on_apple, [])
        apple.catalog = [am(500, "Rare Demo", "Nobody")]  # Apple Music gets it later
        res = self.run_sync(spotify, apple, now=T0 + timedelta(days=14))
        self.assertEqual(apple.added_calls, [["500"]])
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM unmatched").fetchone()[0], 0)

    def test_dry_run_changes_nothing(self):
        spotify = FakeSpotify([sp("a", "Alpha", "Ann", "ISRC1")])
        apple = FakeApple(catalog=[am(101, "Alpha", "Ann", "ISRC1")], exists=False)
        res = self.run_sync(spotify, apple, dry_run=True)
        self.assertEqual(apple.added_calls, [])
        self.assertEqual(apple.created, [])
        self.assertEqual([s[1] for s in res.added], ["Alpha"])
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM sync_runs").fetchone()[0], 0)

    def test_creates_apple_playlist_when_missing(self):
        spotify = FakeSpotify([sp("a", "Alpha", "Ann", "ISRC1")])
        apple = FakeApple(catalog=[am(101, "Alpha", "Ann", "ISRC1")], exists=False)
        res = self.run_sync(spotify, apple)
        self.assertEqual(apple.created, ["Music I like"])
        self.assertEqual(apple.added_calls, [["101"]])
        self.assertEqual(res.status, "success")

    def test_missing_spotify_playlist_fails_cleanly(self):
        res = self.run_sync(FakeSpotify([], name="Other"), FakeApple())
        self.assertEqual(res.status, "failed")
        self.assertIn("No Spotify playlist", res.error)
        row = self.db.conn.execute("SELECT status, error FROM sync_runs").fetchone()
        self.assertEqual(row[0], "failed")


if __name__ == "__main__":
    unittest.main()
