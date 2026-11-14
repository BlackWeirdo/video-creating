# Phase 05: Bật thật Instagram, Facebook Reels, quảng cáo

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: tài khoản và token Meta của chủ (S2, S3, S6 của [phase 01 plan app](../261112-video-creator-app/phase-01-verification-spikes.md)); [phase 04](phase-04-fair-share-across-platforms.md) (nhóm nền tảng)
- Docs: [phase 12 plan app](../261112-video-creator-app/phase-12-trend-sources.md), [research 01 plan app](../261112-video-creator-app/research/researcher-01-social-and-trend-apis.md) mục 5–7
- Mã đã có, CHƯA TỪNG CHẠY THẬT: `src/videocreator/trends/ig_discovery.py`, `ig_hashtag.py`, `ad_library.py`

## Overview

- Ngày: 2026-11-14
- Mô tả: chủ cần xu hướng của cả Instagram, Facebook Reels và quảng cáo. Ba bộ đọc Instagram/quảng cáo đã viết từ tài liệu nhưng chưa gọi API thật lần nào; Facebook Reels chưa có bộ đọc. Phase này chạy thật từng cái, sửa chỗ sai, và trả lời bằng thử nghiệm xem Facebook Reels quét tự động được không.
- Ưu tiên: P2 (BỊ CHẶN bởi việc chủ cấp tài khoản Meta; các phase khác không chờ phase này)
- Trạng thái triển khai: chưa bắt đầu, chờ chủ
- Trạng thái review: chưa review

## Key Insights

Khả năng thật của từng nền tảng (nói thẳng):

| Nền tảng | Quét tự động | Điều kiện | Giới hạn |
|---|---|---|---|
| YouTube Shorts | Có, đang chạy | Khoá API (đã có) | Theo từ khoá + kênh |
| TikTok | Có sau phase 01 | Không cần gì | CHỈ theo tài khoản; không hashtag/từ khoá/tab Đề xuất |
| Instagram | Có mã, chưa chạy | Tài khoản Instagram Business nối với Page + token Meta | Theo tài khoản brand (Business Discovery) và tối đa ~30 hashtag/7 ngày; có thể cần Meta duyệt quyền |
| Facebook Reels | CHƯA CÓ | Quyền "Page Public Content Access" (đọc nội dung công khai của Page khác), phải qua Meta App Review | Chưa kiểm chứng API có trả Reels + lượt xem của Page người khác không |
| Quảng cáo Meta | Có mã, chưa chạy | Xác minh danh tính để lấy token Ad Library | CHỈ quảng cáo có phân phối ở EU; không có số chi tiêu; đối thủ chỉ chạy ở Việt Nam sẽ không có |
| Quảng cáo TikTok | Không | API chỉ cho nhà nghiên cứu | Xem tay ở Creative Center rồi dán link (phase 03) |

- Bài học ở dự án này: mã viết từ tài liệu, chưa chạy thật, đã sai nhiều lần (MoneyPrinterTurbo, chỉ số `plays` của Instagram). Coi ba bộ đọc Meta là CHƯA XONG cho tới khi có 1 lần gọi thật.
- Trong lúc chờ token: Instagram / Facebook / quảng cáo vẫn vào app được bằng dán link (phase 03) hoặc nạp file tay. Phase này chỉ thêm phần TỰ ĐỘNG.
- Facebook Reels: nếu thử nghiệm cho thấy cần App Review dài ngày hoặc API không trả số liệu -> KHÔNG viết bộ đọc; Facebook giữ ở mức dán link. Không dùng yt-dlp để liệt kê Page (bản ghim không có bộ đọc danh sách Page), không scrape.

## Requirements

- Mỗi bộ đọc Meta: 1 lần gọi thật với 1 mục theo dõi thật, >= 1 bài đủ trường bắt buộc, số liệu khớp khi mở bài gốc.
- Sửa mọi chỗ lệch với API thật (tên trường, phiên bản Graph API, quyền). Mỗi chỗ sửa kèm test dùng phản hồi thật đã ghi lại (xoá token khỏi mẫu).
- Thử nghiệm Facebook Reels: ghi kết quả vào báo cáo; chỉ viết `trends/facebook.py` khi thử nghiệm đạt. Migration 010 (phase 01) đã cho phép sẵn `source = 'facebook'` trong `watch_items`, không cần migration nữa.
- Bộ đọc Facebook (nếu làm): `name = "facebook"`, `kinds = ("page",)`, cùng khuôn với `ig_discovery.py`; khoá số liệu `views, likes, comments`; nằm trong nhóm `facebook` của phase 04.
- Nguồn nào không bật được: trang Watchlist hiện đúng lý do bằng tiếng Việt (đã có cơ chế), lần quét không gãy.

## Architecture

```
(đã có)  trends/ig_discovery.py   GET /{ig_id}?fields=business_discovery.username(X){media{...}}
(đã có)  trends/ig_hashtag.py     ig_hashtag_search -> /{hashtag_id}/top_media ; bộ đếm 30/7 ngày
(đã có)  trends/ad_library.py     GET /ads_archive ...
(có điều kiện) trends/facebook.py GET /{page_id}/video_reels hoặc /{page_id}/videos + insights   # tên endpoint phải xác nhận ở bước 4
```

## Related code files

Sửa (theo kết quả chạy thật): `src/videocreator/trends/ig_discovery.py`, `ig_hashtag.py`, `ad_library.py`, `tests/test_trends_live.py`
Tạo: `plans/261114-tiktok-trend-scanning/reports/05-meta-sources-live-results.md`; `tests/samples/meta_*.json` (phản hồi thật, đã xoá token); có điều kiện: `src/videocreator/trends/facebook.py` + dòng đăng ký trong `scan.py` + lựa chọn trên `watchlist.html`
Không sửa: `scan.py` ngoài 1 dòng đăng ký; `rank.py`.

## Implementation Steps

1. **Việc của chủ** (chặn cả phase): kết nối Page + Instagram Business trong app (S2, S3); làm xác minh danh tính Ad Library (S6); cho 2–3 tài khoản Instagram brand, 2–3 hashtag, 2–3 Page Facebook, 2–3 Page quảng cáo để theo dõi.
2. Instagram Business Discovery: thêm 1 tài khoản brand, chạy `fetch` thật, so số liệu với bài gốc. Kiểm quyền `instagram_manage_insights` / `instagram_basic` thực tế cần gì; ghi lại lỗi quyền nguyên văn.
3. Instagram Hashtag: 1 hashtag, kiểm bộ đếm 30 hashtag/7 ngày tăng đúng.
4. Ad Library: 1 Page có quảng cáo ở EU; kiểm `days_running`, `eu_reach`, bộ lọc >= 30 ngày. Thử thêm 1 Page chỉ chạy ở Việt Nam để xác nhận kết quả rỗng (ghi vào hướng dẫn cho chủ).
5. Thử nghiệm Facebook Reels (không viết mã sản phẩm): bằng token đang có, gọi thử endpoint Reels/video của 1 Page công khai KHÔNG thuộc chủ. Ghi: có trả dữ liệu không, có lượt xem không, lỗi quyền gì, App Review đòi gì và mất bao lâu. Quyết định làm / không làm cùng chủ.
6. Nếu bước 5 đạt: viết `trends/facebook.py`, đăng ký, thêm lựa chọn Watchlist, test bằng phản hồi thật.
7. Thêm test live cho từng bộ đọc vào `tests/test_trends_live.py` (bỏ qua khi thiếu token, theo khuôn sẵn có).
8. Một lần "Quét ngay" có đủ các nguồn đã bật; kiểm phân suất của phase 04 hoạt động với dữ liệu thật nhiều nền tảng.

## Todo list

- [ ] Chủ cấp tài khoản/token Meta + danh sách theo dõi
- [ ] Business Discovery chạy thật
- [ ] Hashtag chạy thật
- [ ] Ad Library chạy thật
- [ ] Thử nghiệm Facebook Reels + quyết định
- [ ] (có điều kiện) `trends/facebook.py`
- [ ] Test live từng bộ đọc
- [ ] Một lần quét đủ nguồn, kiểm phân suất

## Success Criteria

- Mỗi bộ đọc Meta: hoặc có bài thật trên `/trends`, hoặc có dòng "chưa bật: <lý do thật>" kèm việc chủ cần làm. Không cái nào ở trạng thái "chưa biết".
- Facebook Reels có câu trả lời dứt khoát: quét tự động được (và đã làm) hoặc chỉ dán link (và vì sao).
- Lần quét có >= 3 nền tảng: file tham khảo và đề xuất trải đều theo phase 04.

## Risk Assessment

- Meta đòi App Review cho quyền đọc số liệu Instagram hoặc nội dung Page công khai -> chờ nhiều ngày tới nhiều tuần, ngoài tầm kiểm soát. Khi đó nền tảng ấy chạy bằng dán link.
- Xác minh danh tính Ad Library chưa xong -> nguồn quảng cáo chưa bật.
- Đối thủ chỉ chạy quảng cáo ở Việt Nam -> Ad Library không có; giới hạn của Meta, không sửa được.
- Ước lượng: 4–6 giờ cho 3 bộ đọc đã có; thêm 3–4 giờ nếu làm Facebook; KHÔNG tính thời gian chờ Meta.

## Security Considerations

- Token Meta nằm trong kho bí mật của app; mẫu test và báo cáo phải xoá token, id tài khoản quảng cáo, và tham số chữ ký trong URL.
- Chỉ đọc số liệu công khai qua API chính thức, đúng quyền được cấp; lỗi 613/429 -> dừng nguồn tới lần quét sau (cơ chế sẵn có).
- Không scrape, không dùng tài khoản cá nhân để đọc thay API.

## Next steps

- Phase 06: kiểm chứng toàn chuỗi và cập nhật tài liệu (không chờ phase này; phần Meta được kiểm bổ sung khi có token).
