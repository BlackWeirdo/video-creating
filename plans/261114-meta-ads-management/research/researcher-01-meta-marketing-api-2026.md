# Research 01: Meta Marketing API, tình trạng cuối 2026

Ngày: 2026-11-14. Nguồn: 2 lượt tìm kiếm web (tóm tắt của công cụ, chưa mở từng trang gốc). Điểm nào ghi [chưa xác minh] phải kiểm ở phase 01 trước khi viết mã.

## Quyền truy cập

- 2026-05-04 Meta đổi tên "Ads Management Standard Access" thành "Marketing API Access Tier": mức cũ Standard -> **Limited**, Advanced -> **Full**. Ngưỡng lên Full: 500 lượt gọi / 15 ngày, tỉ lệ lỗi < 15%. Nguồn: https://developers.meta.com/blog/updates-to-ads-management-standard-access-feature/
- Quản lý tài khoản quảng cáo **của chính mình** (mình là admin) dùng được ở mức thấp, không cần App Review. Quản lý tài khoản của doanh nghiệp khác mới cần Full + App Review. Nguồn: https://climentmedia.com/learn/meta-marketing-api-access/
- Business Verification bắt buộc cho Full và cho việc tạo tài khoản quảng cáo bằng API; không bắt buộc cho tài khoản của mình ở mức Limited [chưa xác minh trên tài liệu gốc].
- Token: thường dùng system user token của Business Manager với quyền `ads_management`, `ads_read` [chưa xác minh trên tài liệu gốc].

## Giới hạn gọi

- Mức thấp: 60 điểm (đọc = 1 điểm), so với 9.000 ở mức cao. `ads_management` theo tài khoản quảng cáo: 300/giờ ở mức thấp, 100.000/giờ ở mức Full. Nguồn: https://developers.facebook.com/documentation/ads-commerce/marketing-api/overview/rate-limiting
- Hệ quả: đồng bộ phải gom (batch, chọn `fields`, insights theo cấp account với `level=ad`), chạy vài lần/ngày, không quét liên tục.

## Cấu trúc campaign

- Từ v25.0 (2026-02-18), rồi mọi phiên bản (2026-05-19): không tạo/nhân bản/sửa được campaign Advantage+ Shopping (ASC) và Advantage+ App kiểu cũ. Nguồn: https://ppc.land/meta-deprecates-legacy-campaign-apis-for-advantage-structure/
- Advantage+ giờ là "một campaign thường bật đủ 3 thứ": ngân sách cấp campaign, Advantage+ audience, placement tự động (không loại trừ placement). Nguồn: https://ppc.land/meta-launches-unified-api-structure-for-advantage-campaigns/
- v26.0 (khoảng 09/2026): campaign kiểu cũ còn lại bị chặn sửa / có thể bị tạm dừng; nguồn không thống nhất. Nguồn: https://www.kitchn.io/blog/meta-marketing-api-q2-2026-update
- App hiện ghim `GRAPH_API_VERSION = "v22.0"` (`posting/meta_auth.py`). Phần quảng cáo cần phiên bản mới hơn, riêng hằng số; chọn bản ở phase 01.

## Chưa tìm được, phải kiểm ở phase 01

1. Tài khoản quảng cáo sandbox (thử tạo campaign không tốn tiền) còn tồn tại và tạo thế nào.
2. Danh sách objective hiện hành (ODAX: `OUTCOME_AWARENESS`, `OUTCOME_TRAFFIC`, `OUTCOME_ENGAGEMENT`, `OUTCOME_LEADS`, `OUTCOME_SALES`, `OUTCOME_APP_PROMOTION`) và tổ hợp `optimization_goal` / `destination_type` cho quảng cáo nhắn tin Messenger.
3. Đơn vị `daily_budget` với tiền VND (đơn vị nhỏ nhất; VND không có số lẻ) và ngân sách tối thiểu/ngày.
4. Dùng bài đã đăng trên Page làm quảng cáo (`object_story_id`) có còn được với Reels không.
5. Trường insights hiện hành cho video (ThruPlay, p25–p100, 3 giây) sau đợt "metric retirements" 2026.
6. Có endpoint gợi ý tối ưu của chính Meta (recommendations / opportunity score) đọc được qua API không.

## Câu hỏi chưa giải quyết

- Như mục "Chưa tìm được". Tất cả là cổng vào phase 01, không đoán khi viết mã.
