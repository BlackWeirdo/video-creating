# Kiểm kê Tầng Router V1 (`routes_*.py`) & Chiến lược Cô lập ở Wave 5

Bảng kiểm kê dưới đây thống kê toàn bộ **24 module** `src/videocreator/api/routes_*.py` trước khi thực hiện Wave 5, đối chiếu mức độ tương đương với `/api/v1/*` (Next.js 15 Studio UI) và độ phủ của 21 tệp kiểm thử hiện hữu.

---

## 1. Nhóm A — Các Mount Hạ tầng Thiết yếu (Đã chuyển sang `src/videocreator/api/mounts/`)

Các route này **không phải** giao diện Jinja2/HTMX cũ mà được Next.js 15 Standalone proxy hoặc gọi trực tiếp. Toàn bộ logic đã được chuyển sang gói `src/videocreator/api/mounts/` (giữ facade re-export mỏng tại `routes_*.py` để tương thích ngược):

| Module gốc | Module mới (`api/mounts/`) | Các đường dẫn chính | Vai trò trong V2 | Test kiểm chứng |
|---|---|---|---|---|
| `routes_media.py` | `mounts/media.py` | `GET /media/{subpath}`, `GET /files/{subpath}` | Phục vụ video/ảnh/âm thanh an toàn chống path traversal (`NFR-SEC-05`), Next.js proxy `/files/*`. | `test_v2_phase05_nextjs_e2e.py`, `test_security_and_bugfixes.py`, `test_shots.py` |
| `routes_freecut_bridge.py` | `mounts/freecut_bridge.py` | `/freecut*`, `/assets/{subpath}`, `/moss-tts/{subpath}`, `/api/editor/*` | Nhúng trình dựng FreeCut (MIT) & cầu nối xuất MP4 về Workspace. | `test_v2_phase12_freecut_and_timeline_editor.py`, `test_wave1_bugfixes.py` |
| `routes_oauth.py` | `mounts/oauth.py` | `GET /oauth/{platform}/start`, `/callback`, `POST /code` | Luồng callback OAuth 2.0 cho YouTube, TikTok, Threads. | `test_oauth.py`, `test_v2_phase03_channels_youtube_autopilot.py` |
| `routes_config_bundle.py` | `mounts/config_bundle.py` | `POST /settings/export`, `POST /settings/import` | Xuất/nhập gói cấu hình mã hóa `.vcx` (song song với `/api/v1/backup/*`). | `test_transfer.py`, `test_wave1_bugfixes.py` |
| *(Mới ở Wave 5)* | `mounts/ui_fallback.py` | `GET /ui-unavailable` | Màn hình chẩn đoán tiếng Việt độc lập khi tiến trình Next.js Standalone không khởi động được (thay cho hành vi rơi ngầm về V1). | `test_wave5_mounts_and_fallback.py` |
| *(Mới ở `2.3.0`)* | `mounts/health.py` | `GET /health` | Endpoint kiểm tra sức khỏe tiến trình Uvicorn dùng chung độc lập với `routes_dashboard.py`. | `test_v23_imagen_and_parity.py` |

---

## 2. Nhóm B — Các Router V1 Đã Được Port Đủ 100% Sang `/api/v1/*` ở `2.3.0`

Ở phiên bản `2.3.0`, toàn bộ 5 nhóm endpoint còn thiếu từ V1 đã có mặt đầy đủ trên `/api/v1/*` (kiểm chứng tại `tests/test_v23_imagen_and_parity.py`):

| Module V1 cũ | Module `/api/v1` tương đương (`2.3.0`) | Các đường dẫn `/api/v1/*` mới |
|---|---|---|
| `routes_broll.py` | `v1/routes_broll_v1.py` | `GET /api/v1/broll`, `POST /api/v1/broll`, `POST /api/v1/broll/suggest`, `POST /api/v1/broll/suggest/cancel`, `DELETE /api/v1/broll/{shot_id}` |
| `routes_manual.py` | `v1/routes_manual_v1.py` | `GET /api/v1/manual-tickets`, `POST /api/v1/manual-tickets`, `POST /api/v1/manual-tickets/{ticket_id}/upload`, `POST /api/v1/manual-tickets/{ticket_id}/cancel` |
| `routes_ai.py` | `v1/routes_ai_v1.py` + `services/ai_cli_health.py` | `GET /api/v1/ai/routes`, `POST /api/v1/ai/check-cli`, `POST /api/v1/ai/providers/{provider_name}/wake` |
| `routes_posting.py` | `v1/routes_videos_v1.py` | `GET /api/v1/videos/{video_id}/manual-bundle` |
| `routes_studio.py` | `v1/routes_studio_sessions_v1.py` | `GET /api/v1/studio/templates`, `POST /api/v1/studio/sessions/{session_id}/save-template`, `POST /api/v1/studio/templates/{template_id}/render` |

---

## 3. Nhóm C — Các Router HTML V1 Đã Có Trang Next.js V2 Tương đương (Đang giữ cho 21 tệp Test song song)

Toàn bộ nhóm dưới đây đã có trang Next.js 15 App Router + `/api/v1/*` tương ứng, hiện được gom gọn vào `src/videocreator/api/legacy_v1.py` (không còn làm phình `app.py`) để bảo toàn 21 tệp kiểm thử tương thích ngược:

| Module | Dòng | `TemplateResponse` | Trang V2 tương đương | Các tệp Test đang gọi trực tiếp |
|---|---:|:---:|---|---|
| `routes_dashboard.py` | 156 | Có | `/` (`app/page.tsx`) | `test_v2_phase01_foundation.py`, `test_v2_phase05_nextjs_e2e.py`, `test_transfer.py` |
| `routes_settings.py` | 188 | Có | `/settings` | `test_budget.py`, `test_secrets.py`, `test_security_and_bugfixes.py` |
| `routes_products.py` | 124 | Có | `/products` | `test_products.py`, `test_v2_phase01_foundation.py`, `test_v2_phase05_nextjs_e2e.py` |
| `routes_footage.py` | 191 | Có | `/footage` | `test_shots.py`, `test_v2_phase04_api_v1_surface.py` |
| `routes_shots.py` | 135 | Có | `/footage` | `test_v2_phase04_api_v1_surface.py` |
| `routes_planning.py` | 55 | Không | `/footage` & `/videos` | `test_shots.py`, `test_v2_phase04_api_v1_surface.py` |
| `routes_videos.py` | 161 | Có | `/videos`, `/videos/[id]` | `test_approvals.py`, `test_router.py`, `test_security_and_bugfixes.py` |
| `routes_assets.py` | 118 | Có | `/video-style` | `test_render.py`, `test_v2_phase02_style_and_qc.py` |
| `routes_approval.py` | 189 | Có | `/approval` | `test_approvals.py`, `test_posting_service.py`, `test_security_and_bugfixes.py` |
| `routes_accounts.py` | 160 | Có | `/approval` | `test_security_and_bugfixes.py`, `test_v2_phase04_api_v1_surface.py` |
| `routes_performance.py` | 51 | Có | `/approval` | `test_v2_phase04_api_v1_surface.py` |
| `routes_watchlist.py` | 123 | Có | `/trends` | `test_rank.py`, `test_trends_apify.py`, `test_trends_facebook_links.py` |
| `routes_trends.py` | 175 | Có | `/trends` | `test_trend_analysis_ui.py`, `test_trends_facebook_links.py`, `test_security_and_bugfixes.py` |
| `routes_suggestions.py` | 75 | Có | `/trends` | `test_suggestion_flow.py`, `test_v2_phase04_api_v1_surface.py` |
| `routes_voices.py` | 75 | Có | `/video-style` & `/welcome` | `test_v2_phase15_wizard_and_backup.py`, `test_v2_phase04_api_v1_surface.py` |

---

## 4. Cờ Tắt Hẳn V1 (`VIDEOCREATOR_DISABLE_LEGACY_V1=1`) & Lộ trình Gỡ Ở `3.0`
1. Đặt biến môi trường `VIDEOCREATOR_DISABLE_LEGACY_V1=1` để chạy `app.py` ở chế độ thuần V2 (`0` router Jinja2/HTMX được nạp, chỉ giữ `/health`, `/files`, `/oauth`, `/freecut`, `/ui-unavailable` và `/api/v1/*`).
2. Khi không còn cần chạy `--classic-ui` dự phòng sau 1 vòng phát hành, chuyển các assertion HTML cũ trong 21 tệp test sang gọi `/api/v1/*`, đặt mặc định `VIDEOCREATOR_DISABLE_LEGACY_V1=1` và xóa `src/videocreator/web/templates/` cùng `routes_*.py` Nhóm C.
