-- Playlist Sync: local SQLite schema (created on-device by the app at first launch).
-- Tracks every sync run and every change so deletions can be told apart from additions.
PRAGMA foreign_keys = ON;

-- One row per song, independent of service.
CREATE TABLE IF NOT EXISTS tracks (
    id           INTEGER PRIMARY KEY,
    match_key    TEXT NOT NULL UNIQUE,   -- normalized title|artist
    title        TEXT NOT NULL,
    artist       TEXT NOT NULL,
    album        TEXT,
    duration_ms  INTEGER,
    isrc         TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_tracks_isrc ON tracks(isrc);

-- Service-specific IDs for a track (Spotify URI / Apple Music catalog ID).
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
    id            INTEGER PRIMARY KEY,
    started_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    finished_at   TEXT,
    status        TEXT NOT NULL DEFAULT 'running'
                  CHECK (status IN ('running','success','partial','failed')),
    added_count   INTEGER NOT NULL DEFAULT 0,
    removed_count INTEGER NOT NULL DEFAULT 0,
    unmatched_count INTEGER NOT NULL DEFAULT 0,
    error         TEXT
);

-- The agreed playlist contents after the last successful run (the "snapshot").
-- Compare against this to detect what was added or removed on each side.
CREATE TABLE IF NOT EXISTS snapshot (
    track_id    INTEGER PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
    synced_run  INTEGER NOT NULL REFERENCES sync_runs(id)
);

-- Full history of every change detected or applied.
CREATE TABLE IF NOT EXISTS change_log (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES sync_runs(id) ON DELETE CASCADE,
    track_id    INTEGER NOT NULL REFERENCES tracks(id),
    action      TEXT NOT NULL CHECK (action IN ('add','remove')),
    origin      TEXT NOT NULL CHECK (origin IN ('spotify','apple')),   -- side where the change happened
    target      TEXT NOT NULL CHECK (target IN ('spotify','apple')),   -- side it was applied to
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','applied','failed','unsupported')),
    detail      TEXT,
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_change_log_run ON change_log(run_id);
CREATE INDEX IF NOT EXISTS idx_change_log_track ON change_log(track_id);

-- Songs that could not be matched on the other service.
CREATE TABLE IF NOT EXISTS unmatched (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES sync_runs(id) ON DELETE CASCADE,
    track_id    INTEGER NOT NULL REFERENCES tracks(id),
    missing_on  TEXT NOT NULL CHECK (missing_on IN ('spotify','apple')),
    UNIQUE (track_id, missing_on)
);

-- Key/value settings (playlist IDs, last sync time).
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
