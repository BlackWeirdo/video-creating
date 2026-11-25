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

> **Lưu ý thêm**: `GET /health` trong `routes_dashboard.py` vẫn đang được `wait_for_health()` trong `__main__.py` và các bài E2E gọi để kiểm tra tiến trình Uvicorn trước khi khởi chạy Next.js.

---

## 2. Nhóm B — Các Router V1 Chưa Có Tương đương 1:1 trên `/api/v1` (Giữ cô lập trong `legacy_v1.py`)

Các tính năng dưới đây hiện mới có trên router V1 và chưa có API `/api/v1` tương đương hoàn chỉnh; do đó **không được xóa mù** ở phiên bản `2.2.0`:

| Module | Dòng | Đường dẫn chưa có 1:1 ở `/api/v1` | Ghi chú nghiệp vụ & Test |
|---|---:|---|---|
| `routes_broll.py` | 180 | `/broll`, `/broll/suggest`, `/broll/suggest/cancel`, `/broll/create` | Gợi ý cảnh quay bù (B-roll checklist) cho kịch bản thiếu shot (`test_broll_suggest.py`). |
| `routes_manual.py` | 96 | `/manual`, `/manual/create`, `/manual/{ticket_id}/upload`, `/cancel` | Luồng phiếu đăng thủ công (manual publish ticket) khi không nối token kênh (`test_posting_service.py`). |
| `routes_ai.py` | 128 | `/ai-routes`, `/ai/check-cli`, `/ai/provider/{provider_name}/wake` | Kiểm tra kết nối CLI provider & đánh thức kết nối (`test_router.py`). |
| `routes_posting.py` | 162 | `GET /posts/{post_id}/manual-bundle` (cùng `/schedule*`) | Xuất gói ZIP bài đăng đơn lẻ từ lịch đăng cũ (`test_posting_service.py`, `test_security_and_bugfixes.py`). |
| `routes_studio.py` | 175 | `/studio/{session_id}/revise`, `/recheck` | Vòng lặp góp ý chỉnh sửa kịch bản AI nhiều lượt (`test_studio_checks.py`). |

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

## 4. Lộ trình Dọn hẳn V1 ở Phiên bản Tương lai (`3.0`)
1. Bổ sung `/api/v1/broll/*` và `/api/v1/manual-tickets/*` nếu còn nhu cầu nghiệp vụ cho Nhóm B.
2. Chuyển các assertion HTML cũ trong 21 tệp test (`test_security_and_bugfixes.py`, `test_posting_service.py`, `test_approvals.py`, v.v.) sang gọi `/api/v1/*`.
3. Gỡ lời gọi `include_legacy_v1_routers(app)` khỏi `src/videocreator/app.py` và xóa `src/videocreator/web/templates/` cùng các `routes_*.py` Nhóm C.
