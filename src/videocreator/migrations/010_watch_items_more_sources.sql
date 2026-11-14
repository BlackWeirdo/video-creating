-- Migration 010: allow 'tiktok' and 'facebook' as watch_items sources.
-- SQLite cannot alter a CHECK constraint, so the table is rebuilt inside one transaction.
-- No other table references watch_items. Re-running after a crash between COMMIT and
-- PRAGMA user_version is safe: the new table is copied from the renamed one again.
BEGIN;
DROP TABLE IF EXISTS watch_items_new;
CREATE TABLE watch_items_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK (source IN ('youtube', 'ig_discovery', 'ad_library', 'ig_hashtag', 'tiktok', 'facebook')),
    kind TEXT NOT NULL CHECK (kind IN ('account', 'hashtag', 'keyword', 'page')),
    value TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (source, kind, value)
);
INSERT INTO watch_items_new (id, source, kind, value, enabled, created_at)
SELECT id, source, kind, value, enabled, created_at FROM watch_items;
DROP TABLE watch_items;
ALTER TABLE watch_items_new RENAME TO watch_items;
COMMIT;
