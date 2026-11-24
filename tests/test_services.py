import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from playlist_sync import notify
from playlist_sync.apple import developer_token, normalize_private_key
from playlist_sync.http import ApiError, call
from playlist_sync.spotify import _track_from_item


def _pem() -> tuple[str, object]:
    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    return pem, key.public_key()


class FakeResp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.content = b"" if body is None else json.dumps(body).encode()
        self.text = self.content.decode()

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.responses.pop(0)


class AppleTokenTests(unittest.TestCase):
    def test_developer_token_claims(self):
        pem, pub = _pem()
        tok = developer_token("TEAM123456", "KEY1234567", pem)
        self.assertEqual(jwt.get_unverified_header(tok)["kid"], "KEY1234567")
        claims = jwt.decode(tok, pub, algorithms=["ES256"])
        self.assertEqual(claims["iss"], "TEAM123456")
        self.assertLessEqual(claims["exp"] - claims["iat"], 15_777_000)

    def test_key_pasted_on_one_line_or_without_headers(self):
        pem, pub = _pem()
        body = "".join(pem.strip().splitlines()[1:-1])
        for variant in (pem.replace("\n", " "), pem.replace("\n", "\\n"), body):
            tok = developer_token("T", "K", variant)
            jwt.decode(tok, pub, algorithms=["ES256"])
        self.assertIn("BEGIN PRIVATE KEY", normalize_private_key(body))


class HttpTests(unittest.TestCase):
    def test_retries_after_rate_limit(self):
        s = FakeSession([FakeResp(429, {}, {"Retry-After": "1"}), FakeResp(200, {"ok": 1})])
        slept = []
        self.assertEqual(call(s, "X", "GET", "https://x/y", sleep=slept.append), {"ok": 1})
        self.assertEqual(slept, [2.0])

    def test_error_message_from_apple_and_spotify(self):
        s = FakeSession([FakeResp(403, {"errors": [{"title": "Forbidden", "detail": "Invalid user token"}]})])
        with self.assertRaises(ApiError) as cm:
            call(s, "Apple Music", "GET", "https://x/y")
        self.assertIn("Invalid user token", cm.exception.message)
        s = FakeSession([FakeResp(400, {"error": "invalid_grant", "error_description": "Refresh token revoked"})])
        with self.assertRaises(ApiError) as cm:
            call(s, "Spotify", "POST", "https://x/y")
        self.assertIn("revoked", cm.exception.message)


class SpotifyParsingTests(unittest.TestCase):
    def test_reads_new_item_shape(self):
        t = _track_from_item({"type": "track", "uri": "spotify:track:1", "name": "N",
                              "artists": [{"name": "A"}, {"name": "B"}], "external_ids": {"isrc": "US1"},
                              "duration_ms": 1000})
        self.assertEqual((t.artist, t.isrc, t.is_local), ("A, B", "US1", False))
        self.assertIsNone(_track_from_item({"type": "episode", "uri": "spotify:episode:1"}))


class NotifyTests(unittest.TestCase):
    def test_comments_on_open_issue(self):
        s = FakeSession([FakeResp(200, [{"number": 7, "title": notify.ISSUE_TITLE, "html_url": "u7"}]),
                         FakeResp(201, {"id": 1})])
        url = notify.post([(1, "Song", "Artist")], token="t", repo="o/r", spotify_name="Music I like",
                          mention="o", session=s)
        self.assertEqual(url, "u7")
        self.assertTrue(s.calls[1][1].endswith("/issues/7/comments"))
        self.assertIn("@o", s.calls[1][2]["json"]["body"])

    def test_opens_issue_when_none_open(self):
        s = FakeSession([FakeResp(200, []), FakeResp(201, {"html_url": "u9"})])
        url = notify.post([(1, "Song", "Artist")], token="t", repo="o/r", spotify_name="Music I like", session=s)
        self.assertEqual(url, "u9")
        self.assertEqual(s.calls[1][2]["json"]["title"], notify.ISSUE_TITLE)


class ConnectPageTests(unittest.TestCase):
    def setUp(self):
        from playlist_sync import connect
        env = {"SPOTIFY_CLIENT_ID": "cid", "SPOTIFY_CLIENT_SECRET": "sec", "GITHUB_REPOSITORY": "o/r"}
        with mock.patch.dict("os.environ", env, clear=False):
            self.app = connect.ConnectApp(minutes=1)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), connect.make_handler(self.app))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()

    def test_needs_the_key(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            urllib.request.urlopen(self.base + "/")
        self.assertEqual(cm.exception.code, 403)
        page = urllib.request.urlopen(f"{self.base}/?k={self.app.key}").read().decode()
        self.assertIn("Sign in to Spotify", page)

    def test_spotify_start_redirects_with_state(self):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        with self.assertRaises(urllib.error.HTTPError) as cm:
            opener.open(f"{self.base}/spotify/start?k={self.app.key}")
        loc = cm.exception.headers["Location"]
        self.assertIn("accounts.spotify.com/authorize", loc)
        self.assertIn(self.app.state, loc)
        self.assertIn("redirect_uri=http%3A%2F%2F127.0.0.1%3A8888%2Fcallback", loc)

    def test_wrong_state_is_refused(self):
        out = self.app.spotify_finish("http://127.0.0.1:8888/callback?code=abcdefghijklmnopqrstuvwxyz&state=nope")
        self.assertIn(b"different sign-in", out)


if __name__ == "__main__":
    unittest.main()
