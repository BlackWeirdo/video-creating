-- Migration 026: Specialized Studios (Novel-to-Video, Podcast Spectrum, Lip-sync AI).

CREATE TABLE IF NOT EXISTS novel_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    source_text TEXT NOT NULL DEFAULT '',
    character_id INTEGER,
    style_preset TEXT NOT NULL DEFAULT 'tiktok_karaoke',
    aspect_ratio TEXT NOT NULL DEFAULT '9:16',
    target_lang TEXT NOT NULL DEFAULT 'vi',
    voice_id TEXT NOT NULL DEFAULT 'vi-VN-HoaiMyNeural',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'rendering', 'partial', 'completed', 'failed')),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS novel_chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES novel_projects(id) ON DELETE CASCADE,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    chapter_index INTEGER NOT NULL,
    title TEXT NOT NULL,
    body_text TEXT NOT NULL DEFAULT '',
    word_count INTEGER NOT NULL DEFAULT 0,
    video_id INTEGER,
    output_path TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'rendering', 'ready', 'failed')),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE(project_id, chapter_index)
);

CREATE TABLE IF NOT EXISTS podcast_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    host_a_name TEXT NOT NULL DEFAULT 'Host A',
    host_b_name TEXT NOT NULL DEFAULT 'Host B',
    host_a_voice TEXT NOT NULL DEFAULT 'vi-VN-HoaiMyNeural',
    host_b_voice TEXT NOT NULL DEFAULT 'vi-VN-NamMinhNeural',
    dialogue_json TEXT NOT NULL DEFAULT '[]',
    audio_source_path TEXT NOT NULL DEFAULT '',
    aspect_ratio TEXT NOT NULL DEFAULT '16:9',
    waveform_style TEXT NOT NULL DEFAULT 'cline' CHECK (waveform_style IN ('bars', 'line', 'p2p', 'cline', 'spectrum')),
    accent_color TEXT NOT NULL DEFAULT '#38bdf8',
    style_preset TEXT NOT NULL DEFAULT 'minimal_bottom',
    target_lang TEXT NOT NULL DEFAULT 'vi',
    output_video_id INTEGER,
    output_path TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'rendering', 'completed', 'failed')),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS lipsync_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    character_id INTEGER,
    portrait_path TEXT NOT NULL DEFAULT '',
    script_text TEXT NOT NULL DEFAULT '',
    audio_path TEXT NOT NULL DEFAULT '',
    aspect_ratio TEXT NOT NULL DEFAULT '9:16',
    style_preset TEXT NOT NULL DEFAULT 'tiktok_karaoke',
    target_lang TEXT NOT NULL DEFAULT 'vi',
    voice_id TEXT NOT NULL DEFAULT 'vi-VN-HoaiMyNeural',
    engine_used TEXT NOT NULL DEFAULT 'ffmpeg_viseme',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    output_video_id INTEGER,
    output_path TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'rendering', 'completed', 'failed')),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_novel_projects_workspace
    ON novel_projects(workspace_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_novel_chapters_project
    ON novel_chapters(project_id, chapter_index);
CREATE INDEX IF NOT EXISTS idx_podcast_projects_workspace
    ON podcast_projects(workspace_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_lipsync_projects_workspace
    ON lipsync_projects(workspace_id, id DESC);
