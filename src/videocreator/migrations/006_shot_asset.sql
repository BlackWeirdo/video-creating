-- Migration 006: Manual subscription work tickets for B-roll (Phase 14 & Phase 18)

CREATE TABLE IF NOT EXISTS manual_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL DEFAULT 'videogen',
    prompt TEXT NOT NULL,
    ref_path TEXT,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'reminded', 'closed', 'cancelled')),
    tg_message_id INTEGER,
    result_asset_id INTEGER REFERENCES assets(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    closed_at TEXT
);
