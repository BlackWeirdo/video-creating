-- Migration 007: Post performance metrics at 24h, 72h, and 7d checkpoints (Phase 15)

CREATE TABLE IF NOT EXISTS post_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    checkpoint TEXT NOT NULL CHECK (checkpoint IN ('24h', '72h', '7d')),
    fetched_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    views INTEGER,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    UNIQUE (post_id, checkpoint)
);
