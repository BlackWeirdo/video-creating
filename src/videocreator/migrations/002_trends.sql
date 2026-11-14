-- Migration 002: Trend watch items, fetched trend items, and suggestions (Phase 12)

CREATE TABLE IF NOT EXISTS watch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK (source IN ('youtube', 'ig_discovery', 'ad_library', 'ig_hashtag')),
    kind TEXT NOT NULL CHECK (kind IN ('account', 'hashtag', 'keyword', 'page')),
    value TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (source, kind, value)
);

CREATE TABLE IF NOT EXISTS trend_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    url TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    caption TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    score REAL NOT NULL DEFAULT 0.0,
    analysis_json TEXT,
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_trend_items_source_score ON trend_items(source, score DESC);

CREATE TABLE IF NOT EXISTS suggestions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trend_item_id INTEGER REFERENCES trend_items(id) ON DELETE SET NULL,
    text TEXT NOT NULL,
    formula_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'new' CHECK (status IN ('new', 'sent', 'accepted', 'dismissed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);
