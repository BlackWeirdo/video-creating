-- Migration 011: track structure-analysis progress per trend item
-- (NULL = never queued, 'queued' | 'running' | 'done' | 'failed').
ALTER TABLE trend_items ADD COLUMN analysis_status TEXT;
ALTER TABLE trend_items ADD COLUMN analysis_error TEXT;
UPDATE trend_items SET analysis_status = 'done' WHERE analysis_json IS NOT NULL AND analysis_json != '';
