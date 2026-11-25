-- Track crash/execution attempts on jobs so repeatedly crashing jobs fail cleanly instead of looping on startup.
ALTER TABLE jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0;
