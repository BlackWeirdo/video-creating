# Phase 10: Lên lịch tự động + retry + cảnh báo

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 07](phase-07-posting-facebook-instagram.md)
- Docs: [brainstorm mục 6, 7](../reports/brainstorm-2026-11-12-video-creator.md)

## Overview

- Ngày: 2026-11-12
- Mô tả: video được duyệt tự vào khung giờ đăng kế tiếp; cảnh báo token sắp hết hạn; báo cáo ngày qua Telegram; hoàn thiện xử lý lỗi đăng.
- Ưu tiên: P1
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Cơ chế tick + `posts.scheduled_at` đã có từ phase 07; phase này chỉ thêm hàm xếp chỗ, không thêm hạ tầng.
- Mục tiêu sau tuần 2: >= 5 video/ngày đúng lịch, thao tác tay duy nhất là duyệt.
- Múi giờ: lưu UTC trong DB, khung giờ cấu hình theo `Asia/Ho_Chi_Minh` (đặt trong config).

## Requirements

- Config khung giờ:

```toml
[schedule]
timezone = "Asia/Ho_Chi_Minh"
auto = true
slots = ["08:00", "11:30", "15:00", "19:00", "21:00"]   # mặc định chung; ghi đè được theo từng tài khoản trong trang tài khoản (cột `accounts.slots_json`)
```

- Khi `approve()` và `auto = true`: với mỗi tài khoản đã chọn lúc duyệt (`videos.target_accounts_json`, chỉ tài khoản `enabled`), tạo `post` ở khung giờ trống sớm nhất (1 video / khung / tài khoản); video -> `scheduled`.
- UI lịch: bảng theo ngày, đổi giờ, huỷ post chưa đăng.
- Retry (hoàn thiện phase 07): post `failed` có nút "Thử lại" (UI + nút Telegram); lỗi permanent kèm hướng dẫn ngắn (ví dụ "token hết hạn: vào Settings kết nối lại").
- Post trễ quá 6 giờ so với `scheduled_at` (máy chủ tắt): KHÔNG tự đăng bù, chuyển `failed` lý do `missed` và hỏi người dùng qua Telegram (tránh xả 5 video cùng lúc).
- Sao lưu (bổ sung khi rà soát 2026-11-13): job mỗi đêm chép `app.db` (qua `sqlite3` backup API) + `config.toml` vào `backups/`, giữ 14 bản; lỗi sao lưu báo Telegram. `secrets.bin` không nằm trong bản sao lưu tự động (dùng xuất cấu hình có mật khẩu ở phase 08).
- Dọn đĩa: thư mục `work/` của video đã xong xoá ngay; bản master của video đã đăng giữ `retention.output_days` (mặc định 90) rồi xoá file, giữ bản ghi; footage gốc KHÔNG bao giờ tự xoá; cảnh báo Telegram khi ổ đĩa còn dưới 10 GB.
- Cảnh báo token: job mỗi ngày, `token_expires_at` còn < 7 ngày -> Telegram.
- Báo cáo ngày (giờ cấu hình, mặc định 21:30): đã đăng / lỗi / đang chờ duyệt / lịch ngày mai / chi phí AI. Lệnh `/report` trả cùng nội dung.

## Architecture

```
posting/slots.py     # next_free_slot(account_id, now) -> datetime (hàm thuần + 1 truy vấn)
posting/service.py   # thêm xử lý missed, retry thủ công
approvals.py         # sau approve: nếu auto -> slots + tạo posts
reports.py           # daily_summary() -> str
scheduler.py         # thêm 2 job cron: token check, daily report
```

## Related code files

Tạo: `src/videocreator/posting/slots.py`, `reports.py`, `web/templates/schedule.html`, `tests/test_slots.py`, `tests/test_reports.py`.
Sửa: `approvals.py`, `posting/service.py`, `scheduler.py`, `telegram_bot.py` (`/report`, nút thử lại), `config.py`, `api/routes_posting.py`.

## Implementation Steps

1. `slots.py`; xử lý qua ngày, múi giờ bằng `zoneinfo` (thêm `tzdata` cho Windows).
2. Nối vào `approve()`.
3. Xử lý `missed` + retry thủ công.
4. `reports.py` + 2 job cron + `/report`.
5. Trang lịch.
6. Test `-m local` (SQLite thật, thời gian truyền vào dạng tham số, không patch đồng hồ): 7 video duyệt liên tiếp với 5 khung -> 5 hôm nay, 2 ngày mai, không trùng khung; post trễ 7 giờ -> `missed`; báo cáo đếm đúng.
7. Checklist tay: chạy 1 ngày thật với 5 video trên tài khoản thử, đối chiếu giờ đăng.

## Todo list

- [ ] Xếp khung giờ
- [ ] Tự tạo post khi duyệt
- [ ] missed + thử lại
- [ ] Sao lưu DB hằng đêm + dọn đĩa + cảnh báo đầy đĩa
- [ ] Cảnh báo token
- [ ] Báo cáo ngày + `/report`
- [ ] UI lịch
- [ ] Test local + chạy thử 1 ngày

## Success Criteria

- 1 ngày chạy thật: 5 video đăng đúng khung (lệch < 2 phút), người dùng chỉ bấm duyệt.
- Tắt máy chủ qua 1 khung giờ rồi bật lại sau 7 giờ: không đăng bù, có tin nhắn hỏi.
- Báo cáo 21:30 đến đúng giờ, số liệu khớp UI.

## Risk Assessment

- Máy chủ là PC hay ngủ/tắt -> lỡ lịch. Giảm thiểu: báo `missed`; khuyến nghị tắt sleep. Máy chủ đã chốt là PC Windows bật 24/7 (2026-11-12): `docs/install.md` ghi các bước tắt sleep/hibernate, tự chạy app khi Windows khởi động, và tắt tự khởi động lại của Windows Update trong giờ đăng.
- Khung giờ mặc định giống nhau cho mọi tài khoản có thể không tối ưu reach: người dùng đặt khung riêng từng tài khoản bằng `accounts.slots_json`; chỉnh theo số liệu khi có phase 15.
- 2–3 tài khoản mỗi nền tảng x 5–10 video/ngày: nếu số video duyệt vượt số khung của 1 tài khoản thì dồn sang ngày sau; báo cáo ngày ghi số video đang xếp hàng quá 2 ngày.

## Security Considerations

- Nút "Thử lại" trên Telegram qua cùng allowlist.
- Báo cáo không chứa token/đường dẫn nội bộ.

## Next steps

- Phase 11 thêm Threads, TikTok vào cùng cơ chế.
