# Kế hoạch: nguồn Facebook (Fanpage/Profile) + dán link Reel Meta vào luồng xu hướng

Ngày: 2026-11-14. Trạng thái: xong, chủ đã duyệt 2026-11-14 (đặc tả: `FR-TRD-02`, `FR-TRD-10`). Kiểm chứng: 41 test local + 1 test live (facebook.com thật), toàn bộ bộ test 129 đạt; chạy thật trọn chuỗi trong thư mục tạm (đọc Reel -> tải -> rea-video -> AI phân tích -> 3 đề xuất, 155 giây); máy chủ thật đã nâng DB lên phiên bản 10 (sao lưu `backups/pre-010_app.db`), bot đã nạp lệnh `/link`. Gốc repo: `c:\Project Video Creator\`.
Liên quan: [plan TikTok](../261114-tiktok-trend-scanning/plan.md) (phase 03 dán link, migration 010), [plan app phase 12–13](../261112-video-creator-app/plan.md), [đặc tả](../../docs/video-creator-spec.md) `FR-TRD-*`, `BR-REF-*`.

## Yêu cầu của chủ

Ngoài Meta Ad Library: quét Reels đang lên xu hướng, hoặc điền tay nguồn Facebook (Profile, Fanpage) để lấy tư liệu.

## Sự thật đã thử thật (2026-11-14, yt-dlp 2026.10.26, không đăng nhập)

| Việc | Kết quả |
|---|---|
| Liệt kê Reels/video của Fanpage (`/<page>/reels/`, `/<page>/videos/`) | KHÔNG được: `Unsupported URL` |
| Đọc 1 Reel / video Page / link watch công khai | Được: id, tác giả, ngày đăng, thời lượng, lượt xem; KHÔNG có like/comment (Reel có "9.9K views · 340 reactions" trong tiêu đề) |
| Tải file video Facebook bằng bộ tải sẵn có | Được, giữ cả tiếng (VP9 1080 + AAC); Reel mẫu vốn không có tiếng |
| Đọc 1 bài Instagram công khai | Được (bài nhiều ảnh/video trả về dạng danh sách) |

Mẫu thật: `tests/samples/ytdlp_facebook_*.json`, `tests/samples/ytdlp_instagram_post.json`.

## Giới hạn nói thẳng

- "Reels đang lên xu hướng" trên Facebook: Meta không có API nào; không có cách tự động hợp lệ. Instagram có "top media theo hashtag" (nguồn `ig_hashtag` đã có mã, chờ token Meta) là cách chính thức gần nhất.
- Fanpage của người khác: tự quét cần quyền Page Public Content Access, Meta xét duyệt app (doanh nghiệp đã xác minh nên nộp được; chờ duyệt). Chưa làm ở đây.
- Profile cá nhân: không có API nào (Meta khoá từ 2018). Chỉ dán link từng video.

## Làm trong đợt này

1. Migration `010_watch_items_more_sources.sql`: `watch_items.source` nhận thêm `tiktok`, `facebook` (đúng SQL đã thiết kế ở plan TikTok phase 01, để không phải dựng lại bảng lần hai).
2. Nguồn `facebook` trong Watchlist, loại `page` (Fanpage) / `account` (Profile); chuẩn hoá link; trạng thái "chưa bật tự động" kèm hướng dẫn; nút "Mở trang".
3. `/watchlist/add` kiểm nguồn và loại (sai -> báo lỗi, không còn lỗi 500).
4. Dán link video Facebook / Instagram trên `/trends` và lệnh Telegram `/link <url>`: đọc số liệu (yt-dlp), lưu thành bài xu hướng có cờ `pinned`, xếp job `analyse_trend` (tải + rea-video + phân tích) rồi tạo đề xuất; bài `pinned` được ưu tiên khi chọn đề xuất. Trần 20 link/ngày.
5. Test bằng mẫu thật, test live có cổng biến môi trường, chạy thật trên máy chủ.

## Để sau (không làm đợt này)

- Tự quét Fanpage qua Graph API khi app có quyền Page Public Content Access.
- Chạy thật nguồn `ig_hashtag` / `ig_discovery` khi có token Meta (plan app phase 01 S2/S3).

## Đợt 2 (2026-11-14): Apify cho dữ liệu xu hướng

Chủ quyết định: (1) đổi quy tắc `BR-REF-04` cho dữ liệu xu hướng, dùng Apify; (2) dùng gói miễn phí $5/tháng trước, hiệu quả thì nâng tối đa $20; (3) quét cả Profile cá nhân. Token lưu trong kho bí mật (`APIFY_API_TOKEN`), không ghi vào mã hay tài liệu.

- `trends/apify.py`: 5 nguồn Apify giữ tên cũ (`tiktok`, `ig_hashtag`, `ig_discovery`, `facebook`, `ad_library`); `build_trend_sources` dùng chúng khi có token. Đặc tả `FR-TRD-11`.
- Trần chi: đọc mức dùng tài khoản trước mỗi lần chạy (`trends.apify_monthly_usd`, mặc định 5) + trần 0,5 USD mỗi lần chạy (TikTok không nhận trần thấp hơn); thử lại lỗi 5xx.
- Chạy thật trên dữ liệu thật: lượt quét đủ 5 nguồn, không lỗi, khoảng $0,11–0,13 mỗi lượt với 4 mục theo dõi × 10 kết quả. Tổng đã dùng sau thử nghiệm: $0,55/$5.
- Sửa sau lần chạy thật: Ad Library khớp nguyên cụm (khớp từng chữ ra quảng cáo không liên quan); TikTok từ khoá lọc video trong tháng (tìm "Top" trả video cũ, bị bộ lọc 30 ngày loại hết); thử lại khi Apify trả 502.
- Test: `tests/test_trends_apify.py` trên đầu ra Apify thật (`tests/samples/apify_*.json`), 1 test live có cổng `RUN_LIVE_APIFY`.

## Câu hỏi chưa giải quyết

- Ad Library VN với cụm "trang sức bạc": không có quảng cáo video nào chạy từ 30 ngày. Chủ nên thêm mã Page đối thủ (loại `page`) hoặc cụm từ khác.

- Lượt xem Reel: yt-dlp trả `view_count` khác số trong tiêu đề trang (427 so với 9.9K). App lấy số lớn hơn; chưa rõ số nào Facebook coi là "lượt xem".
