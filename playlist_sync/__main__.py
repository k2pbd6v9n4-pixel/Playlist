"""Command line entry point.

python -m playlist_sync run       # the sync (what the weekly workflow runs)
python -m playlist_sync check     # test the credentials, change nothing
python -m playlist_sync connect   # sign-in page that gives you the two user tokens
"""
from __future__ import annotations

import argparse
import os
import sys

from . import config, report


def cmd_run() -> int:
    from .apple import AppleMusic, developer_token
    from .db import DEFAULT_DB, Database, utcnow
    from .engine import SyncEngine
    from .http import ApiError
    from .notify import post
    from .spotify import Spotify

    absent = config.missing(config.SYNC_SECRETS)
    if absent:
        report.publish("## Sync didn't start\n\nThese repository secrets are missing: "
                       + ", ".join(f"`{n}`" for n in absent)
                       + ". See docs/SETUP.md.\n")
        return 1
    env = config.env
    try:
        dev = developer_token(env("APPLE_TEAM_ID"), env("APPLE_MUSIC_KEY_ID"), env("APPLE_MUSIC_PRIVATE_KEY"))
    except Exception as e:
        report.publish("## Sync didn't start\n\nCouldn't sign the Apple Music developer token with "
                       f"APPLE_MUSIC_PRIVATE_KEY ({e.__class__.__name__}). Paste the whole .p8 file, "
                       "including the BEGIN and END lines.\n")
        return 1
    spotify = Spotify(env("SPOTIFY_CLIENT_ID"), env("SPOTIFY_CLIENT_SECRET"), env("SPOTIFY_REFRESH_TOKEN"))
    apple = AppleMusic(dev, env("APPLE_MUSIC_USER_TOKEN"))
    db = Database(env("SYNC_DB_PATH", str(DEFAULT_DB)))
    settings = config.settings()
    res = SyncEngine(spotify, apple, db, settings).run()
    md = report.render(res)

    token, repo = env("GITHUB_TOKEN"), env("GITHUB_REPOSITORY")
    if res.newly_not_on_apple and not settings.dry_run:
        if token and repo:
            run_url = None
            if env("GITHUB_RUN_ID"):
                run_url = f"{env('GITHUB_SERVER_URL', 'https://github.com')}/{repo}/actions/runs/{env('GITHUB_RUN_ID')}"
            try:
                url = post(res.newly_not_on_apple, token=token, repo=repo,
                           spotify_name=settings.spotify_playlist_name,
                           mention=env("NOTIFY_MENTION", env("GITHUB_REPOSITORY_OWNER")), run_url=run_url)
                db.mark_notified([s[0] for s in res.newly_not_on_apple], utcnow())
                db.commit()
                md += f"\nPosted the songs that aren't on Apple Music to [this issue]({url}).\n"
            except ApiError as e:
                md += f"\nCouldn't post the GitHub issue about missing songs ({e.status}: {e.message}).\n"
        else:
            md += "\n(No GITHUB_TOKEN here, so no issue was posted about missing songs.)\n"
    db.close()
    report.publish(md)
    return 1 if res.status == "failed" else 0


def cmd_check() -> int:
    from .check import render, run

    rows, ok = run()
    report.publish(render(rows, ok))
    return 0 if ok else 1


def cmd_connect(args) -> int:
    from .connect import main

    return main(minutes=args.minutes, port=args.port, tunnel=not args.no_tunnel,
                cloudflared=os.environ.get("CLOUDFLARED", "cloudflared"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m playlist_sync")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", help="add Spotify playlist songs to the Apple Music playlist")
    sub.add_parser("check", help="test the credentials without changing anything")
    c = sub.add_parser("connect", help="open a sign-in page to get the Spotify and Apple Music user tokens")
    c.add_argument("--minutes", type=int, default=20)
    c.add_argument("--port", type=int, default=8765)
    c.add_argument("--no-tunnel", action="store_true", help="serve on 127.0.0.1 only (local testing)")
    args = p.parse_args(argv)
    if args.cmd == "check":
        return cmd_check()
    if args.cmd == "connect":
        return cmd_connect(args)
    return cmd_run()


if __name__ == "__main__":
    sys.exit(main())
