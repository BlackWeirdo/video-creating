-- Migration 021: Channel Autopilot rules and execution audit history (V2-AUT-01..04).

CREATE TABLE IF NOT EXISTS autopilot_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    source_mode TEXT NOT NULL CHECK (source_mode IN ('suggestions', 'products_ab', 'rss_feed', 'localize_trends')),
    feed_url TEXT NOT NULL DEFAULT '',
    target_account_ids_json TEXT NOT NULL DEFAULT '[]',
    daily_cap INTEGER NOT NULL DEFAULT 3 CHECK (daily_cap BETWEEN 1 AND 20),
    min_quality_score REAL NOT NULL DEFAULT 8.0,
    style_preset TEXT NOT NULL DEFAULT 'tiktok_karaoke',
    aspect_ratio TEXT NOT NULL DEFAULT '9:16',
    interval_minutes INTEGER NOT NULL DEFAULT 60,
    last_run_at TEXT,
    last_status TEXT NOT NULL DEFAULT 'idle',
    last_error TEXT,
    total_generated INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_autopilot_rules_workspace
    ON autopilot_rules(workspace_id, enabled, id DESC);

CREATE TABLE IF NOT EXISTS autopilot_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_id INTEGER NOT NULL REFERENCES autopilot_rules(id) ON DELETE CASCADE,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    source_key TEXT NOT NULL DEFAULT '',
    source_summary TEXT NOT NULL DEFAULT '',
    video_id INTEGER,
    batch_id INTEGER,
    localize_id INTEGER,
    status TEXT NOT NULL DEFAULT 'completed',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_autopilot_runs_rule_date
    ON autopilot_runs(rule_id, created_at DESC);
