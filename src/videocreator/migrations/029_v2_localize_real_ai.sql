-- Migration 029: Real AI Localize/Reup columns — Whisper size, translation style, speaker diarization, OCR cues & voice cloning safeguards (R3).

ALTER TABLE localize_projects ADD COLUMN whisper_size TEXT NOT NULL DEFAULT 'small';
ALTER TABLE localize_projects ADD COLUMN translation_style TEXT NOT NULL DEFAULT 'natural_tiktok';
ALTER TABLE localize_projects ADD COLUMN clone_source_voice INTEGER NOT NULL DEFAULT 0;
ALTER TABLE localize_projects ADD COLUMN clone_consent_confirmed INTEGER NOT NULL DEFAULT 0;
ALTER TABLE localize_projects ADD COLUMN speaker_config_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE localize_projects ADD COLUMN ocr_cues_json TEXT NOT NULL DEFAULT '[]';
