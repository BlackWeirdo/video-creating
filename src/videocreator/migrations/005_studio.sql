-- Migration 005: Studio sessions and Remotion templates (Phase 17)

CREATE TABLE IF NOT EXISTS studio_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER REFERENCES videos(id) ON DELETE SET NULL,
    prompt TEXT NOT NULL,
    ref_item_id INTEGER REFERENCES trend_items(id) ON DELETE SET NULL,
    session_ref TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    cost_usd REAL NOT NULL DEFAULT 0.0,
    versions_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS studio_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    project_path TEXT NOT NULL,
    props_schema_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
