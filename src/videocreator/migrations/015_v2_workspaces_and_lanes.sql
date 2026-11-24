-- Migration 015: Multi-workspace isolation and dual-lane job queue (V2 Wave 1 Phase 01)

CREATE TABLE IF NOT EXISTS workspaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    niche TEXT NOT NULL DEFAULT 'general',
    content_policy TEXT NOT NULL DEFAULT 'strict_footage' CHECK (content_policy IN ('strict_footage', 'hybrid_remix', 'full_ai')),
    approval_mode TEXT NOT NULL DEFAULT 'single' CHECK (approval_mode IN ('single', 'bulk', 'autopilot')),
    default_aspect_ratio TEXT NOT NULL DEFAULT '9:16' CHECK (default_aspect_ratio IN ('9:16', '16:9', '1:1')),
    style_preset TEXT NOT NULL DEFAULT 'tiktok_karaoke',
    tg_chat_id TEXT NOT NULL DEFAULT '',
    tg_bot_secret_key TEXT NOT NULL DEFAULT '',
    settings_json TEXT NOT NULL DEFAULT '{}',
    archived INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

INSERT OR IGNORE INTO workspaces (
    id, slug, name, niche, content_policy, approval_mode, default_aspect_ratio, style_preset
) VALUES (
    1, 'default', 'Workspace Mặc định', 'general', 'strict_footage', 'single', '9:16', 'tiktok_karaoke'
);

-- NOTE: SQLite refuses `ALTER TABLE ... ADD COLUMN ... REFERENCES ... DEFAULT 1` under
-- `PRAGMA foreign_keys = ON`. Workspace foreign-key integrity is enforced in Python (`workspaces.require_workspace`).
ALTER TABLE products ADD COLUMN workspace_id INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_products_workspace_id ON products(workspace_id);

ALTER TABLE footage ADD COLUMN workspace_id INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_footage_workspace_id ON footage(workspace_id);

ALTER TABLE assets ADD COLUMN workspace_id INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_assets_workspace_id ON assets(workspace_id);

ALTER TABLE videos ADD COLUMN workspace_id INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_videos_workspace_id ON videos(workspace_id);

ALTER TABLE accounts ADD COLUMN workspace_id INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_accounts_workspace_id ON accounts(workspace_id);

ALTER TABLE watch_items ADD COLUMN workspace_id INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_watch_items_workspace_id ON watch_items(workspace_id);

ALTER TABLE trend_items ADD COLUMN workspace_id INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_trend_items_workspace_id ON trend_items(workspace_id);

ALTER TABLE suggestions ADD COLUMN workspace_id INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_suggestions_workspace_id ON suggestions(workspace_id);

ALTER TABLE studio_sessions ADD COLUMN workspace_id INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_studio_sessions_workspace_id ON studio_sessions(workspace_id);

ALTER TABLE jobs ADD COLUMN workspace_id INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS idx_jobs_workspace_id ON jobs(workspace_id);

ALTER TABLE jobs ADD COLUMN lane TEXT NOT NULL DEFAULT 'io' CHECK (lane IN ('io', 'compute'));
ALTER TABLE jobs ADD COLUMN progress REAL NOT NULL DEFAULT 0.0;
ALTER TABLE jobs ADD COLUMN step TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_jobs_lane_queue ON jobs(status, lane, priority DESC, id);
