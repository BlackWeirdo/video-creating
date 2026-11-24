-- Migration 025: Visual Workflow Node Engine (`@xyflow/react`) & starter DAG templates (V2-WFL-01..05).

CREATE TABLE IF NOT EXISTS workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    nodes_json TEXT NOT NULL DEFAULT '[]',
    edges_json TEXT NOT NULL DEFAULT '[]',
    is_template INTEGER NOT NULL DEFAULT 0,
    last_status TEXT NOT NULL DEFAULT 'idle',
    last_video_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_workflows_workspace
    ON workflows(workspace_id, is_template DESC, id DESC);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workflow_id INTEGER NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    workspace_id INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    node_outputs_json TEXT NOT NULL DEFAULT '{}',
    video_id INTEGER,
    error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

INSERT OR IGNORE INTO workflows (id, workspace_id, name, description, nodes_json, edges_json, is_template)
VALUES
(
    1,
    1,
    'Mẫu 1: Nhân vật → Cảnh → Giọng → Render',
    'Luồng nối Nhân vật cố định sang Cảnh quay, Giọng đọc và Render MP4.',
    '[{"id":"n1","type":"character_node","position":{"x":40,"y":120},"data":{"label":"Nhân vật MC","node_kind":"character_node","name":"MC Studio","appearance_prompt":"Áo dài thanh lịch"}},{"id":"n2","type":"scene_node","position":{"x":300,"y":120},"data":{"label":"Ghép Cảnh & Kịch bản","node_kind":"scene_node","prompt":"Giới thiệu phong cách tinh tế mỗi ngày"}},{"id":"n3","type":"voice_node","position":{"x":560,"y":120},"data":{"label":"Giọng đọc TTS","node_kind":"voice_node","lang":"vi"}},{"id":"n4","type":"render_node","position":{"x":820,"y":120},"data":{"label":"Xuất Master MP4","node_kind":"render_node","style_preset":"tiktok_karaoke","aspect_ratio":"9:16"}}]',
    '[{"id":"e1-2","source":"n1","target":"n2"},{"id":"e2-3","source":"n2","target":"n3"},{"id":"e3-4","source":"n3","target":"n4"}]',
    1
),
(
    2,
    1,
    'Mẫu 2: Tin tức → Cảnh → Giọng → Render',
    'Trích xuất bài báo/text, tóm tắt giữ số liệu và render bản tin dọc.',
    '[{"id":"n1","type":"news_node","position":{"x":40,"y":120},"data":{"label":"Nguồn Tin tức","node_kind":"news_node","raw_text":"Thị trường bạc 2026 tăng trưởng 85% nhờ thiết kế tối giản."}},{"id":"n2","type":"scene_node","position":{"x":300,"y":120},"data":{"label":"Cảnh Tin tức","node_kind":"scene_node"}},{"id":"n3","type":"voice_node","position":{"x":560,"y":120},"data":{"label":"Giọng Phát thanh","node_kind":"voice_node","lang":"vi"}},{"id":"n4","type":"render_node","position":{"x":820,"y":120},"data":{"label":"Render Bản tin","node_kind":"render_node","style_preset":"box_highlight","aspect_ratio":"9:16"}}]',
    '[{"id":"e1-2","source":"n1","target":"n2"},{"id":"e2-3","source":"n2","target":"n3"},{"id":"e3-4","source":"n3","target":"n4"}]',
    1
),
(
    3,
    1,
    'Mẫu 3: Sản phẩm → Cảnh → Giọng → Render → Phát hành',
    'Dùng dữ kiện sản phẩm thật trong Workspace + shot thật để xuất video và gói đăng bài.',
    '[{"id":"n1","type":"product_node","position":{"x":40,"y":120},"data":{"label":"Dữ kiện Sản phẩm","node_kind":"product_node"}},{"id":"n2","type":"scene_node","position":{"x":280,"y":120},"data":{"label":"Cảnh Sản phẩm","node_kind":"scene_node"}},{"id":"n3","type":"voice_node","position":{"x":520,"y":120},"data":{"label":"Giọng Review","node_kind":"voice_node","lang":"vi"}},{"id":"n4","type":"render_node","position":{"x":760,"y":120},"data":{"label":"Render QC","node_kind":"render_node","style_preset":"tiktok_karaoke","aspect_ratio":"9:16"}},{"id":"n5","type":"publish_node","position":{"x":1000,"y":120},"data":{"label":"Gói Đăng Bài / Autopilot","node_kind":"publish_node"}}]',
    '[{"id":"e1-2","source":"n1","target":"n2"},{"id":"e2-3","source":"n2","target":"n3"},{"id":"e3-4","source":"n3","target":"n4"},{"id":"e4-5","source":"n4","target":"n5"}]',
    1
);
