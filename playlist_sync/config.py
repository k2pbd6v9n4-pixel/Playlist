"""Read settings from environment variables (GitHub Actions secrets and variables)."""
from __future__ import annotations

import os

from .engine import Settings

SYNC_SECRETS = (
    "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET", "SPOTIFY_REFRESH_TOKEN",
    "APPLE_TEAM_ID", "APPLE_MUSIC_KEY_ID", "APPLE_MUSIC_PRIVATE_KEY", "APPLE_MUSIC_USER_TOKEN",
)


def env(name: str, default: str | None = None) -> str | None:
    v = os.environ.get(name)
    if v is None or not v.strip():
        return default
    return v if "PRIVATE_KEY" in name else v.strip()


def flag(name: str) -> bool:
    return (env(name, "") or "").lower() in ("1", "true", "yes", "on")


def missing(names: tuple[str, ...]) -> list[str]:
    return [n for n in names if not env(n)]


def settings() -> Settings:
    return Settings(
        spotify_playlist_name=env("SPOTIFY_PLAYLIST_NAME", "Music I like"),
        apple_playlist_name=env("APPLE_PLAYLIST_NAME", "Music I like"),
        spotify_playlist_id=env("SPOTIFY_PLAYLIST_ID"),
        apple_playlist_id=env("APPLE_PLAYLIST_ID"),
        dry_run=flag("DRY_RUN"),
    )
