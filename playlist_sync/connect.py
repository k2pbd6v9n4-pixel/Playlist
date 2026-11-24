"""A short-lived sign-in page, served from the GitHub Actions runner, that gives you the two
user tokens the sync needs. It works from an iPhone, with no Mac and no hosting.

How it works (the 'Connect Spotify and Apple Music' workflow):
1. The runner starts this page and opens a temporary public https link to it with a
   Cloudflare quick tunnel (trycloudflare.com). The link, with a one-time key, is printed in
   the run log. Requests without the key are refused.
2. Spotify: you sign in on Spotify's own site. Spotify then sends your browser to
   http://127.0.0.1:8888/callback?code=..., which won't load on a phone; you copy that address
   and paste it into the page. The runner swaps the code for a refresh token and shows it.
3. Apple Music: the page uses Apple's MusicKit on the web. You sign in with your Apple Account
   in Apple's own window, and the page shows your Music User Token.
4. You copy each token into a repository secret. Nothing is saved on the runner, and the
   page stops when you tap "I'm done" or after the time limit.
"""
from __future__ import annotations

import hmac
import html
import json
import re
import secrets
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import requests

from . import config
from .apple import AppleMusic, developer_token
from .http import ApiError
from .spotify import REDIRECT_URI, Spotify, authorize_url, exchange_code

TUNNEL_URL = re.compile(r"https://[-a-z0-9]+\.trycloudflare\.com")

PAGE_CSS = """
body{font:16px/1.45 -apple-system,system-ui,sans-serif;margin:0;padding:16px;background:#f5f5f7;color:#1d1d1f}
main{max-width:560px;margin:auto}
section{background:#fff;border-radius:14px;padding:16px 18px;margin:14px 0;box-shadow:0 1px 3px #0001}
h1{font-size:22px} h2{font-size:18px;margin:0 0 8px}
.btn{display:inline-block;border:0;border-radius:10px;padding:12px 16px;font-size:16px;font-weight:600;
     background:#1d1d1f;color:#fff;text-decoration:none;margin:6px 0;cursor:pointer}
.spotify{background:#1db954}.apple{background:#fa233b}.ghost{background:#e8e8ed;color:#1d1d1f}
textarea{width:100%;box-sizing:border-box;font:13px ui-monospace,Menlo,monospace;border-radius:8px;
         border:1px solid #c7c7cc;padding:8px;min-height:84px}
.ok{color:#1a7f37;font-weight:600}.err{color:#c62828;font-weight:600}
code{background:#f0f0f3;padding:1px 5px;border-radius:5px}
small{color:#6e6e73}
"""


def _copy_js() -> str:
    return """
function copyFrom(id, btn){
  const el=document.getElementById(id); el.select(); el.setSelectionRange(0, 99999);
  (navigator.clipboard ? navigator.clipboard.writeText(el.value) : Promise.reject())
    .then(()=>{btn.textContent='Copied';}, ()=>{document.execCommand('copy'); btn.textContent='Copied';});
}
"""


class ConnectApp:
    def __init__(self, minutes: int = 20, session: requests.Session | None = None):
        self.key = secrets.token_urlsafe(18)
        self.state = secrets.token_urlsafe(18)
        self.deadline = time.time() + minutes * 60
        self.done = threading.Event()
        self.session = session or requests.Session()
        self.cfg = config.settings()
        e = config.env
        self.spotify_id, self.spotify_secret = e("SPOTIFY_CLIENT_ID"), e("SPOTIFY_CLIENT_SECRET")
        self.apple_parts = (e("APPLE_TEAM_ID"), e("APPLE_MUSIC_KEY_ID"), e("APPLE_MUSIC_PRIVATE_KEY"))
        self.repo = e("GITHUB_REPOSITORY")
        self.dev_token: str | None = None
        self.dev_error: str | None = None
        if all(self.apple_parts):
            try:
                self.dev_token = developer_token(*self.apple_parts, ttl_seconds=minutes * 60 + 600)
            except Exception as exc:  # bad key format
                self.dev_error = f"Couldn't sign with APPLE_MUSIC_PRIVATE_KEY ({exc.__class__.__name__})."

    # -- helpers -------------------------------------------------------------------------
    def key_ok(self, value: str | None) -> bool:
        return bool(value) and hmac.compare_digest(value, self.key)

    def secrets_link(self) -> str:
        if not self.repo:
            return "your repo's Settings → Secrets and variables → Actions"
        url = f"https://github.com/{self.repo}/settings/secrets/actions/new"
        return f'<a href="{html.escape(url)}" target="_blank">New repository secret</a>'

    def page(self, body: str) -> bytes:
        doc = (f"<!doctype html><html><head><meta charset=utf-8>"
               f"<meta name=viewport content='width=device-width,initial-scale=1'>"
               f"<title>Connect Playlist Sync</title><style>{PAGE_CSS}</style>"
               f"<script>{_copy_js()}</script></head><body><main>{body}</main></body></html>")
        return doc.encode()

    def token_box(self, box_id: str, secret_name: str, value: str) -> str:
        return (f"<p>Copy this and save it as the repository secret <code>{secret_name}</code> "
                f"({self.secrets_link()}).</p>"
                f"<textarea id={box_id} readonly>{html.escape(value)}</textarea>"
                f"<button class='btn ghost' onclick=\"copyFrom('{box_id}', this)\">Copy</button>")

    # -- pages ---------------------------------------------------------------------------
    def home(self) -> bytes:
        k = html.escape(self.key)
        if self.spotify_id and self.spotify_secret:
            spotify = f"""
<p><b>1.</b> Tap the button and sign in to Spotify, then tap <b>Agree</b>.</p>
<a class='btn spotify' href='/spotify/start?k={k}' target='_blank'>Sign in to Spotify</a>
<p><b>2.</b> Safari then shows <i>can't connect to the server</i>. That's expected. Tap the address bar,
copy the whole address (it starts with <code>http://127.0.0.1:8888/callback?code=</code>), come back to this
tab and paste it here:</p>
<form method=post action='/spotify/finish'><input type=hidden name=k value='{k}'>
<textarea name=pasted placeholder='http://127.0.0.1:8888/callback?code=…'></textarea>
<button class='btn spotify'>Get my Spotify token</button></form>"""
        else:
            spotify = ("<p class=err>Add the <code>SPOTIFY_CLIENT_ID</code> and <code>SPOTIFY_CLIENT_SECRET</code> "
                       "repository secrets first, then run this workflow again.</p>")
        if self.dev_token:
            dev = json.dumps(self.dev_token)
            apple = f"""
<p>Tap the button and sign in with the Apple Account that has your Apple Music subscription.
If nothing opens, allow pop-ups for this page and tap again.</p>
<button class='btn apple' id=amBtn onclick='amConnect()' disabled>Loading Apple Music…</button>
<p id=amStatus></p><div id=amOut></div>
<script src='https://js-cdn.music.apple.com/musickit/v3/musickit.js' data-web-components async></script>
<script>
const DEV={dev}, KEY={json.dumps(self.key)};
document.addEventListener('musickitloaded', async () => {{
  try {{
    await MusicKit.configure({{developerToken: DEV, app: {{name: 'Playlist Sync', build: '1.0.0'}}}});
    const b=document.getElementById('amBtn'); b.disabled=false; b.textContent='Sign in to Apple Music';
  }} catch (e) {{ document.getElementById('amStatus').innerHTML='<span class=err>MusicKit failed to start: '+e+'</span>'; }}
}});
async function amConnect() {{
  const st=document.getElementById('amStatus');
  try {{
    const music=MusicKit.getInstance();
    const token=await music.authorize();
    if(!token) throw new Error('no token returned');
    st.textContent='Checking the token…';
    const r=await fetch('/apple/verify', {{method:'POST', headers:{{'Content-Type':'application/json'}},
      body: JSON.stringify({{k: KEY, token: token}})}});
    const j=await r.json();
    st.innerHTML = j.ok ? '<span class=ok>'+j.message+'</span>' : '<span class=err>'+j.message+'</span>';
    document.getElementById('amOut').innerHTML = j.box || '';
  }} catch (e) {{ st.innerHTML='<span class=err>Apple Music sign-in didn\\'t finish: '+e+'</span>'; }}
}}
</script>"""
        elif self.dev_error:
            apple = f"<p class=err>{html.escape(self.dev_error)} Paste the whole .p8 file, including the BEGIN and END lines.</p>"
        else:
            apple = ("<p class=err>Add the <code>APPLE_TEAM_ID</code>, <code>APPLE_MUSIC_KEY_ID</code> and "
                     "<code>APPLE_MUSIC_PRIVATE_KEY</code> repository secrets first, then run this workflow again.</p>")
        left = max(0, int((self.deadline - time.time()) / 60))
        return self.page(f"""
<h1>Connect Playlist Sync</h1>
<small>This page works for about {left} more minutes. Do Spotify and Apple Music in either order.</small>
<section><h2>Spotify</h2>{spotify}</section>
<section><h2>Apple Music</h2>{apple}</section>
<section><form method=post action='/done'><input type=hidden name=k value='{k}'>
<button class='btn ghost'>I'm done, close this page</button></form></section>""")

    def spotify_finish(self, pasted: str) -> bytes:
        back = f"<p><a href='/?k={html.escape(self.key)}'>← Back</a></p>"
        pasted = (pasted or "").strip()
        q = parse_qs(urlsplit(pasted).query) if "?" in pasted else {}
        if q.get("error"):
            return self.page(f"<section><p class=err>Spotify said: {html.escape(q['error'][0])}.</p>{back}</section>")
        code = (q.get("code") or [None])[0] or (pasted if re.fullmatch(r"[-_A-Za-z0-9]{20,}", pasted) else None)
        if not code:
            return self.page("<section><p class=err>That doesn't look like the address Spotify sent you to. "
                             f"Copy the whole address from the address bar.</p>{back}</section>")
        if q and not hmac.compare_digest((q.get("state") or [""])[0], self.state):
            return self.page("<section><p class=err>That address is from a different sign-in. Tap "
                             f"<b>Sign in to Spotify</b> again.</p>{back}</section>")
        try:
            tok = exchange_code(self.spotify_id, self.spotify_secret, code, self.session)
        except ApiError as e:
            return self.page(f"<section><p class=err>Spotify refused the code ({html.escape(e.message)}). "
                             "Codes work once and only for a few minutes, so sign in again.</p>"
                             f"<p>Also check that <code>{REDIRECT_URI}</code> is listed exactly under Redirect URIs "
                             f"in the Spotify app's settings.</p>{back}</section>")
        refresh = tok.get("refresh_token", "")
        msg = "Signed in."
        try:
            sp = Spotify(self.spotify_id, self.spotify_secret, refresh, self.session)
            sp.access_token = tok.get("access_token")
            me = sp.me()
            who = me.get("display_name") or me.get("id")
            pl = sp.find_playlist(self.cfg.spotify_playlist_name, self.cfg.spotify_playlist_id)
            found = (f'Found your playlist "{html.escape(pl.name)}".' if pl else
                     f'But there\'s no playlist named "{html.escape(self.cfg.spotify_playlist_name)}" in your library yet.')
            msg = f"Signed in as {html.escape(str(who))}. {found}"
        except (ApiError, RuntimeError) as e:
            msg = f"Signed in, but checking your playlists failed: {html.escape(str(e))}"
        return self.page(f"<section><h2>Spotify</h2><p class=ok>{msg}</p>"
                         f"{self.token_box('sp', 'SPOTIFY_REFRESH_TOKEN', refresh)}{back}</section>")

    def apple_verify(self, token: str) -> dict:
        if not self.dev_token or not token:
            return {"ok": False, "message": "No token to check."}
        try:
            am = AppleMusic(self.dev_token, token, self.session)
            sf = am.storefront()
            pl = am.find_playlist(self.cfg.apple_playlist_name, self.cfg.apple_playlist_id)
            found = (f'Found your playlist "{pl.name}".' if pl else
                     f'No playlist named "{self.cfg.apple_playlist_name}" yet; the first sync creates it.')
            message = f"Signed in to Apple Music (store: {sf.upper()}). {found}"
            ok = True
        except Exception as e:  # show the reason on the page
            message, ok = f"Got a token, but Apple Music didn't accept it: {e}", False
        return {"ok": ok, "message": html.escape(message),
                "box": self.token_box("am", "APPLE_MUSIC_USER_TOKEN", token) if ok else ""}


def make_handler(app: ConnectApp):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # keep tokens and codes out of the run log
            return

        def _send(self, code: int, body: bytes, ctype: str = "text/html; charset=utf-8", extra: dict | None = None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "no-referrer")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(body)

        def _form(self) -> dict:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(min(n, 20_000)).decode("utf-8", "replace")
            if "json" in (self.headers.get("Content-Type") or ""):
                try:
                    return json.loads(raw)
                except ValueError:
                    return {}
            return {k: v[0] for k, v in parse_qs(raw).items()}

        def do_GET(self):
            u = urlsplit(self.path)
            k = (parse_qs(u.query).get("k") or [None])[0]
            if not app.key_ok(k):
                return self._send(403, b"Forbidden", "text/plain")
            if u.path == "/":
                return self._send(200, app.home())
            if u.path == "/spotify/start" and app.spotify_id:
                return self._send(302, b"", extra={"Location": authorize_url(app.spotify_id, app.state)})
            return self._send(404, b"Not found", "text/plain")

        def do_POST(self):
            u = urlsplit(self.path)
            form = self._form()
            if not app.key_ok(form.get("k")):
                return self._send(403, b"Forbidden", "text/plain")
            if u.path == "/spotify/finish" and app.spotify_id:
                return self._send(200, app.spotify_finish(form.get("pasted", "")))
            if u.path == "/apple/verify":
                return self._send(200, json.dumps(app.apple_verify(form.get("token", ""))).encode(),
                                  "application/json")
            if u.path == "/done":
                app.done.set()
                return self._send(200, app.page("<section><h2>All done</h2><p>The page is closed. Next, run "
                                                "<b>Check connections</b> to test everything.</p></section>"))
            return self._send(404, b"Not found", "text/plain")

    return Handler


def start_tunnel(port: int, cloudflared: str, timeout: float = 90) -> tuple[subprocess.Popen, str]:
    proc = subprocess.Popen(
        [cloudflared, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    found: list[str] = []
    ready = threading.Event()

    def drain():
        for line in proc.stderr:  # keep reading so the pipe never fills up
            m = TUNNEL_URL.search(line)
            if m and not found:
                found.append(m.group(0))
                ready.set()

    threading.Thread(target=drain, daemon=True).start()
    if not ready.wait(timeout):
        proc.terminate()
        raise RuntimeError("The Cloudflare tunnel didn't start. Run the workflow again.")
    return proc, found[0]


def main(minutes: int = 20, port: int = 8765, tunnel: bool = True, cloudflared: str = "cloudflared") -> int:
    app = ConnectApp(minutes=minutes)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    proc = None
    try:
        if tunnel:
            proc, base = start_tunnel(port, cloudflared)
        else:
            base = f"http://127.0.0.1:{port}"
        link = f"{base}/?k={app.key}"
        print("=" * 60)
        print("Open this link on your phone (give it 10 seconds if it doesn't load at first):")
        print(link)
        print(f"It stops after {minutes} minutes, or when you tap \"I'm done\".")
        print("=" * 60, flush=True)
        print(f"::notice title=Open this link on your phone::{link}", flush=True)
        app.done.wait(max(0, app.deadline - time.time()))
        print("Done." if app.done.is_set() else "Time's up. Run the workflow again if you weren't finished.")
        return 0
    finally:
        server.shutdown()
        if proc:
            proc.terminate()
