-- Jobs someone is waiting for (plan, render, replan, studio) run before background work
-- such as trend analysis. Existing rows get priority 0 (background).
ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(status, priority DESC, id);
