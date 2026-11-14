# Phase 06: Hàng chờ duyệt + Telegram bot cơ bản

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 05](phase-05-ffmpeg-render-core.md)
- Docs: [research 02 mục 6](research/researcher-02-video-pipeline-and-packaging.md)

## Overview

- Ngày: 2026-11-12
- Mô tả: trang hàng chờ duyệt trong UI; bot Telegram gửi video kèm nút Duyệt/Loại, lệnh `/status`. Duyệt là bắt buộc trước khi đăng.
- Ưu tiên: P0
- Trạng thái triển khai: hoàn thành (2026-11-13)
- Trạng thái review: đã kiểm thử (`pytest -m local`)

## Key Insights

- PTB v22 chạy trong lifespan FastAPI: `initialize/start/updater.start_polling`; KHÔNG `run_polling()` (tự tạo loop).
- Chỉ máy `role = "server"` khởi động bot; 2 máy cùng poll 1 token sẽ xung đột.
- UI và Telegram gọi CHUNG 1 hàm `approve()/reject()`; chống bấm trùng nhờ `transition()` có điều kiện ở phase 02.
- Bot API chuẩn giới hạn upload ~50 MB (chưa xác nhận lại): file > 45 MB thì transcode bản xem thử 720p.

## Requirements

- Màn hình duyệt và tin Telegram hiện: tên sản phẩm trong video, các câu lời/caption bị đánh dấu "không có căn cứ trong thông tin sản phẩm" (từ phase 04), và nhãn "có cảnh AI" nếu video chứa shot `ai_broll`. Người duyệt là lớp kiểm tra cuối cho độ chính xác sản phẩm.
- Không có đường nào đưa video sang `approved` ngoài `approvals.approve()`; phase đăng bài chỉ nhận video `approved` trở đi.
- Trang "Chờ duyệt": player, caption từng nền tảng sửa được (tab theo nền tảng), kết quả kiểm tra định dạng từng nền tảng (phase 05), nút Duyệt / Loại (lý do tuỳ chọn). Ô chọn tài khoản đích CHƯA có ở phase này (bảng `accounts` chỉ có dữ liệu từ phase 07); phase 07 thêm ô đó vào màn hình này.
- Người duyệt (chốt 2026-11-12): nhóm Telegram 2–5 người, MỘT người bấm là đủ. Lưu `approved_by` = user ID + tên người bấm; sau khi duyệt, bot sửa tin nhắn thành "Đã duyệt bởi <tên>" và gỡ nút. Từ phase 07: duyệt qua Telegram dùng tài khoản đích mặc định (các tài khoản cùng ngôn ngữ với caption); đổi tài khoản ngay trong Telegram có từ phase 16.
- Khi video vào `pending_approval`: bot gửi `send_video` + caption + nút inline `ok:<id>` / `no:<id>` tới các chat trong allowlist.
- Bấm nút: cập nhật trạng thái, sửa tin nhắn thành "Đã duyệt bởi X" / "Đã loại"; nếu đã xử lý ở nơi khác thì trả lời "đã xử lý rồi".
- Lệnh: `/status` (số video theo trạng thái, job đang chạy, chi phí AI hôm nay), `/pending` (gửi lại các video đang chờ). `/report` thêm ở phase 10, 15. Bộ lệnh điều khiển đầy đủ và các nút `Đăng ngay` / `Làm lại` / chọn tài khoản / sửa caption: [phase 16](phase-16-telegram-control-center.md). Phase này chỉ làm Duyệt/Loại.
- Allowlist 2 lớp: `telegram.allowed_chat_ids` (nhóm duyệt) VÀ `telegram.approver_user_ids` (kiểm tra `from_user.id` của người bấm nút); chat lạ hoặc người ngoài danh sách bị bỏ qua và ghi log. Hai người bấm gần như cùng lúc: chuyển trạng thái bằng 1 câu `UPDATE ... WHERE status = 'pending_approval'`, người sau nhận "đã xử lý rồi".

## Architecture

```
approvals.py        # approve(video_id, by), reject(video_id, by, reason) -> gọi state.transition
telegram_bot.py     # build_application(), handlers, notify_pending(video_id), send_text(msg)
api/routes_approval.py  # GET /approval, POST /videos/{id}/approve|reject
```

- Hook: sau `rendered -> pending_approval`, `render.py` gọi `notify_pending()` (no-op nếu bot không chạy).
- `approved_by`: `ui` hoặc `tg:<user_id>`.
- `send_text()` là điểm duy nhất các phase sau dùng để gửi cảnh báo/báo cáo.

## Related code files

Tạo: `src/videocreator/approvals.py`, `telegram_bot.py`, `api/routes_approval.py`, `web/templates/approval.html`, `tests/test_approvals.py`, `tests/test_telegram_live.py`.
Sửa: `app.py` (lifespan khởi động/dừng bot theo role + có token), `pipeline/render.py` (hook), `config.py`.

## Implementation Steps

1. `uv add "python-telegram-bot==22.*"`.
2. `approvals.py` + route + template hàng chờ.
3. `telegram_bot.py`: `Application.builder().token(...)`, `CommandHandler` với `filters.Chat(ALLOWED)`, `CallbackQueryHandler(pattern=r"^(ok|no):\d+$")` kiểm tra lại `effective_chat.id`.
4. Lifespan: start bot nếu role server và có token; shutdown gọn (`updater.stop`, `stop`, `shutdown`).
5. `notify_pending()`: chọn file gốc hoặc bản 720p theo dung lượng.
6. Test `-m local`: approve/reject trên SQLite thật; approve 2 lần -> lần 2 báo đã xử lý; không thể chuyển `planned -> approved`.
7. Test `-m live` (cần token bot + chat thử): `send_text` và `send_video` clip mẫu trả về message id.
8. Checklist tay: bấm Duyệt trên Telegram -> UI đổi trạng thái; bấm Loại trên UI -> nút Telegram trả "đã xử lý rồi"; chat ngoài allowlist gõ `/status` không được trả lời.

## Todo list

- [x] approvals + UI hàng chờ (tab caption từng nền tảng, tên sản phẩm, câu bị đánh dấu, kết quả kiểm tra định dạng)
- [x] Bot trong lifespan (`TelegramBotService`)
- [x] Nút inline + allowlist 2 lớp (`allowed_chat_ids` & `approver_user_ids`)
- [x] `/status`, `/pending`
- [x] Bản xem thử 720p khi file lớn (`> 45 MB`)
- [x] Test local + live (`tests/test_approvals.py`, `tests/test_telegram_live.py`)
- [ ] Checklist tay bấm nút (khi người dùng điền `TELEGRAM_BOT_TOKEN`)

## Success Criteria

- Render xong 1 video -> trong < 1 phút điện thoại nhận video kèm nút; bấm Duyệt -> UI hiện `approved`.
- `/status` trả số liệu đúng với UI.
- Tắt app: bot dừng sạch, không treo process.

## Risk Assessment

- Bấm nút không tự động test được (cần người) -> checklist tay, ghi rõ ở trên.
- Mạng chập chờn làm polling lỗi: PTB tự retry; lỗi bot không được làm sập FastAPI (bắt exception ở lifespan, ghi log, UI vẫn chạy).
- Token bot bị dùng ở máy thứ hai: lỗi `Conflict` -> log + hiện cảnh báo trên trang chủ.

## Security Considerations

- Allowlist kiểm tra ở cả filter lẫn trong callback (callback query không qua filter lệnh).
- `callback_data` chỉ chứa id số; mọi quyết định kiểm tra lại trạng thái trong DB.
- Token bot trong secrets store.

## Next steps

- Phase 07 đăng video `approved`.
