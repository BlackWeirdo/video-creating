# Phase 07: Đăng Facebook Page + Instagram (R2)

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 06](phase-06-approval-queue-telegram-bot.md); kết quả S2, S3, S4, S10 của [phase 01](phase-01-verification-spikes.md)
- Docs: [research 01 mục 1, 2, 3](research/researcher-01-social-and-trend-apis.md)

## Overview

- Ngày: 2026-11-12
- Mô tả: interface `Poster`, upload R2, adapter Facebook Page và Instagram, kết nối tài khoản Meta, nút "Đăng ngay" và hẹn giờ thủ công cho video đã duyệt.
- Ưu tiên: P0
- Trạng thái triển khai: hoàn thành (2026-11-13)
- Trạng thái review: đã kiểm thử (`pytest -m local`)

## Key Insights

- Phase rủi ro nhất tuần 1: phụ thuộc kết quả S2 (Live mode), nằm ngoài tầm kiểm soát.
- IG chắc chắn chỉ có đường `video_url` công khai (resumable chỉ cho Facebook Login for Business) -> dùng R2 cho cả FB và IG, 1 đường duy nhất.
- Xác thực: nếu S3 xác nhận token System User không hết hạn -> v1 chỉ cần DÁN TOKEN vào Settings, không viết luồng OAuth cho Meta (KISS). Nếu không: OAuth với redirect theo S4.
- Đăng 2 bước (IG: tạo container -> publish) có thể hỏng giữa chừng -> lưu `remote_container_id` TRƯỚC khi publish, retry kiểm tra trạng thái trước, tránh đăng trùng.
- 2–3 Page/IG có thể thuộc nhiều Business khác nhau -> 1 token có thể không thấy hết; trang kết nối cho nhập nhiều token, mỗi `account` trỏ tới secret của token thấy nó.
- Endpoint FB cho video dọc (`/{page_id}/videos` với `file_url` hay `/video_reels`): theo S10. Mặc định plan: `/videos` + `file_url`.

## Requirements

- Interface:

```python
@dataclass
class PostResult: status: str  # "posted" | "needs_user_action"
                  external_post_id: str | None; permalink: str | None

class Poster(Protocol):
    platform: str
    def publish(self, account: Account, video_url: str, video_path: Path, caption: str, post: Post) -> PostResult: ...

class TransientPostError(Exception): ...   # mạng, 5xx, rate limit -> retry
class PermanentPostError(Exception): ...   # token sai (190), bị từ chối nội dung -> dừng, báo người
```

- Kết nối tài khoản: nhập token -> app gọi API liệt kê Page + IG Business liên kết -> lưu `accounts` (token vào secrets, `token_expires_at` từ `debug_token`).
- Thêm ô chọn tài khoản đích vào màn hình duyệt của phase 06 (mặc định tick các tài khoản `enabled` cùng ngôn ngữ với caption; tài khoản của nền tảng không qua kiểm tra định dạng bị bỏ tick); lưu `videos.target_accounts_json`.
- Trên video `approved`: "Đăng ngay" hoặc chọn giờ -> tạo 1 dòng `posts` (`scheduled`) cho mỗi tài khoản đích, video -> `scheduled`.
- Tick mỗi phút (APScheduler, chỉ role server): lấy `posts` đến hạn (`scheduled_at <= now` và `next_attempt_at <= now`) -> publish.
- Retry tối thiểu ở phase này: lỗi transient -> tối đa 3 lần, giãn 1, 5, 30 phút; lỗi permanent hoặc hết lượt -> `failed` + báo Telegram. (Tự xếp lịch và cảnh báo token ở phase 10.)
- Kết quả: lưu `external_post_id`, `permalink`; Telegram báo "Đã đăng: <link>".
- Nếu S2 không đạt: nút "Tải gói đăng tay" (mp4 + caption) thay cho đăng tự động.
- Kiểm tra định dạng trước khi đăng: mỗi adapter gọi `preflight.check(master, platform)` (phase 05) ngay trước `publish`; có lỗi thì `post` thành `failed` với lý do rõ, không gọi API. Sau lần đăng thật đầu tiên trên mỗi nền tảng: tải bài về xem nền tảng có nén lại làm mất chi tiết sản phẩm không, chỉnh bitrate master nếu cần. Lỗi định dạng do nền tảng trả về được ghi nguyên văn vào `posts.error` và bổ sung vào bảng `platform_limits`.
- Nhiều tài khoản (chốt 2026-11-12): 2–3 Page và 2–3 IG. Trang kết nối liệt kê mọi Page/IG mà token thấy, người dùng tick cái nào dùng và gắn ngôn ngữ (`vi`/`en`) cho từng tài khoản. Mỗi `post` = 1 video x 1 tài khoản, lấy caption của đúng nền tảng từ `videos.captions_json`. Khoá chống đăng trùng theo (video_id, account_id).

## Architecture

```
posting/base.py        # Poster, PostResult, 2 lớp lỗi
posting/storage_r2.py  # upload(path) -> public_url (boto3 S3 API, key ngẫu nhiên); delete(key)
posting/meta_auth.py   # list_pages_and_ig(token), debug_token(token)
posting/facebook.py    # POST /{page_id}/videos file_url=..., description=...
posting/instagram.py   # POST /{ig_id}/media (REELS, video_url) -> poll status_code -> POST /{ig_id}/media_publish
posting/service.py     # publish_due(): chọn post, upload R2 1 lần/video, gọi adapter, phân loại lỗi, cập nhật DB
scheduler.py           # AsyncIOScheduler: job interval 60s -> service.publish_due()
api/routes_posting.py  # kết nối tài khoản, tạo post, xem lịch sử
```

- `service.publish_due()` đặt `post.status = publishing` bằng UPDATE có điều kiện trước khi gọi API (chống chạy trùng). Khởi động lại: post kẹt ở `publishing` -> nếu có `remote_container_id` thì hỏi trạng thái, không thì đưa về `scheduled`.
- IG: sau khi tạo container lưu ngay `remote_container_id`; poll `status_code` tối đa 5 phút; `FINISHED` -> publish; `ERROR` -> permanent.
- File R2 xoá sau khi mọi post của video ở trạng thái cuối + 24 giờ.
- Phiên bản Graph API ghim trong config.

## Related code files

Tạo: các file trên; `web/templates/accounts.html`, `web/templates/posts.html`; `tests/test_posting_service.py` (local), `tests/test_r2_live.py`, `tests/test_meta_live.py` (live).
Sửa: `app.py` (scheduler trong lifespan), `telegram_bot.py` (tin "Đã đăng: <link>" và tin lỗi), `web/templates/approval.html` (ô chọn tài khoản đích), `web/templates/video_detail.html`. Không thêm lệnh `/post`: nút `Đăng ngay` trên Telegram thuộc phase 16.

## Implementation Steps

1. Đọc kết quả S2–S4, S10; chốt: dán token hay OAuth; endpoint FB.
2. `uv add boto3 apscheduler`. `storage_r2.py`.
3. `base.py`, `meta_auth.py`, trang kết nối tài khoản.
4. `facebook.py`, `instagram.py`: ánh xạ mã lỗi Graph (190, 4/17/32/613, 5xx) sang transient/permanent.
5. `service.py` + `scheduler.py` (chỉ start khi role server).
6. UI chọn tài khoản đích / tạo post / hẹn giờ / lịch sử.
7. Test `-m local`: logic chọn post đến hạn, backoff, chuyển trạng thái trên SQLite thật (không gọi mạng: test hàm thuần `next_attempt()` và truy vấn DB).
8. Test `-m live`: upload clip mẫu lên R2 và GET lại qua public URL; đăng clip mẫu lên Page thử và IG thử, khẳng định có `permalink`, rồi xoá bài FB (IG xoá qua API: chưa xác nhận, xoá tay). CẦN tài khoản thử của người dùng.
9. Checklist tay: token sai -> `failed` + Telegram báo; tắt mạng giữa chừng -> retry thành công, không đăng trùng.

## Todo list

- [x] Chốt nhánh xác thực + endpoint (`posting/meta_auth.py`)
- [x] R2 upload/xoá (`posting/storage_r2.py`)
- [x] Interface + kết nối tài khoản (`posting/base.py`, `api/routes_posting.py`)
- [x] Adapter Facebook (`posting/facebook.py`)
- [x] Adapter Instagram (container/poll/publish, lưu `remote_container_id` trước khi publish) (`posting/instagram.py`)
- [x] Service + tick scheduler + retry tối thiểu (`posting/service.py`, `scheduler.py`)
- [x] UI chọn tài khoản đích + đăng/hẹn giờ/lịch sử (`web/templates/accounts.html`, `web/templates/posts.html`)
- [x] Nhiều tài khoản: tick Page/IG dùng, gắn ngôn ngữ (`vi`/`en`)
- [x] Gọi `preflight.check` trước khi đăng
- [x] Test local + live (`tests/test_posting_service.py`, `tests/test_r2_live.py`, `tests/test_meta_live.py`)
- [x] Gói đăng tay (`.zip` gồm MP4 + ảnh bìa + 4 caption) (`GET /videos/{id}/manual-bundle`)

## Success Criteria

- Tiêu chí tuần 1: 1 footage -> >= 3 remix -> duyệt -> bấm đăng -> bài xuất hiện công khai trên Page và IG, có link trong app và Telegram.
- Mô phỏng mất mạng không sinh bài trùng.
- Video chưa duyệt không thể tạo post (API trả lỗi).

## Risk Assessment

- S2 hỏng -> không đạt tiêu chí tuần 1 bằng API; chuyển gói đăng tay, không cố lách.
- Meta xử lý video chậm làm poll hết giờ: coi là transient, lần retry sau hỏi lại container cũ.
- Giới hạn IG 50 hay 100 bài/24h: 5–10 video/ngày nằm dưới cả hai.
- Dễ trượt: ước 1 ngày, thực tế có thể 1.5 ngày vì lỗi quyền/Graph khó đoán.

## Security Considerations

- Token Meta trong secrets store; log che token; không đưa token vào URL log (dùng header/POST body).
- Object R2: key ngẫu nhiên 32 ký tự, tự xoá sau đăng; bucket không cho liệt kê.
- Chỉ đăng lên `accounts.enabled = 1`; test live chỉ dùng tài khoản đánh dấu thử.

## Next steps

- Phase 08 đóng gói. Phase 10 thêm tự xếp lịch + cảnh báo. Phase 11 thêm 2 adapter.
