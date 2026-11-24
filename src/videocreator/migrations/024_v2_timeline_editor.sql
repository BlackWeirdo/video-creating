-- Migration 024: FreeCut (MIT) Embedded Timeline Editor & Multi-Track Composer (V2-EDT-01..05).

CREATE TABLE IF NOT EXISTS editor_projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    source_video_id INTEGER,
    aspect_ratio TEXT NOT NULL DEFAULT '9:16',
    fps INTEGER NOT NULL DEFAULT 30,
    tracks_json TEXT NOT NULL DEFAULT '{"video_clips":[],"audio_clips":[],"subtitles":[]}',
    output_video_id INTEGER,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'rendering', 'completed', 'failed')),
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_editor_projects_workspace
    ON editor_projects(workspace_id, id DESC);
