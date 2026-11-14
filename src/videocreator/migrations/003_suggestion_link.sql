-- Migration 003: Reference videos downloaded for internal structure breakdown (Phase 13, BR-REF-03: no FK to shots)

CREATE TABLE IF NOT EXISTS reference_videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trend_item_id INTEGER NOT NULL REFERENCES trend_items(id) ON DELETE CASCADE,
    path TEXT,
    rea_dir TEXT,
    downloaded_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    deleted_at TEXT,
    UNIQUE (trend_item_id)
);
