-- Migration 027: Explicit simulation_flags_json columns for honest fallback transparency (R1).

ALTER TABLE localize_projects ADD COLUMN simulation_flags_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE podcast_projects ADD COLUMN simulation_flags_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE novel_projects ADD COLUMN simulation_flags_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE news_projects ADD COLUMN simulation_flags_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE lipsync_projects ADD COLUMN simulation_flags_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE ai_images ADD COLUMN simulation_flags_json TEXT NOT NULL DEFAULT '[]';
