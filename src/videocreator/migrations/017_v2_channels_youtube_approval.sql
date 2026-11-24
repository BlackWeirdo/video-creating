-- pragma: foreign_keys=off
-- Migration 017: Multi-channel accounts (add YouTube platform, approval_mode, autopilot_min_score, channel_group).
-- `db.migrate()` disables foreign_keys outside the transaction and verifies PRAGMA foreign_key_check after COMMIT.

DROP TABLE IF EXISTS accounts_new;
CREATE TABLE accounts_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL CHECK (platform IN ('facebook', 'instagram', 'threads', 'tiktok', 'youtube')),
    external_id TEXT NOT NULL,
    name TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT 'vi' CHECK (lang IN ('vi', 'en')),
    slots_json TEXT,
    secret_key TEXT NOT NULL,
    token_expires_at TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    workspace_id INTEGER NOT NULL DEFAULT 1,
    approval_mode TEXT NOT NULL DEFAULT 'inherit' CHECK (approval_mode IN ('inherit', 'single', 'bulk', 'autopilot')),
    autopilot_min_score REAL NOT NULL DEFAULT 8.0,
    channel_group TEXT NOT NULL DEFAULT '',
    UNIQUE (platform, external_id)
);

INSERT INTO accounts_new (
    id, platform, external_id, name, lang, slots_json,
    secret_key, token_expires_at, enabled, created_at, workspace_id
)
SELECT
    id, platform, external_id, name, lang, slots_json,
    secret_key, token_expires_at, enabled, created_at, workspace_id
FROM accounts;

DROP TABLE accounts;
ALTER TABLE accounts_new RENAME TO accounts;
CREATE INDEX IF NOT EXISTS idx_accounts_workspace_id ON accounts(workspace_id);
