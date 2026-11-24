"""In-memory stand-ins for the Spotify and Apple Music clients."""
from playlist_sync.models import APPLE, SPOTIFY, PlaylistRef, Track


def sp(uri, title, artist, isrc=None, ms=200_000):
    return Track(SPOTIFY, f"spotify:track:{uri}", title, artist, duration_ms=ms, isrc=isrc)


def am(cid, title, artist, isrc=None, ms=200_000):
    return Track(APPLE, str(cid), title, artist, duration_ms=ms, isrc=isrc)


class FakeSpotify:
    def __init__(self, tracks, name="Music I like", editable=True):
        self.tracks = list(tracks)
        self.ref = PlaylistRef("sp1", name, editable)

    def find_playlist(self, name, playlist_id=None):
        return self.ref if name == self.ref.name else None

    def playlist_tracks(self, playlist_id):
        return list(self.tracks)


class FakeApple:
    """`catalog` is what search/ISRC lookups can find; `playlist` is what the library shows."""

    def __init__(self, catalog=(), playlist=(), exists=True, visible_after_add=True):
        self.catalog = list(catalog)
        self.playlist = list(playlist)
        self.exists = exists
        self.visible_after_add = visible_after_add
        self.added_calls = []
        self.created = []

    def find_playlist(self, name, playlist_id=None):
        return PlaylistRef("p.1", name, True) if self.exists else None

    def create_playlist(self, name, description=""):
        self.exists = True
        self.created.append(name)
        return PlaylistRef("p.1", name, True)

    def playlist_tracks(self, playlist_id):
        return list(self.playlist)

    def songs_by_isrc(self, isrcs):
        out = {}
        for t in self.catalog:
            if t.isrc and t.isrc.upper() in isrcs:
                out.setdefault(t.isrc.upper(), []).append(t)
        return out

    def search(self, title, artist):
        return list(self.catalog)

    def add_tracks(self, playlist_id, ids):
        self.added_calls.append(list(ids))
        if self.visible_after_add:
            by_id = {t.service_id: t for t in self.catalog}
            self.playlist += [by_id[i] for i in ids if i in by_id]
