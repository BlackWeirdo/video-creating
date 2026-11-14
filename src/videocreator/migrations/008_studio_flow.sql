-- Migration 008: Studio runs as a queued job with a script confirmation stop and audio options (Phase 17)

ALTER TABLE studio_sessions ADD COLUMN options_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE studio_sessions ADD COLUMN pending_prompt TEXT;
ALTER TABLE studio_sessions ADD COLUMN error TEXT;
