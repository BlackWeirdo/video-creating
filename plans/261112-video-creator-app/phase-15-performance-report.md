# Phase 15: Báo cáo hiệu quả bài đăng

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 07](phase-07-posting-facebook-instagram.md), [phase 10](phase-10-scheduling-retry-alerts.md), [phase 11](phase-11-threads-tiktok.md) (tuỳ nền tảng)
- Docs: [brainstorm mục 5](../reports/brainstorm-2026-11-12-video-creator.md)

## Overview

- Ngày: 2026-11-12
- Mô tả: thu số liệu (view, like, comment, share) của bài đã đăng, báo cáo tuần qua Telegram + trang trong UI, so sánh theo formula và theo nguồn đề xuất.
- Ưu tiên: P3 (cắt được)
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Endpoint insights và quyền của từng nền tảng CHƯA research (FB video insights, IG media insights cần `instagram_manage_insights`, Threads insights, TikTok `video.list`). Bước đầu là tra docs; nền tảng nào cần quyền/review thêm thì bỏ qua ở v1.
- Giá trị thật: biết formula nào hiệu quả để chỉnh planner và đề xuất. Không làm dashboard phân tích (YAGNI).
- Số liệu tăng dần theo thời gian -> chụp ở mốc cố định (24 giờ, 72 giờ, 7 ngày sau đăng) để so sánh công bằng.

## Requirements

- Thêm 1 hàm TUỲ CHỌN cho adapter (không sửa `Poster`):

```python
class MetricsReader(Protocol):
    def fetch_metrics(self, account: Account, external_post_id: str) -> dict  # views, likes, comments, shares (thiếu = None)
```

- Migration: `post_metrics` (id, post_id, checkpoint (`24h`/`72h`/`7d`), fetched_at, views, likes, comments, shares; UNIQUE(post_id, checkpoint)).
- Job mỗi giờ: tìm post `posted` đến mốc mà chưa có bản ghi -> fetch -> lưu. Lỗi thì thử lại lần tick sau, bỏ sau 24 giờ.
- Báo cáo tuần (thứ Hai 09:00, cấu hình được) + lệnh `/report week`: số video đăng theo nền tảng, top 3 và bottom 3 theo view 72h, trung bình theo `formula`, so sánh video từ đề xuất xu hướng với video thường.
- UI: bảng bài đăng với số liệu 3 mốc, sắp xếp được.

## Architecture

```
posting/metrics.py     # collect_due(): chọn post + mốc -> gọi fetch_metrics của adapter nếu có
posting/facebook.py, instagram.py, threads.py, tiktok.py   # thêm fetch_metrics khi API cho phép
reports.py             # weekly_summary()
scheduler.py           # job mỗi giờ + cron tuần
```

TikTok hộp nháp: không có `external_post_id` cho tới khi người dùng đăng tay -> không có số liệu; ghi rõ trong báo cáo.

## Related code files

Tạo: `src/videocreator/posting/metrics.py`, `migrations/007_post_metrics.sql`, `web/templates/performance.html`, `tests/test_metrics.py`, `tests/test_metrics_live.py`.
Sửa: 4 adapter posting, `reports.py`, `scheduler.py`, `telegram_bot.py`.

## Implementation Steps

1. Tra docs insights 4 nền tảng: endpoint, field, quyền; quyết định nền tảng nào làm được không cần review thêm.
2. Migration + `metrics.py` (logic mốc thời gian là hàm thuần nhận `now`).
3. `fetch_metrics` cho FB và IG trước; Threads/TikTok nếu quyền cho phép.
4. `weekly_summary()` + cron + lệnh.
5. Trang hiệu quả.
6. Test `-m local`: chọn đúng post đến mốc, không fetch trùng mốc, tổng hợp theo formula đúng (SQLite thật; số liệu đầu vào lấy từ bản ghi live đã lưu, không bịa).
7. Test `-m live` (CẦN bài đã đăng thật trên tài khoản người dùng từ các phase trước): fetch 1 bài FB, 1 bài IG -> có ít nhất view hoặc like là số.

## Todo list

- [ ] Tra docs insights + quyền
- [ ] Migration + thu thập theo mốc
- [ ] fetch_metrics FB, IG
- [ ] fetch_metrics Threads, TikTok (nếu được)
- [ ] Báo cáo tuần + lệnh
- [ ] UI hiệu quả
- [ ] Test local + live

## Success Criteria

- Sau 7 ngày chạy: mỗi bài FB/IG có đủ 3 mốc số liệu.
- Báo cáo tuần đến Telegram đúng giờ, nêu được formula tốt nhất/kém nhất kèm số.
- Nền tảng không lấy được số liệu hiện "không có dữ liệu", không hiện số 0 giả.

## Risk Assessment

- Quyền insights đòi App Review -> chỉ còn FB hoặc không có gì. Khi đó phase rút xuống: báo cáo số lượng đăng + link, người dùng tự xem số trong app nền tảng.
- Mẫu nhỏ (vài chục video) -> so sánh formula dễ nhiễu; báo cáo ghi số mẫu cạnh mỗi trung bình, không tự động đổi chiến lược.
- Là phase cuối cùng (tuần 4) và là phase bị cắt trước tiên nếu thiếu giờ.

## Security Considerations

- Chỉ đọc số liệu bài của chính mình; không thêm quyền ghi.
- Báo cáo gửi qua cùng allowlist Telegram.

## Next steps

- Hết plan. Việc sau (ngoài phạm vi): khung giờ đăng riêng từng nền tảng dựa trên số liệu; template Remotion; nguồn xu hướng TikTok.
