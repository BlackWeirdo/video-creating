# Phase 02: Đồng bộ chỉ đọc + trang Quảng cáo + báo cáo Telegram

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 01](phase-01-access-and-api-spike.md) (token, phiên bản, trường thật, mẫu JSON)
- Mã liên quan: `src/videocreator/posting/meta_auth.py` (`classify_meta_error`), `src/videocreator/scheduler.py`, `src/videocreator/reports.py`, `src/videocreator/tg/handlers.py` (danh sách chủ đề)

## Overview

- Ngày: 2026-11-14
- Mô tả: app thấy mọi campaign/ad set/ad và số liệu theo ngày; trang "Quảng cáo" xem danh sách, chi tiêu, kết quả; báo cáo quảng cáo hằng ngày trong chủ đề Telegram "Báo cáo". Không có lệnh ghi nào tới Meta.
- Ưu tiên: P1
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Mức truy cập thấp: gom lượt gọi. Một lượt đồng bộ = 1 lượt đọc cấu trúc (campaign + ad set + ad bằng field expansion) + 1 lượt insights `level=ad`, `time_increment=1`, 7 ngày gần nhất (số liệu Meta còn được cập nhật lại trong vài ngày).
- Lưu theo ngày, upsert theo `(ad_id, date)`; tính lại cấp ad set/campaign bằng SQL, không gọi thêm.
- Tiền lưu dạng số nguyên theo đơn vị tài khoản (VND), theo kết quả phase 01.

## Requirements

- Migration (số kế tiếp còn trống) tạo:
  - `ad_accounts(id, external_id, name, currency, timezone, enabled)`
  - `ad_campaigns(id, external_id UNIQUE, account_id, name, objective, status, effective_status, daily_budget, lifetime_budget, managed_by_app INTEGER, video_id NULL, content_type NULL, created_at, synced_at)`
  - `ad_sets(...)`, `ad_ads(..., post_id NULL, video_id NULL)` tương tự, khoá ngoại về cha
  - `ad_insights_daily(ad_id, date, spend, impressions, reach, frequency, clicks, ctr, cpm, video_3s, thruplay, p25, p50, p75, p100, results, result_type, cost_per_result, actions_json, UNIQUE(ad_id, date))`
- Job `ads_sync` chạy 3 lần/ngày (giờ cấu hình) + nút "Đồng bộ ngay"; lỗi 17/613/80004 (giới hạn) -> dừng tới lượt sau, không thử dồn.
- Trang `/ads`: bảng campaign (trạng thái, mục tiêu, ngân sách, chi tiêu 7 ngày, kết quả, chi phí/kết quả), bấm vào xem ad set/ad và biểu đồ theo ngày.
- Báo cáo Telegram 1 lần/ngày: tổng chi, top 3 / bottom 3 ad theo chi phí/kết quả, campaign sắp hết ngân sách trọn đời.
- Thêm chủ đề Telegram "Quảng cáo" (dùng từ phase 03) theo cơ chế tạo chủ đề sẵn có.

## Architecture

```
ads/client.py     # AdsClient: get(path, fields, params) + phân trang + đọc header giới hạn; dùng classify_meta_error
ads/sync.py       # sync_account(paths) -> upsert cấu trúc + insights 7 ngày
ads/queries.py    # tổng hợp theo campaign/ad set, chi phí/kết quả
api/routes_ads.py + web/templates/ads.html
```

## Related code files

Tạo: các file trên, `migrations/0NN_ads.sql`, `tests/test_ads_sync.py`, `tests/samples/meta_ads_*.json` (từ phase 01).
Sửa: `app.py` (router + job), `scheduler.py` (lịch đồng bộ), `config.py` (`[ads]`: giờ đồng bộ, bật/tắt), `reports.py`, `tg/handlers.py` (chủ đề mới), `web/templates/base.html` (menu).

## Implementation Steps

1. Migration + `AdsClient` (chỉ GET).
2. `sync.py`: map phản hồi thật -> bảng; upsert; đánh dấu `managed_by_app = 0` cho mọi campaign hiện có.
3. Job + lịch + nút; trang `/ads`.
4. Báo cáo ngày + chủ đề Telegram.
5. Test local (SQLite thật, mẫu JSON thật từ phase 01): map đủ trường, upsert 2 lần không trùng, số liệu tổng khớp tay tính từ mẫu, tiền VND đúng đơn vị.
6. Test live (bỏ qua khi thiếu token): đồng bộ thật 1 lần, số campaign khớp Ads Manager.

## Todo list

- [ ] Migration + client
- [ ] Sync + test mẫu thật
- [ ] Job/lịch/nút
- [ ] Trang `/ads`
- [ ] Báo cáo + chủ đề Telegram
- [ ] Test live

## Success Criteria

- Sau "Đồng bộ ngay", `/ads` hiện đúng số campaign và chi tiêu 7 ngày khớp Ads Manager (lệch do múi giờ/độ trễ Meta ghi rõ).
- 3 lần đồng bộ/ngày nằm dưới giới hạn lượt gọi (đọc header).
- Không có request ghi nào (kiểm bằng grep: `ads/` không có POST ở phase này).

## Risk Assessment

- Tài khoản nhiều ad -> phân trang nhiều, chạm giới hạn: giới hạn 7 ngày + chỉ campaign hoạt động trong 30 ngày.
- Số liệu "kết quả" khác nhau theo mục tiêu: lưu `actions_json` thô để phase 03 chọn đúng chỉ số.

## Security Considerations

- Token chỉ đọc từ kho bí mật; log không in token hay URL có `access_token`.
- Trang `/ads` theo cơ chế xác thực sẵn có (`NonLocalhostBasicAuthMiddleware`).

## Next steps

- Phase 03 đánh giá trên dữ liệu đã đồng bộ.
