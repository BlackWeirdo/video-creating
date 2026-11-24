# Phase 09: Kênh Autopilot tự chạy & Giao diện Next.js Đợt 2 (`V2-AUT-01..04`)

## Mục tiêu
1. Bổ sung migration `021_v2_autopilot_rules.sql` (`autopilot_rules`, `autopilot_runs`) và `src/videocreator/autopilot.py` hỗ trợ 4 nguồn (`suggestions`, `products_ab`, `rss_feed`, `localize_trends`), chặn vượt `daily_cap`, kết nối lịch `APScheduler` 15 phút và tự xếp lịch `posts` qua `try_autopilot_approve` khi đạt ngưỡng điểm QC.
2. Xây dựng `/api/v1/autopilot/*` và giao diện Next.js 15 Đợt 2 (`/localize`, `/batch`, `/autopilot`, cập nhật `/trends` & `/settings`).
3. Build lại Next.js standalone, viết `tests/test_v2_phase09_autopilot_and_wave2_ui.py` và chạy toàn bộ `uv run pytest -m local -q` đạt 100%.
