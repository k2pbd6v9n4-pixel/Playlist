import Foundation
import SQLite3

enum DBError: Error { case open, schema, sql(String) }

private let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

final class Database {
    private var db: OpaquePointer?

    init() throws {
        let dir = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask,
                                              appropriateFor: nil, create: true)
        let path = dir.appendingPathComponent("playlist_sync.db").path
        guard sqlite3_open(path, &db) == SQLITE_OK else { throw DBError.open }
        guard let url = Bundle.main.url(forResource: "schema", withExtension: "sql"),
              let sql = try? String(contentsOf: url, encoding: .utf8) else { throw DBError.schema }
        try exec(sql)
    }

    deinit { sqlite3_close(db) }

    func exec(_ sql: String) throws {
        var err: UnsafeMutablePointer<CChar>?
        if sqlite3_exec(db, sql, nil, nil, &err) != SQLITE_OK {
            let msg = err.map { String(cString: $0) } ?? "unknown"
            sqlite3_free(err)
            throw DBError.sql(msg)
        }
    }

    @discardableResult
    func run(_ sql: String, _ params: [Any?] = []) throws -> Int64 {
        let stmt = try prepare(sql, params)
        defer { sqlite3_finalize(stmt) }
        guard sqlite3_step(stmt) == SQLITE_DONE else { throw DBError.sql(String(cString: sqlite3_errmsg(db))) }
        return sqlite3_last_insert_rowid(db)
    }

    func query(_ sql: String, _ params: [Any?] = []) throws -> [[String: Any?]] {
        let stmt = try prepare(sql, params)
        defer { sqlite3_finalize(stmt) }
        var rows: [[String: Any?]] = []
        while sqlite3_step(stmt) == SQLITE_ROW {
            var row: [String: Any?] = [:]
            for i in 0..<sqlite3_column_count(stmt) {
                let name = String(cString: sqlite3_column_name(stmt, i))
                switch sqlite3_column_type(stmt, i) {
                case SQLITE_INTEGER: row[name] = Int(sqlite3_column_int64(stmt, i))
                case SQLITE_TEXT: row[name] = String(cString: sqlite3_column_text(stmt, i))
                default: row[name] = nil
                }
            }
            rows.append(row)
        }
        return rows
    }

    private func prepare(_ sql: String, _ params: [Any?]) throws -> OpaquePointer? {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            throw DBError.sql(String(cString: sqlite3_errmsg(db)))
        }
        for (i, p) in params.enumerated() {
            let idx = Int32(i + 1)
            switch p {
            case let v as Int: sqlite3_bind_int64(stmt, idx, Int64(v))
            case let v as String: sqlite3_bind_text(stmt, idx, v, -1, SQLITE_TRANSIENT)
            default: sqlite3_bind_null(stmt, idx)
            }
        }
        return stmt
    }

    // MARK: - Sync helpers

    func upsertTrack(_ t: SyncTrack) throws -> Int {
        try run("""
            INSERT INTO tracks (match_key, title, artist, album, duration_ms, isrc)
            VALUES (?,?,?,?,?,?) ON CONFLICT(match_key) DO UPDATE SET isrc = COALESCE(excluded.isrc, isrc)
            """, [t.key, t.title, t.artist, t.album, t.durationMs, t.isrc])
        let rows = try query("SELECT id FROM tracks WHERE match_key = ?", [t.key])
        return rows[0]["id"] as! Int
    }

    func snapshotKeys() throws -> Set<String> {
        Set(try query("SELECT t.match_key AS k FROM snapshot s JOIN tracks t ON t.id = s.track_id")
            .compactMap { $0["k"] as? String })
    }

    func startRun() throws -> Int { Int(try run("INSERT INTO sync_runs DEFAULT VALUES")) }

    func log(run: Int, trackId: Int, action: String, origin: String, target: String,
             status: String, detail: String? = nil) throws {
        try run("INSERT INTO change_log (run_id, track_id, action, origin, target, status, detail) VALUES (?,?,?,?,?,?,?)",
                [run, trackId, action, origin, target, status, detail])
    }

    func finish(run: Int, status: String, added: Int, removed: Int, unmatched: Int, error: String? = nil) throws {
        try self.run("""
            UPDATE sync_runs SET finished_at = strftime('%Y-%m-%dT%H:%M:%fZ','now'), status = ?,
            added_count = ?, removed_count = ?, unmatched_count = ?, error = ? WHERE id = ?
            """, [status, added, removed, unmatched, error, run])
    }

    func replaceSnapshot(keys: Set<String>, run: Int) throws {
        try exec("DELETE FROM snapshot")
        for k in keys {
            try self.run("INSERT OR IGNORE INTO snapshot (track_id, synced_run) SELECT id, ? FROM tracks WHERE match_key = ?", [run, k])
        }
    }
}
