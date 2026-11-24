# Phase 01 (Đợt 1): Nền móng Multi-Workspace, Hàng đợi 2 làn & `/api/v1` Core

## Context links
- Plan cha: [plan.md](plan.md)
- Đặc tả: [docs/video-creator-v2-spec.md](../../docs/video-creator-v2-spec.md)
- Phụ thuộc: Baseline `v2` (`pytest -m local` xanh với FFmpeg + Node 24 LTS)

## Mục tiêu
Xây dựng nền móng dữ liệu và lõi điều phối cho Video Creator V2 mà vẫn tương thích ngược 100% với các luồng V1 đang chạy:
1. Thêm khái niệm **`Workspace`** (đa thương hiệu / đa chủ đề) kèm bộ quy tắc riêng (`content_policy`, `approval_mode`, `default_aspect_ratio`, `style_preset`).
2. Nâng cấp **`JobWorker`** thành **Hàng đợi 2 làn song song** (`io` cho mạng/AI/tải file và `compute` cho FFmpeg/Model nặng), hỗ trợ theo dõi tiến độ `progress`/`step` và **Tạm dừng / Chạy tiếp toàn cục**.
3. Dựng lớp lõi **`/api/v1/*`** (Health, Workspaces CRUD, Jobs/Queue status & pause/resume, Log tail, SSE Events) kèm cấu hình CORS/CSRF an toàn cho giao diện Next.js cục bộ.

## Thiết kế Chi tiết

### 1. Migration SQLite `src/videocreator/migrations/015_v2_workspaces_and_lanes.sql`
- Bảng `workspaces`:
  - `id` (PK), `slug` (UNIQUE), `name`, `niche`, `content_policy` (`strict_footage` | `hybrid_remix` | `full_ai`), `approval_mode` (`single` | `bulk` | `autopilot`), `default_aspect_ratio` (`9:16` | `16:9` | `1:1`), `style_preset`, `tg_chat_id`, `tg_bot_secret_key`, `settings_json`, `archived`, `created_at`, `updated_at`.
  - Seed dòng mặc định `id = 1` (`slug = 'default'`, `content_policy = 'strict_footage'`, `approval_mode = 'single'`).
- Gắn `workspace_id INTEGER NOT NULL DEFAULT 1` (không gắn inline `REFERENCES` trên `ALTER TABLE ADD COLUMN` để tránh lỗi SQLite khi `foreign_keys = ON`) và tạo index cho:
  - `products`, `footage`, `assets`, `videos`, `accounts`, `watch_items`, `trend_items`, `suggestions`, `studio_sessions`, `jobs`.
- Nâng cấp bảng `jobs`:
  - `lane TEXT NOT NULL DEFAULT 'io' CHECK (lane IN ('io', 'compute'))`
  - `progress REAL NOT NULL DEFAULT 0.0`
  - `step TEXT NOT NULL DEFAULT ''`
  - Index `idx_jobs_lane_queue ON jobs(status, lane, priority DESC, id)`.

### 2. Cấu hình `src/videocreator/config.py`
- `WorkerConfig`: `io_concurrency: int = 4`, `compute_concurrency: int = 1` (không dùng `None` để tương thích `tomli_w`).
- `WebUIConfig`: `allowed_origins: list[str]` mặc định gồm `http://localhost:3000`, `http://127.0.0.1:3000`, `http://localhost:3200`, `http://127.0.0.1:3200`.

### 3. Module `src/videocreator/workspaces.py` & `products.py`
- CRUD đầy đủ cho Workspace (`list_workspaces`, `get_workspace`, `get_workspace_by_slug`, `require_workspace`, `create_workspace`, `update_workspace`, `archive_workspace`).
- Trạng thái Workspace đang chọn lưu tại bảng `settings` (`active_workspace_id`), mặc định `1`.
- Không cho phép lưu trữ/xóa workspace `id=1` hoặc workspace active cuối cùng.
- Cập nhật `src/videocreator/products.py` hỗ trợ lọc & tạo sản phẩm theo `workspace_id` (mặc định `1` để không ảnh hưởng code cũ).

### 4. Hàng đợi 2 làn (`src/videocreator/job_store.py`, `src/videocreator/jobs.py`)
- Phân loại làn mặc định:
  - `compute`: `render`, `analyse`, `studio`, `localize_render`, `audio_separate`, `whisper_asr`, `inpaint_subtitles`.
  - `io`: các job còn lại (`describe`, `plan`, `replan`, `scan_trends`, `trend_scan`, `analyse_trend`, `broll_suggest`, v.v.).
- `JobRegistry.register(kind, handler, *, lane=None)` cho phép đăng ký chỉ định làn rõ ràng.
- `JobWorker` tạo `io_concurrency` coroutine slot cho làn `io` và `compute_concurrency` coroutine slot cho làn `compute` chạy đồng thời trên cùng event loop; tôn trọng cờ `queue_paused` trong bảng `settings` (lưu bền vững qua restart).

### 5. Lớp `/api/v1/*` & CORS/CSRF (`src/videocreator/api/v1/`, `auth.py`, `app.py`)
- `routes_system.py`:
  - `GET /api/v1/health` (miễn auth như `/health`)
  - `GET /api/v1/logs/tail?lines=100`
  - `GET /api/v1/events` (SSE phát trạng thái hàng đợi & recent jobs; hỗ trợ `?once=1` để test tự động)
- `routes_workspaces.py`: `GET/POST /api/v1/workspaces`, `GET/PATCH/DELETE /api/v1/workspaces/{id}`, `POST /api/v1/workspaces/{id}/activate`.
- `routes_jobs.py`: `GET /api/v1/jobs`, `GET /api/v1/jobs/{id}`, `GET /api/v1/queue/status`, `POST /api/v1/queue/pause`, `POST /api/v1/queue/resume`.
- `auth.py`: Cho phép `Origin` trong `web_ui.allowed_origins` trên `/api/v1/*` khi `Sec-Fetch-Site != 'cross-site'`, giữ nguyên 100% lớp chặn CSRF đối với `cross-site`, `Origin: null` và origin lạ.

## Tiêu chí Nghiệm thu (Test thật, không mock)
- Tạo `tests/test_v2_phase01_foundation.py` kiểm chứng:
  1. Migration `015` tạo đủ cột/bảng và phân tách `products` theo `workspace_id`.
  2. Thực thi song song thật trên `JobWorker(io_concurrency=3, compute_concurrency=1)`: đo bằng timestamp/counter thực tế chứng minh nhiều job `io` chạy đồng thời với nhau và song song với 1 job `compute`, trong khi số job `compute` cùng lúc không vượt quá `1`.
  3. Tạm dừng (`pause`) và chạy tiếp (`resume`) hàng đợi hoạt động chính xác qua cả API và Python API.
  4. Kiểm tra toàn bộ `/api/v1/workspaces`, `/api/v1/jobs`, `/api/v1/queue/*`, `/api/v1/logs/tail`, `/api/v1/events?once=1`, CORS allowed origin và từ chối CSRF `403`.
- Toàn bộ `uv run pytest -m local` đạt 100%.
