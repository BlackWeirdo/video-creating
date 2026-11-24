-- Migration 022: Characters & AI Image Studio with seed locking & cutout PNGs (V2-CHR-01..05).

CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    appearance_prompt TEXT NOT NULL DEFAULT '',
    negative_prompt TEXT NOT NULL DEFAULT '',
    seed INTEGER NOT NULL DEFAULT 42,
    voice_id TEXT NOT NULL DEFAULT 'vi-VN-HoaiMyNeural',
    ref_image_path TEXT NOT NULL DEFAULT '',
    cutout_image_path TEXT NOT NULL DEFAULT '',
    style_tags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_characters_workspace
    ON characters(workspace_id, id DESC);

CREATE TABLE IF NOT EXISTS ai_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    character_id INTEGER REFERENCES characters(id) ON DELETE SET NULL,
    prompt TEXT NOT NULL,
    seed INTEGER NOT NULL DEFAULT 42,
    aspect_ratio TEXT NOT NULL DEFAULT '9:16',
    is_product_shot INTEGER NOT NULL DEFAULT 0,
    image_path TEXT NOT NULL DEFAULT '',
    cutout_path TEXT NOT NULL DEFAULT '',
    motion_shot_id INTEGER,
    provider TEXT NOT NULL DEFAULT 'local_card',
    status TEXT NOT NULL DEFAULT 'ready',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_ai_images_workspace
    ON ai_images(workspace_id, id DESC);
