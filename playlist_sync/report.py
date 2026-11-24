"""Markdown run summary for the GitHub Actions run page."""
from __future__ import annotations

import os

from .engine import Result, Song

MAX_LIST = 50


def songs_md(songs: list[Song]) -> list[str]:
    lines = [f"- {title} — {artist}" for _, title, artist in songs[:MAX_LIST]]
    if len(songs) > MAX_LIST:
        lines.append(f"- …and {len(songs) - MAX_LIST} more (see data/playlist_sync.db)")
    return lines


def render(res: Result) -> str:
    title = {
        "success": "Apple Music is up to date",
        "partial": "Synced, but some songs aren't on Apple Music",
        "failed": "Sync failed",
    }.get(res.status, res.status)
    out = [f"## {title}"]
    if res.dry_run:
        out.append("**Preview only (dry run): nothing was added to Apple Music.**")
    if res.error:
        out += ["", f"**Error:** {res.error}"]
    sp, ap = res.spotify_playlist, res.apple_playlist
    if sp:
        out += ["", f'Spotify "{sp.name}" ({res.spotify_count} songs) → '
                    f'Apple Music "{ap.name if ap else sp.name}" ({res.apple_count} songs before this run)']
    if not res.error:
        out += ["", "| | Songs |", "|---|---|",
                f"| {'Would add' if res.dry_run else 'Added'} to Apple Music | {len(res.added)} |",
                f"| Already in Apple Music | {res.already_there} |",
                f"| Not on Apple Music | {len(res.not_on_apple)} |"]
        if res.waiting:
            out.append(f"| Added earlier, Apple Music hasn't listed them yet | {len(res.waiting)} |")
        if res.removed_in_apple:
            out.append(f"| Added earlier, then removed in Apple Music (not re-added) | {len(res.removed_in_apple)} |")

    if res.added:
        out += ["", f"### {'Would add' if res.dry_run else 'Added'} to Apple Music"] + songs_md(res.added)
    if res.not_on_apple:
        out += ["", "### Not on Apple Music",
                "Apple Music's catalog didn't have a match for these. Each run checks again."]
        out += songs_md(res.not_on_apple)
    if res.removed_in_apple:
        out += ["", "### Removed in Apple Music",
                "The sync added these earlier and they're no longer in the Apple Music playlist, so it left them "
                "out. Add them back in the Music app if that wasn't on purpose."]
        out += songs_md(res.removed_in_apple)
    if res.failures:
        out += ["", "### Problems"] + [f"- {f}" for f in res.failures]
    if res.rotated_spotify_refresh_token:
        out += ["", "### Spotify sent a new sign-in token",
                "If the next run says Spotify refused the sign-in, run **Connect Spotify and Apple Music** again "
                "and update the `SPOTIFY_REFRESH_TOKEN` secret."]
    if res.notes:
        out += [""] + [f"- {n}" for n in res.notes]
    return "\n".join(out) + "\n"


def publish(markdown: str) -> None:
    print(markdown)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(markdown)
