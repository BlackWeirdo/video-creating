-- Migration 019: Localize, Reup, Hybrid Remix & Internationalize Studio (V2-LOC-01..06).

ALTER TABLE videos ADD COLUMN target_lang TEXT NOT NULL DEFAULT 'vi';

CREATE TABLE IF NOT EXISTS localize_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('reup_vi', 'hybrid_remix', 'intl_export')),
    source_url TEXT NOT NULL DEFAULT '',
    source_media_path TEXT NOT NULL DEFAULT '',
    source_trend_id INTEGER,
    source_video_id INTEGER,
    source_lang TEXT NOT NULL DEFAULT 'auto',
    target_lang TEXT NOT NULL DEFAULT 'vi',
    hardsub_mode TEXT NOT NULL DEFAULT 'blur_bar' CHECK (hardsub_mode IN ('none', 'blur_bar', 'crop_frame', 'ocr_inpaint')),
    hardsub_box_json TEXT NOT NULL DEFAULT '{"x":0.06,"y":0.74,"w":0.88,"h":0.16}',
    anti_dup_json TEXT NOT NULL DEFAULT '{"mirror":false,"zoom":1.04,"color_eq":true}',
    vocal_track_path TEXT NOT NULL DEFAULT '',
    bgm_track_path TEXT NOT NULL DEFAULT '',
    segments_json TEXT NOT NULL DEFAULT '[]',
    product_ids_json TEXT NOT NULL DEFAULT '[]',
    style_preset TEXT NOT NULL DEFAULT 'tiktok_karaoke',
    aspect_ratio TEXT NOT NULL DEFAULT '9:16',
    voice_id TEXT NOT NULL DEFAULT 'vi-VN-HoaiMyNeural',
    output_video_id INTEGER,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'extracting', 'ready_to_edit', 'rendering', 'completed', 'failed')),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_localize_projects_workspace
    ON localize_projects(workspace_id, id DESC);
