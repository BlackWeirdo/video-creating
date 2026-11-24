# Phase 13: Bảng vẽ Workflow Node (`@xyflow/react`) & Giao diện Đợt 3 (`V2-WFL-01..05`)

## Mục tiêu
1. Bổ sung migration `025_v2_workflows.sql` (`workflows`, `workflow_runs`, 3 mẫu khởi tạo) và `src/videocreator/pipeline/workflow_engine.py` thực thi đồ thị DAG theo thứ tự topo (chặn chu trình), hỗ trợ `character_node`, `product_node`, `news_node`, `scene_node`, `voice_node`, `render_node`, `publish_node` + Export/Import JSON.
2. Cài `@xyflow/react` trong `web-next/`, thêm proxy `/freecut` và `/api/editor`, xây dựng 4 màn hình Next.js Đợt 3 (`/characters`, `/news`, `/editor`, `/workflows`).
3. Build lại Next.js standalone, viết `tests/test_v2_phase13_workflows_and_wave3_ui.py` và chạy toàn bộ `uv run pytest -m local -q` đạt 100%.
