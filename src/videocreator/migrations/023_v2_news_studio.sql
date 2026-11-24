-- Migration 023: News / Article-to-Video Studio (V2-NWS-01..04).

CREATE TABLE IF NOT EXISTS news_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('url', 'rss', 'raw_text')),
    source_url TEXT NOT NULL DEFAULT '',
    raw_text TEXT NOT NULL DEFAULT '',
    facts_json TEXT NOT NULL DEFAULT '{}',
    script_json TEXT NOT NULL DEFAULT '[]',
    character_id INTEGER,
    style_preset TEXT NOT NULL DEFAULT 'tiktok_karaoke',
    aspect_ratio TEXT NOT NULL DEFAULT '9:16',
    target_lang TEXT NOT NULL DEFAULT 'vi',
    voice_id TEXT NOT NULL DEFAULT 'vi-VN-HoaiMyNeural',
    output_video_id INTEGER,
    publish_pack_path TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'summarized', 'rendering', 'completed', 'failed')),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_news_projects_workspace
    ON news_projects(workspace_id, id DESC);
