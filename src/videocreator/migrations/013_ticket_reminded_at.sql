-- Add reminded_at timestamp to manual_tickets so stale ticket cancellation waits for a reminder grace window.
ALTER TABLE manual_tickets ADD COLUMN reminded_at TEXT;
