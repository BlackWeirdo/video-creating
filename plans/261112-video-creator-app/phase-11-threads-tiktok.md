# Phase 11: Threads + TikTok

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 07](phase-07-posting-facebook-instagram.md), [phase 10](phase-10-scheduling-retry-alerts.md); kết quả S4, S5 của [phase 01](phase-01-verification-spikes.md)
- Docs: [research 01 mục 3, 4](research/researcher-01-social-and-trend-apis.md)

## Overview

- Ngày: 2026-11-12
- Mô tả: thêm 2 adapter `Poster`: Threads và TikTok. TikTok chạy chế độ hộp nháp (inbox) cho tới khi audit qua, sau đó bật Direct Post bằng 1 cờ config.
- Ưu tiên: P1
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Threads API CHƯA được research tra (không có nguồn). Hiểu biết sẵn có, chưa kiểm chứng: mô hình container giống IG (`POST /{user_id}/threads` với `media_type=VIDEO`, `video_url` -> `threads_publish`), OAuth riêng của Threads. Bước đầu của phase là đọc docs chính thức.
- TikTok app chưa audit: mọi bài chỉ private. Hộp nháp (`/v2/post/publish/inbox/video/init/`, scope `video.upload`) theo kết quả S5.
- Cả hai bắt buộc OAuth (không dán token được như Meta System User) -> đây là lần đầu app cần luồng OAuth. Redirect theo S4: localhost, hoặc trang callback tĩnh HTTPS hiện `code` để dán.
- Token TikTok ngắn hạn + refresh token (thời hạn: chưa xác nhận) -> cần refresh tự động trước khi đăng.
- Trạng thái `needs_user_action` đã có trong state model từ phase 02 cho đúng trường hợp hộp nháp.

## Requirements

- `posting/threads.py`: đăng video + caption, trả permalink.
- Bước đọc docs phải điền `[platform_limits.threads]` và `[platform_limits.tiktok]` (thời lượng, dung lượng, codec, fps, tỉ lệ); cả hai adapter gọi `preflight.check()` trước khi đăng như phase 07. Dùng chung bản master, không xuất bản riêng.
- `posting/tiktok.py`:
  - `mode = "inbox"` (mặc định): upload vào hộp nháp -> `PostResult("needs_user_action")` -> Telegram nhắc "Mở TikTok, vào hộp thư, bấm đăng video <tên>".
  - `mode = "direct"` (sau audit): `creator_info/query` -> `video/init` (`FILE_UPLOAD`) -> PUT -> `status/fetch`.
- OAuth 1 module dùng chung cho 2 nền tảng: tạo URL authorize (có `state`), đổi `code` lấy token, refresh.
- Trang tài khoản: nút "Kết nối Threads", "Kết nối TikTok"; hiện hạn token. Nhiều tài khoản (chốt 2026-11-12): bấm kết nối lặp lại cho từng tài khoản (2–3 mỗi nền tảng), mỗi lần 1 phiên OAuth riêng; gắn ngôn ngữ cho từng tài khoản.
- Người dùng xác nhận đã đăng TikTok tay: nút "Đã đăng" (UI/Telegram) -> post `posted`.
- Nộp audit TikTok ngay khi luồng chạy được (nếu audit cần video demo, quay từ app ở phase này).

## Architecture

```
posting/oauth.py     # build_authorize_url(platform), exchange_code(platform, code), refresh(platform, account)
posting/threads.py   # container -> poll -> publish
posting/tiktok.py    # inbox | direct theo config [tiktok].mode
api/routes_oauth.py  # GET /oauth/{platform}/start, GET /oauth/{platform}/callback, POST /oauth/{platform}/code (dán tay)
```

- `service.publish_due()` gọi `oauth.refresh()` nếu token hết hạn trong < 10 phút trước khi publish.
- Nhánh callback tĩnh: 1 file `deploy/oauth-callback.html` đưa lên Cloudflare Pages, chỉ hiện `code` + `state`.
- Đăng ký adapter: dict `{platform: Poster}` trong `posting/__init__.py`, không plugin system.

## Related code files

Tạo: `src/videocreator/posting/oauth.py`, `posting/threads.py`, `posting/tiktok.py`, `api/routes_oauth.py`, `deploy/oauth-callback.html` (chỉ khi S4 lùi), `tests/test_oauth.py`, `tests/test_threads_live.py`, `tests/test_tiktok_live.py`.
Sửa: `posting/__init__.py`, `posting/service.py`, `web/templates/accounts.html`, `telegram_bot.py` (nút "Đã đăng"), `config.py`.

## Implementation Steps

1. Đọc docs chính thức Threads (publishing, OAuth, giới hạn, spec video) và trang upload/inbox của TikTok; ghi điểm khác với giả định vào đầu file phase này.
2. `oauth.py` + routes; kiểm tra `state` chống CSRF.
3. `threads.py`.
4. `tiktok.py` chế độ inbox trước; direct sau (không test công khai được trước audit: test với `SELF_ONLY`).
5. Nhắc Telegram + nút "Đã đăng".
6. Test `-m local`: sinh URL authorize đúng tham số, `state` sai bị từ chối, logic refresh theo hạn token (SQLite thật).
7. Test `-m live` (CẦN tài khoản Threads và TikTok của người dùng đã kết nối tay 1 lần): đăng clip mẫu lên Threads thử; đẩy clip mẫu vào hộp nháp TikTok; direct post `SELF_ONLY`.
8. Checklist tay: luồng kết nối OAuth 2 nền tảng; mở app TikTok thấy video trong hộp thư.
9. Nộp audit TikTok.

## Todo list

- [ ] Đọc docs Threads + TikTok inbox, cập nhật giả định
- [ ] OAuth dùng chung + refresh
- [ ] Adapter Threads
- [ ] Adapter TikTok inbox
- [ ] Adapter TikTok direct (SELF_ONLY tới khi audit)
- [ ] Nhắc Telegram + xác nhận đã đăng
- [ ] Test local + live
- [ ] Nộp audit TikTok

## Success Criteria

- 1 video duyệt -> tự lên FB, IG, Threads đúng lịch; TikTok vào hộp nháp và người dùng nhận nhắc trên Telegram.
- Token TikTok tự refresh qua ít nhất 1 chu kỳ hết hạn mà không cần đăng nhập lại.
- Đổi `tiktok.mode = "direct"` là đủ để chuyển chế độ, không sửa code.

## Risk Assessment

- Audit TikTok chậm hoặc bị từ chối: hộp nháp là trạng thái lâu dài chấp nhận được; mục tiêu "không thao tác tay ngoài duyệt" KHÔNG đạt cho TikTok cho tới khi audit qua. Nói rõ với người dùng.
- Inbox endpoint bị coi là cũ (research ghi "endpoint cũ"): nếu S5 hỏng -> direct `SELF_ONLY` + người dùng đổi quyền riêng tư trong app.
- Threads khác giả định (chưa có nguồn): có thể thêm 0.5 ngày.
- Threads/TikTok đòi App Review riêng để đăng công khai: chưa xác nhận; nếu có, cùng cách xử lý như S2.

## Security Considerations

- `state` ngẫu nhiên, dùng 1 lần, hết hạn 10 phút; client secret trong secrets store.
- Trang callback tĩnh không gửi `code` đi đâu (không JS gọi mạng); `code` dùng 1 lần, hạn ngắn.
- Refresh token được che trong log như mọi secret khác.

## Next steps

- Sau audit: bật `direct`, bỏ bước nhắc tay.
- Phase 12 độc lập, có thể làm song song.
