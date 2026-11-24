-- Migration 030: Consented Channel Voices, Character Cutout Flags & Podcast Host Avatars (Stage R4).

CREATE TABLE IF NOT EXISTS channel_voices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    character_id INTEGER REFERENCES characters(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    speaker_name TEXT NOT NULL,
    consent_confirmed INTEGER NOT NULL CHECK (consent_confirmed = 1),
    ref_audio_path TEXT NOT NULL,
    duration_s REAL NOT NULL DEFAULT 0.0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_channel_voices_workspace
    ON channel_voices(workspace_id, id DESC);

ALTER TABLE characters ADD COLUMN cutout_simulation_flags_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE podcast_projects ADD COLUMN host_a_avatar_path TEXT NOT NULL DEFAULT '';
ALTER TABLE podcast_projects ADD COLUMN host_b_avatar_path TEXT NOT NULL DEFAULT '';
