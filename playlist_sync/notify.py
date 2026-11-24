"""Tell you about songs that aren't on Apple Music, through one GitHub issue in this repo.

The first time, the run opens an issue titled ISSUE_TITLE; later runs add a comment to it while it's
open. Either way the GitHub app sends you a notification. Each song is reported once (the
database remembers what was posted). Close the issue whenever you like; the next new song opens
a fresh one.

Uses the workflow's built-in GITHUB_TOKEN (needs `issues: write`), so there's no extra key.
"""
from __future__ import annotations

import requests

from .engine import Song
from .http import call

ISSUE_TITLE = "Songs not found on Apple Music"
API = "https://api.github.com"


def _body(songs: list[Song], spotify_name: str, mention: str | None, run_url: str | None) -> str:
    lines = []
    if mention:
        lines.append(f"@{mention}")
    lines.append(f'{len(songs)} song{"s" if len(songs) != 1 else ""} from your Spotify playlist "{spotify_name}" '
                 "couldn't be found on Apple Music, so they weren't added:")
    lines.append("")
    lines += [f"- {title} — {artist}" for _, title, artist in songs[:100]]
    if len(songs) > 100:
        lines.append(f"- …and {len(songs) - 100} more")
    lines.append("")
    lines.append("Each weekly run checks again and adds them if Apple Music gets them.")
    if run_url:
        lines.append(f"\n[Run details]({run_url})")
    return "\n".join(lines)


def post(songs: list[Song], *, token: str, repo: str, spotify_name: str, mention: str | None = None,
         run_url: str | None = None, session: requests.Session | None = None) -> str:
    """Comment on the open issue, or open one. Returns the issue's web URL."""
    s = session or requests.Session()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
               "X-GitHub-Api-Version": "2022-11-28"}
    body = _body(songs, spotify_name, mention, run_url)
    issues = call(s, "GitHub", "GET", f"{API}/repos/{repo}/issues",
                  params={"state": "open", "per_page": 100, "sort": "created", "direction": "desc"},
                  headers=headers)
    existing = next((i for i in issues if isinstance(i, dict) and i.get("title") == ISSUE_TITLE
                     and "pull_request" not in i), None) if isinstance(issues, list) else None
    if existing:
        call(s, "GitHub", "POST", f"{API}/repos/{repo}/issues/{existing['number']}/comments",
             json={"body": body}, headers=headers)
        return existing.get("html_url", "")
    created = call(s, "GitHub", "POST", f"{API}/repos/{repo}/issues",
                   json={"title": ISSUE_TITLE, "body": body}, headers=headers)
    return created.get("html_url", "")
