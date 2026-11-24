-- Migration 020: Batch & Product A/B Studio with per-item checkpoint resume (V2-BAT-01..05).

CREATE TABLE IF NOT EXISTS batch_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    title TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('prompts', 'products', 'trends')),
    ab_count INTEGER NOT NULL DEFAULT 1 CHECK (ab_count BETWEEN 1 AND 3),
    style_presets_json TEXT NOT NULL DEFAULT '["tiktok_karaoke"]',
    aspect_ratio TEXT NOT NULL DEFAULT '9:16',
    target_lang TEXT NOT NULL DEFAULT 'vi',
    target_accounts_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'completed', 'partial_failed', 'failed')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_batch_runs_workspace
    ON batch_runs(workspace_id, id DESC);

CREATE TABLE IF NOT EXISTS batch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batch_runs(id) ON DELETE CASCADE,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    item_index INTEGER NOT NULL DEFAULT 0,
    variant_label TEXT NOT NULL DEFAULT 'A' CHECK (variant_label IN ('A', 'B', 'C')),
    source_ref_json TEXT NOT NULL DEFAULT '{}',
    style_preset TEXT NOT NULL DEFAULT 'tiktok_karaoke',
    hook_angle TEXT NOT NULL DEFAULT 'curiosity_problem',
    step TEXT NOT NULL DEFAULT 'queued' CHECK (step IN ('queued', 'planned', 'rendered', 'completed', 'failed')),
    video_id INTEGER,
    error TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_batch_items_batch
    ON batch_items(batch_id, item_index, variant_label);
