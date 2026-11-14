# Phase 02: Khung dự án, DB, config, secrets, log

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 01](phase-01-verification-spikes.md) (S9; không cần chờ spike Meta)
- Docs: [research 02 mục 5, 6](research/researcher-02-video-pipeline-and-packaging.md)

## Overview

- Ngày: 2026-11-12
- Mô tả: dựng bộ khung chạy được: cửa sổ pywebview mở trang chủ, DB có schema lõi, config, kho secrets, log, worker job, state machine. Là tài liệu tham chiếu kiến trúc cho mọi phase sau.
- Ưu tiên: P0
- Trạng thái triển khai: hoàn thành (2026-11-13)
- Trạng thái review: đã tự kiểm (`pytest -m local`: 11/11 passed)

## Key Insights

- 1 process, 1 event loop: FastAPI lifespan khởi động worker, scheduler, bot. Không Celery/Redis.
- UI Jinja2 + HTMX: không Node, không build step, bộ cài nhẹ hơn. (Ngoại lệ duy nhất cần Node.js: chế độ Studio ở phase 17, cài riêng khi dùng.)
- stdlib `sqlite3` + file SQL migration. Không ORM (KISS, ít bảng).
- Lịch đăng lưu trong bảng `posts` (cột `scheduled_at`), scheduler chỉ tick mỗi phút -> không cần jobstore của APScheduler, sống sót qua restart.
- Secrets phải chạy cả Windows lẫn Linux headless -> không dùng keyring (Linux headless rắc rối). Dùng file mã hoá.

## Requirements

- `uv run videocreator` mở cửa sổ; `uv run videocreator --headless` chạy server không cửa sổ.
- Thư mục dữ liệu qua `platformdirs.user_data_dir("VideoCreator")`, ghi đè bằng env `VIDEOCREATOR_DATA`.
- `role = "server" | "client"` trong config: chỉ `server` chạy bot + scheduler. Mặc định `server`. (Tên `client` để không nhầm với chế độ dựng "Studio" của phase 17.)
- Chỉ 1 instance trên 1 máy (named mutex Windows; file lock Linux).
- Log xoay vòng, không lộ token.

## Architecture

Layout:

```
pyproject.toml, uv.lock
src/videocreator/
  __main__.py          # parse --headless/--host/--port; desktop: uvicorn thread + pywebview
  app.py               # FastAPI factory + lifespan (worker, scheduler, bot theo role)
  config.py            # config.toml -> pydantic Settings
  paths.py             # data dir, media/, logs/, work/, ffmpeg path
  db.py                # connect (WAL, foreign_keys), migrate(), helper query
  migrations/001_core.sql
  secrets_store.py     # get/set/delete; DPAPI trên Windows, chmod 600 trên Linux
  logging_setup.py     # RotatingFileHandler + filter che token
  state.py             # transition(video_id, to) có kiểm tra
  jobs.py              # hàng job trong DB + 1 worker asyncio
  api/                 # routes_*.py (thêm dần theo phase)
  web/templates/, web/static/   # Jinja2 + htmx.min.js (bundle local)
  pipeline/  ai/  posting/  trends/   # package rỗng, phase sau điền
tests/  (samples/, test_*.py)
```

Schema `001_core.sql` (cột chính):

| Bảng | Cột |
|---|---|
| `products` | id, name, material, facts_json, created_at (người dùng nhập tay; nguồn sự thật cho lời và caption) |
| `footage` | id, path, sha256 (unique), duration_s, width, height, orientation, crop_json, product_ids_json, status, error, created_at |
| `shots` | id, footage_id, idx, start_s, end_s, description, tags_json, has_product, product_ids_json, quality, thumb_path |
| `assets` | id, kind (`music`/`sfx`/`broll`), path, duration_s, meta_json |
| `videos` | id, footage_id (NULL khi kịch bản lấy shot từ nhiều footage), product_ids_json, engine (`ffmpeg`/`mpt`/`studio`: MỘT cột duy nhất cho cách dựng; `ffmpeg` và `mpt` là chế độ Nhanh, `studio` là phase 17), preflight_json, unsupported_claims_json, cover_path, status, plan_json, voice_lang (`none`/`vi`/`en`), caption_lang (`vi`/`en`), captions_json (caption riêng từng nền tảng: `{"facebook": "...", "instagram": "...", "threads": "...", "tiktok": "..."}`), target_accounts_json (id các tài khoản chọn lúc duyệt), output_path, duration_s, error, reject_reason, created_at, approved_at, approved_by |
| `accounts` | id, platform, external_id, name, lang (`vi`/`en`), slots_json (khung giờ riêng, NULL = dùng mặc định), secret_key, token_expires_at, enabled |
| `posts` | id, video_id, account_id, status, scheduled_at, attempts, next_attempt_at, remote_container_id, external_post_id, permalink, error, posted_at; UNIQUE(video_id, account_id) |
| `jobs` | id, kind, ref_id, status (`queued`/`running`/`done`/`failed`), error, log_tail, created_at, started_at, finished_at |
| `ai_usage` | id, day, provider, model, kind, input_units, output_units, cost_usd, ref |

Migration sau, đánh số theo THỨ TỰ THỰC HIỆN: `001b_routing.sql` (phase 18, ngay sau phase 04), `002_trends.sql` (phase 12), `003_suggestion_link.sql` (phase 13), `004_telegram_control.sql` (phase 16), `005_studio.sql` (phase 17), `006_shot_asset.sql` (phase 14), `007_post_metrics.sql` (phase 15).

State:

```
footage: imported -> analysing -> analysed | failed
video:   planned -> rendering -> rendered -> (scoring, từ phase 16) -> pending_approval -> approved -> scheduled -> posted | failed
         bất kỳ trạng thái trước approved -> superseded (bị thay bằng bản làm lại, phase 16)
job:     queued -> running -> done | failed ; queued -> waiting_quota -> queued (phase 18)
         pending_approval -> rejected ;  failed -> rendering (render lại) | scheduled (đăng lại)
post:    scheduled -> publishing -> posted | failed | needs_user_action (TikTok hộp nháp)
```

- `transition()` dùng `UPDATE videos SET status=? WHERE id=? AND status=?`, kiểm tra rowcount -> chống duyệt trùng (UI và Telegram bấm cùng lúc).
- `video.posted` khi mọi `post` đã `posted`/`needs_user_action`; `failed` khi có post lỗi vĩnh viễn (chi tiết nằm ở `posts`).
- Worker: 1 task asyncio, lấy job `queued` cũ nhất, chạy việc nặng bằng `asyncio.to_thread`, song song = 1. Khởi động: job `running` -> `queued` lại.

Config `config.toml` (không bí mật): role, host, port, `budget.daily_usd` (mặc định 5), `budget.generative_daily_usd` (mặc định 15), bảng giá model, model ID, `telegram.allowed_chat_ids` (nhóm duyệt), `telegram.approver_user_ids` (2–5 người được bấm duyệt), `r2.bucket`, `r2.public_base`, khung giờ đăng, `[ai.routes]` (danh sách provider theo thứ tự cho từng vai trò `vision`/`writer`/`checker`/`studio`/`videogen`) và `[ai.policy]` (phase 04, 18), `[platform_limits.<nền tảng>]` (phase 05).
Secrets (`secrets.bin`): JSON {tên: giá trị}; Windows mã hoá `CryptProtectData` qua `ctypes`; Linux file thường quyền 600. API: `get(name)`, `set(name, value)`.
Log: `logs/app.log`, 5 MB x 5 file; filter thay mọi giá trị đang có trong secrets store bằng `***`.

## Related code files

Tạo: toàn bộ file trong layout trên; `tests/test_db.py`, `tests/test_state.py`, `tests/test_secrets.py`, `tests/test_jobs.py`; `README.md` (cách chạy).

## Implementation Steps

1. `uv init`, Python 3.11; deps: fastapi, uvicorn, jinja2, python-multipart, pywebview, platformdirs, pydantic, httpx, pytest. Entry point `videocreator`.
2. `paths.py`, `config.py` (tạo `config.toml` mặc định nếu thiếu).
3. `db.py` + `001_core.sql` + `migrate()` theo `user_version`.
4. `secrets_store.py`, `logging_setup.py`.
5. `state.py` (bảng chuyển trạng thái hợp lệ) + `jobs.py` (enqueue, worker, registry `kind -> handler`).
6. `app.py`: lifespan, `/health`, trang chủ liệt kê số footage/video theo trạng thái, trang Settings (xem/sửa config, nhập secret; secret chỉ ghi, không hiện lại).
7. `__main__.py`: single-instance, chế độ desktop (uvicorn thread -> chờ `/health` -> `webview.create_window`) và `--headless`.
8. Test `-m local`: migrate trên DB tạm thật, transition hợp lệ/không hợp lệ, 2 lần approve đồng thời chỉ 1 lần thắng, secrets round-trip, job chạy và phục hồi sau "crash".

## Todo list

- [x] Khởi tạo uv project + deps
- [x] paths, config
- [x] db + migration lõi
- [x] secrets store (DPAPI/600)
- [x] logging + che token
- [x] state machine + jobs worker
- [x] app + trang chủ + Settings
- [x] entry point desktop/headless + single-instance
- [x] Test local xanh

## Success Criteria

- `uv run videocreator` mở cửa sổ, hiện trang chủ; đóng mở lại dữ liệu còn.
- `uv run videocreator --headless` + mở `http://127.0.0.1:<port>` trong trình duyệt ra cùng trang.
- `uv run pytest -m local` xanh, không mock.
- Mở `secrets.bin` bằng editor không đọc được key (Windows).

## Risk Assessment

- pywebview thiếu WebView2 trên Win 10 cũ: báo lỗi rõ + tự mở trình duyệt mặc định thay thế.
- SQLite ghi từ nhiều thread (worker + request): 1 connection mỗi thao tác, WAL, `busy_timeout=5000`.
- Phình phạm vi: phase này KHÔNG làm UI đẹp, không auth, không bot.

## Security Considerations

- Mặc định bind `127.0.0.1`. Bind khác đi chỉ có ở phase 08 kèm mật khẩu.
- Secrets không vào `config.toml`, không vào log, không trả về qua API.
- DPAPI gắn với user Windows: copy `secrets.bin` sang máy khác không giải mã được (đúng ý; chuyển máy dùng export ở phase 08).

## Next steps

- Phase 03 dùng `jobs`, `footage`, `shots`.
