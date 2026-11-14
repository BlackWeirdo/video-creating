-- Migration 009: remember the R2 object staged for a video so it is uploaded once and deleted later (FR-PST-05)

ALTER TABLE videos ADD COLUMN r2_key TEXT;
ALTER TABLE videos ADD COLUMN r2_url TEXT;
