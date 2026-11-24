import os
import unittest
from unittest import mock

from playlist_sync import check
from playlist_sync.http import ApiError

ONLY_SPOTIFY_APP = {"SPOTIFY_CLIENT_ID": "id", "SPOTIFY_CLIENT_SECRET": "secret"}


class CheckTests(unittest.TestCase):
    def run_check(self, side_effect=None):
        with mock.patch.dict(os.environ, ONLY_SPOTIFY_APP, clear=True), \
                mock.patch.object(check, "client_credentials_token", side_effect=side_effect) as cc:
            rows, ok = check.run()
        cc.assert_called_once()
        self.assertEqual(cc.call_args.args[:2], ("id", "secret"))
        return rows, ok

    def test_spotify_app_ok_and_rest_skipped(self):
        rows, ok = self.run_check()
        self.assertTrue(ok)
        self.assertEqual(rows[0][:2], (check.OK, "Spotify app"))
        self.assertTrue(all(r[0] == check.SKIP for r in rows[1:]))
        self.assertIn("everything set so far works", check.render(rows, ok))

    def test_spotify_app_bad_credentials(self):
        rows, ok = self.run_check(ApiError("Spotify", 400, "invalid_client", "/api/token"))
        self.assertFalse(ok)
        self.assertEqual(rows[0][0], check.FAIL)
        self.assertIn("invalid_client", rows[0][2])
        self.assertIn("something needs fixing", check.render(rows, ok))

    def test_spotify_unreachable(self):
        rows, ok = self.run_check(ApiError("Spotify", 0, "network error: Timeout", "/api/token"))
        self.assertFalse(ok)
        self.assertIn("Couldn't reach Spotify", rows[0][2])


if __name__ == "__main__":
    unittest.main()
