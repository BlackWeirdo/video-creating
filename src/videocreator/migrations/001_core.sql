-- 001_core.sql: Core schema for Video Creator (Phase 02)

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    material TEXT NOT NULL DEFAULT '',
    facts_json TEXT NOT NULL DEFAULT '{}',
    hidden INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS footage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL,
    sha256 TEXT NOT NULL UNIQUE,
    duration_s REAL NOT NULL DEFAULT 0.0,
    width INTEGER NOT NULL DEFAULT 0,
    height INTEGER NOT NULL DEFAULT 0,
    orientation TEXT NOT NULL DEFAULT 'portrait',
    crop_json TEXT,
    product_ids_json TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'imported',
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL CHECK (kind IN ('music', 'sfx', 'broll')),
    path TEXT NOT NULL,
    duration_s REAL NOT NULL DEFAULT 0.0,
    meta_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS shots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    footage_id INTEGER REFERENCES footage(id) ON DELETE CASCADE,
    asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
    idx INTEGER NOT NULL DEFAULT 0,
    start_s REAL NOT NULL,
    end_s REAL NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    has_product INTEGER NOT NULL DEFAULT 1,
    product_ids_json TEXT NOT NULL DEFAULT '[]',
    quality INTEGER NOT NULL DEFAULT 3,
    thumb_path TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_shots_footage_id ON shots(footage_id);

CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    footage_id INTEGER REFERENCES footage(id) ON DELETE SET NULL,
    product_ids_json TEXT NOT NULL DEFAULT '[]',
    engine TEXT NOT NULL DEFAULT 'ffmpeg' CHECK (engine IN ('ffmpeg', 'mpt', 'studio')),
    status TEXT NOT NULL DEFAULT 'planned',
    plan_json TEXT NOT NULL DEFAULT '{}',
    voice_lang TEXT NOT NULL DEFAULT 'none' CHECK (voice_lang IN ('none', 'vi', 'en')),
    caption_lang TEXT NOT NULL DEFAULT 'vi' CHECK (caption_lang IN ('vi', 'en')),
    captions_json TEXT NOT NULL DEFAULT '{}',
    target_accounts_json TEXT NOT NULL DEFAULT '[]',
    output_path TEXT,
    cover_path TEXT,
    duration_s REAL,
    preflight_json TEXT NOT NULL DEFAULT '{}',
    unsupported_claims_json TEXT NOT NULL DEFAULT '[]',
    quality_score REAL,
    quality_notes TEXT,
    auto_retry_count INTEGER NOT NULL DEFAULT 0,
    redo_count INTEGER NOT NULL DEFAULT 0,
    supersedes_id INTEGER REFERENCES videos(id) ON DELETE SET NULL,
    suggestion_id INTEGER,
    auto_render INTEGER NOT NULL DEFAULT 0,
    tg_message_id INTEGER,
    error TEXT,
    reject_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    approved_at TEXT,
    approved_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_videos_status ON videos(status);
CREATE INDEX IF NOT EXISTS idx_videos_footage_id ON videos(footage_id);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL CHECK (platform IN ('facebook', 'instagram', 'threads', 'tiktok')),
    external_id TEXT NOT NULL,
    name TEXT NOT NULL,
    lang TEXT NOT NULL DEFAULT 'vi' CHECK (lang IN ('vi', 'en')),
    slots_json TEXT,
    secret_key TEXT NOT NULL,
    token_expires_at TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (platform, external_id)
);

CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'scheduled',
    scheduled_at TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT,
    remote_container_id TEXT,
    external_post_id TEXT,
    permalink TEXT,
    error TEXT,
    posted_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (video_id, account_id)
);

CREATE INDEX IF NOT EXISTS idx_posts_status_scheduled ON posts(status, scheduled_at);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    ref_id INTEGER,
    status TEXT NOT NULL DEFAULT 'queued',
    error TEXT,
    log_tail TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    started_at TEXT,
    finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at);

CREATE TABLE IF NOT EXISTS ai_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d', 'now')),
    role TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    route TEXT NOT NULL DEFAULT 'api' CHECK (route IN ('subscription', 'api', 'manual')),
    kind TEXT NOT NULL,
    input_units INTEGER NOT NULL DEFAULT 0,
    output_units INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    ref TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_ai_usage_day ON ai_usage(day);

CREATE TABLE IF NOT EXISTS provider_state (
    name TEXT PRIMARY KEY,
    resting_until TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id INTEGER,
    detail TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
