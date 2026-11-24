# Phase 15: Welcome Wizard & Sao lưu / Khôi phục Mã hóa (`.vcx`) (`V2-OPS-01..02`)

## Mục tiêu
1. Bổ sung `src/videocreator/onboarding.py` kiểm tra trạng thái hệ thống (FFmpeg, FFprobe, Node 24, `yt-dlp`, workspace, secrets, key pool, kênh MXH) và lưu bước hoàn tất / đặt lại **Welcome Wizard** (`kv_state.v2_wizard_completed`).
2. Bổ sung `src/videocreator/api/v1/routes_onboarding_v1.py` với:
   - `GET /api/v1/onboarding/status`, `POST /api/v1/onboarding/complete`, `POST /api/v1/onboarding/reset`.
   - `GET /api/v1/backup/summary`, `POST /api/v1/backup/export` (tạo gói `.vcx` mã hóa mật khẩu chứa `config.toml`, `app.db`, `secrets.enc.json` dùng lại `transfer.py` và tùy chọn lưu bản sao vào `paths.backups_dir`), `POST /api/v1/backup/restore` (upload multipart khôi phục đa máy an toàn, từ chối sai mật khẩu mà không ghi đè dữ liệu hiện tại).
3. Viết `tests/test_v2_phase15_wizard_and_backup.py` và kiểm chứng lại cả `tests/test_transfer.py`.
