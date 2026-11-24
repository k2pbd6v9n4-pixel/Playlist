-- Playlist Sync: SQLite schema.
-- Used by the GitHub Actions sync (playlist_sync/). The database lives at data/playlist_sync.db
-- and the workflow commits it back to the repo after each run.
-- One-way: every song on the Spotify playlist is added once to the Apple Music playlist.
PRAGMA foreign_keys = ON;

-- One row per song, independent of service.
CREATE TABLE IF NOT EXISTS tracks (
    id           INTEGER PRIMARY KEY,
    match_key    TEXT NOT NULL UNIQUE,   -- normalized title|primary artist
    title        TEXT NOT NULL,
    artist       TEXT NOT NULL,
    album        TEXT,
    duration_ms  INTEGER,
    isrc         TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_tracks_isrc ON tracks(isrc);

-- Service-specific IDs for a track (Spotify URI / Apple Music catalog or library ID).
CREATE TABLE IF NOT EXISTS track_ids (
    track_id     INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    service      TEXT NOT NULL CHECK (service IN ('spotify','apple')),
    service_id   TEXT NOT NULL,
    match_method TEXT CHECK (match_method IN ('isrc','search','manual')),
    PRIMARY KEY (service, service_id)
);
CREATE INDEX IF NOT EXISTS idx_track_ids_track ON track_ids(track_id);

-- One row per sync run.
CREATE TABLE IF NOT EXISTS sync_runs (
    id              INTEGER PRIMARY KEY,
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    finished_at     TEXT,
    status          TEXT NOT NULL DEFAULT 'running'
                    CHECK (status IN ('running','success','partial','failed')),
    spotify_count   INTEGER,              -- songs on the Spotify playlist
    apple_count     INTEGER,              -- songs on the Apple Music playlist before this run
    added_count     INTEGER NOT NULL DEFAULT 0,
    unmatched_count INTEGER NOT NULL DEFAULT 0,
    error           TEXT
);

-- Every change the sync made or tried to make.
CREATE TABLE IF NOT EXISTS change_log (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES sync_runs(id) ON DELETE CASCADE,
    track_id    INTEGER NOT NULL REFERENCES tracks(id),
    action      TEXT NOT NULL CHECK (action IN ('add')),
    origin      TEXT NOT NULL CHECK (origin IN ('spotify','apple')),   -- side the song came from
    target      TEXT NOT NULL CHECK (target IN ('spotify','apple')),   -- side it was added to
    -- applied: Apple Music accepted it. failed: the call failed, or the song never showed up
    -- (the next run tries again).
    status      TEXT NOT NULL CHECK (status IN ('applied','failed')),
    detail      TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_change_log_run ON change_log(run_id);
CREATE INDEX IF NOT EXISTS idx_change_log_track ON change_log(track_id);

-- Songs on Spotify that the Apple Music catalog doesn't have (or we couldn't match).
-- notified_at is set once the song has been posted to the GitHub issue, so you hear about it once.
CREATE TABLE IF NOT EXISTS unmatched (
    id           INTEGER PRIMARY KEY,
    run_id       INTEGER NOT NULL REFERENCES sync_runs(id) ON DELETE CASCADE,  -- last run that saw it
    track_id     INTEGER NOT NULL REFERENCES tracks(id),
    missing_on   TEXT NOT NULL CHECK (missing_on IN ('spotify','apple')),
    first_seen   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    notified_at  TEXT,
    UNIQUE (track_id, missing_on)
);

-- Adds Apple Music accepted but doesn't list yet (it can take a while). While a row is here the
-- song isn't added again, so a slow library never causes duplicates.
CREATE TABLE IF NOT EXISTS pending_adds (
    track_id    INTEGER NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
    target      TEXT NOT NULL CHECK (target IN ('spotify','apple')),
    run_id      INTEGER NOT NULL REFERENCES sync_runs(id),
    added_at    TEXT NOT NULL,
    PRIMARY KEY (track_id, target)
);

-- Key/value settings (playlist IDs, last sync time).
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
