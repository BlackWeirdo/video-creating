-- Muse Gateway non-blocking multi-lane task queue & multi-scene storyboards (Phase 2.4).
CREATE TABLE IF NOT EXISTS muse_tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL DEFAULT 1 REFERENCES workspaces(id),
  kind TEXT NOT NULL CHECK (kind IN ('video', 'image', 'audio', 'chat')),
  model TEXT NOT NULL,
  purpose TEXT NOT NULL DEFAULT 'studio',
  ref_type TEXT,
  ref_id INTEGER,
  prompt TEXT NOT NULL,
  params_json TEXT NOT NULL DEFAULT '{}',
  refs_json TEXT NOT NULL DEFAULT '[]',
  thread_url TEXT,
  account_id TEXT,
  parent_task_id INTEGER REFERENCES muse_tasks(id),
  priority INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'submitted', 'importing', 'succeeded', 'failed', 'cancelled', 'waiting_quota')),
  attempt INTEGER NOT NULL DEFAULT 0,
  gateway_task_id TEXT,
  idempotency_key TEXT,
  partial INTEGER NOT NULL DEFAULT 0,
  duration_sec REAL,
  result_text TEXT,
  local_path TEXT,
  asset_id INTEGER,
  shot_id INTEGER,
  ai_image_id INTEGER,
  error TEXT,
  retry_after TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  submitted_at TEXT,
  finished_at TEXT,
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_muse_tasks_status ON muse_tasks(status, priority DESC, id);
CREATE INDEX IF NOT EXISTS idx_muse_tasks_ref ON muse_tasks(ref_type, ref_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_muse_tasks_gw ON muse_tasks(gateway_task_id) WHERE gateway_task_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS muse_storyboards (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  workspace_id INTEGER NOT NULL DEFAULT 1 REFERENCES workspaces(id),
  title TEXT NOT NULL,
  ratio TEXT NOT NULL DEFAULT '9:16',
  model TEXT NOT NULL DEFAULT 'muse-video',
  continuity INTEGER NOT NULL DEFAULT 1,
  narration_json TEXT NOT NULL DEFAULT '{}',
  style_preset TEXT NOT NULL DEFAULT 'tiktok_karaoke',
  status TEXT NOT NULL DEFAULT 'draft'
    CHECK (status IN ('draft', 'generating', 'assembling', 'completed', 'partial', 'failed', 'cancelled')),
  output_video_id INTEGER REFERENCES videos(id),
  simulation_flags_json TEXT NOT NULL DEFAULT '[]',
  error TEXT,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS muse_storyboard_segments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  storyboard_id INTEGER NOT NULL REFERENCES muse_storyboards(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL,
  prompt TEXT NOT NULL,
  duration_sec INTEGER NOT NULL DEFAULT 8,
  caption TEXT NOT NULL DEFAULT '',
  refs_json TEXT NOT NULL DEFAULT '[]',
  muse_task_id INTEGER REFERENCES muse_tasks(id),
  status TEXT NOT NULL DEFAULT 'pending',
  UNIQUE(storyboard_id, idx)
);
