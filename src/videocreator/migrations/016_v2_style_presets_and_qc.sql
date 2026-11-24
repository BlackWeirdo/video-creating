-- Migration 016: Video Style Presets, Multi-Aspect Ratio, QC & Render Cache (V2 Wave 1 Phase 02)

CREATE TABLE IF NOT EXISTS style_presets (
    id TEXT PRIMARY KEY,
    workspace_id INTEGER,
    name TEXT NOT NULL,
    subtitle_style TEXT NOT NULL DEFAULT 'karaoke_highlight'
        CHECK (subtitle_style IN ('karaoke_highlight', 'tiktok_pop', 'box_highlight', 'neon_glow', 'minimal_bottom', 'bilingual')),
    font_name TEXT NOT NULL DEFAULT 'Be Vietnam Pro',
    font_size INTEGER NOT NULL DEFAULT 58,
    primary_color TEXT NOT NULL DEFAULT '#FFFFFF',
    highlight_color TEXT NOT NULL DEFAULT '#FFE082',
    outline_color TEXT NOT NULL DEFAULT '#141414',
    box_color TEXT NOT NULL DEFAULT '#99121216',
    position TEXT NOT NULL DEFAULT 'bottom' CHECK (position IN ('bottom', 'center', 'top')),
    ducking_enabled INTEGER NOT NULL DEFAULT 1,
    music_volume REAL NOT NULL DEFAULT 0.22,
    sfx_transition_asset_id INTEGER,
    intro_text TEXT NOT NULL DEFAULT '',
    outro_text TEXT NOT NULL DEFAULT '',
    motion_preset TEXT NOT NULL DEFAULT 'none' CHECK (motion_preset IN ('none', 'subtle_zoom')),
    is_builtin INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

INSERT OR IGNORE INTO style_presets (
    id, workspace_id, name, subtitle_style, font_name, font_size,
    primary_color, highlight_color, outline_color, box_color,
    position, ducking_enabled, music_volume, motion_preset, is_builtin
) VALUES
    ('tiktok_karaoke', NULL, 'TikTok Karaoke Tô Chữ', 'karaoke_highlight', 'Be Vietnam Pro', 58, '#FFFFFF', '#FFE082', '#141414', '#99121216', 'bottom', 1, 0.22, 'none', 1),
    ('tiktok_pop', NULL, 'TikTok Pop Nhịp Nhanh', 'tiktok_pop', 'Be Vietnam Pro', 62, '#FFFFFF', '#FF6B6B', '#141414', '#99121216', 'bottom', 1, 0.24, 'none', 1),
    ('box_highlight', NULL, 'Hộp Nền Tương Phản', 'box_highlight', 'Be Vietnam Pro', 54, '#FFFFFF', '#FFE082', '#141414', '#CC10141C', 'bottom', 1, 0.20, 'none', 1),
    ('neon_glow', NULL, 'Neon Phát Sáng', 'neon_glow', 'Be Vietnam Pro', 58, '#FFFFFF', '#00E5FF', '#0A192F', '#99121216', 'center', 1, 0.22, 'none', 1),
    ('minimal_bottom', NULL, 'Tối Giản Tinh Tế', 'minimal_bottom', 'Be Vietnam Pro', 50, '#F5F5F5', '#FFFFFF', '#1E1E1E', '#66000000', 'bottom', 1, 0.18, 'none', 1),
    ('bilingual_sub', NULL, 'Song Ngữ Việt - Anh', 'bilingual', 'Be Vietnam Pro', 52, '#FFFFFF', '#FFE082', '#141414', '#99121216', 'bottom', 1, 0.20, 'none', 1);

ALTER TABLE videos ADD COLUMN style_preset TEXT NOT NULL DEFAULT 'tiktok_karaoke';
ALTER TABLE videos ADD COLUMN aspect_ratio TEXT NOT NULL DEFAULT '9:16';
ALTER TABLE videos ADD COLUMN qc_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE videos ADD COLUMN render_cache_json TEXT NOT NULL DEFAULT '{}';
