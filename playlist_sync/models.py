"""Service-neutral track and playlist models, plus cross-service matching."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

SPOTIFY = "spotify"
APPLE = "apple"


@dataclass
class Track:
    """One song as one service sees it."""

    service: str  # "spotify" or "apple"
    service_id: str  # Spotify URI, or Apple catalog ID (numeric) / library ID ("i.xxxx")
    title: str
    artist: str  # display string, e.g. "Artist A, Artist B"
    album: str | None = None
    duration_ms: int | None = None
    isrc: str | None = None
    is_local: bool = False  # Spotify local file / Apple upload with no catalog match
    extra: dict = field(default_factory=dict)  # e.g. Apple library id

    @property
    def key(self) -> str:
        return match_key(self.title, self.artist)


@dataclass
class PlaylistRef:
    id: str
    name: str
    editable: bool = True
    track_count: int | None = None


# Words inside "(...)", "[...]" or after " - " that don't change which recording it is.
_NOISE = re.compile(
    r"\b(feat|ft|featuring|with|remaster(ed)?|\d{4} remaster|mono|stereo|explicit|clean|"
    r"single|album|lp|radio|edit|version|original mix|bonus( track)?|deluxe|expanded|anniversary|"
    r"from)\b",
    re.IGNORECASE,
)
_KEEP = re.compile(r"\b(live|remix|mix|acoustic|instrumental|demo|unplugged|karaoke|cover|sped up|slowed)\b", re.IGNORECASE)
_ARTIST_SPLIT = re.compile(r"\s*(?:,|&|\+|;|/| x | and | feat\.? | ft\.? | featuring | with )\s*", re.IGNORECASE)


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s.casefold()


def _alnum(s: str) -> str:
    # Keep letters and digits from every script, so non-Latin titles still compare.
    return "".join(ch for ch in s if ch.isalnum())


def _drop_noise(segment: str) -> bool:
    return bool(_NOISE.search(segment)) and not _KEEP.search(segment)


def norm_title(title: str) -> str:
    t = _fold(title)
    # "Song - Remastered 2011" -> "Song (Remastered 2011)"
    t = re.sub(r"\s+[-–—]\s+(.+)$", r" (\1)", t)

    def strip(m: re.Match) -> str:
        return "" if _drop_noise(m.group(1)) else " " + m.group(1) + " "

    t = re.sub(r"\(([^)]*)\)", strip, t)
    t = re.sub(r"\[([^\]]*)\]", strip, t)
    out = _alnum(t)
    return out or _alnum(_fold(title))


def primary_artist(artist: str) -> str:
    a = _fold(artist)
    first = _ARTIST_SPLIT.split(a, maxsplit=1)[0]
    first = re.sub(r"^the\s+", "", first)
    return _alnum(first) or _alnum(a)


def match_key(title: str, artist: str) -> str:
    return f"{norm_title(title)}|{primary_artist(artist)}"


def artists_match(a: str, b: str) -> bool:
    pa, pb = primary_artist(a), primary_artist(b)
    if pa == pb:
        return True
    fa, fb = _alnum(_fold(a)), _alnum(_fold(b))
    return bool(pa and pa in fb) or bool(pb and pb in fa)


def pick_best(source: Track, candidates: list[Track], *, by_isrc: bool = False) -> Track | None:
    """Pick the candidate that is the same recording as `source`, or None.

    ISRC hits are trusted (we only prefer the one whose title matches best); text-search
    hits must match title and artist, and be within 20 seconds of the source's length.
    """
    scored = []
    src_title = norm_title(source.title)
    for c in candidates:
        if c.is_local:
            continue
        title_ok = norm_title(c.title) == src_title
        artist_ok = artists_match(source.artist, c.artist)
        diff = None
        if source.duration_ms and c.duration_ms:
            diff = abs(source.duration_ms - c.duration_ms)
        if not by_isrc:
            if not (title_ok and artist_ok):
                continue
            if diff is not None and diff > 20_000:
                continue
        score = (2 if title_ok else 0) + (1 if artist_ok else 0)
        scored.append((score, -(diff or 0), len(scored), c))
    if not scored:
        return None
    scored.sort(key=lambda x: (x[0], x[1], -x[2]), reverse=True)
    return scored[0][3]
