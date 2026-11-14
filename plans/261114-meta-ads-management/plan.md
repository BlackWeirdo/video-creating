# Kế hoạch: quản lý quảng cáo Meta (Facebook/Instagram) do AI đề xuất, người duyệt

Ngày: 2026-11-14. Trạng thái: chưa bắt đầu, chưa viết mã. Gốc repo: `c:\Project Video Creator\`.
Nguồn: [research 01](research/researcher-01-meta-marketing-api-2026.md), [plan app](../261112-video-creator-app/plan.md), [đặc tả](../../docs/video-creator-spec.md), [CLAUDE.md](../../CLAUDE.md).

## Mục tiêu

App đọc được mọi campaign trong tài khoản quảng cáo của chủ, tự đánh giá hiệu quả, tự đề xuất bật/tắt/tăng giảm ngân sách, và tự đề xuất cách lên campaign cho từng video (mục tiêu, ngân sách, đối tượng, vị trí hiển thị, thời gian, nội dung chữ). AI phân tích qua gói thuê bao (`claude_cli`, dự phòng Gemini) theo bộ định tuyến sẵn có; API Meta miễn phí, chỉ tiền quảng cáo là tốn.

## Nguyên tắc cứng (vì đây là tiền thật)

1. **AI chỉ đề xuất. Mọi thao tác làm tốn tiền hoặc đổi tiền (tạo, bật, tăng ngân sách) cần một người duyệt bấm nút** trên giao diện hoặc Telegram. Ghi lại ai duyệt.
2. Campaign do app tạo luôn ở trạng thái **PAUSED**; bật là một lần duyệt riêng.
3. **Trần trong mã, AI không vượt được**: ngân sách/ngày mỗi campaign, tổng/ngày mọi campaign app quản lý, số campaign đang chạy, thời gian chạy tối đa, bước tăng ngân sách tối đa (20%/lần). Vượt trần -> từ chối trước khi gọi API.
4. Campaign tạo tay trong Ads Manager: app được quản lý đầy đủ theo quyết định của chủ (câu 4), nhưng vẫn qua duyệt và trần như campaign do app tạo.
5. Chỉ API chính thức (Marketing API), token system user trong kho bí mật; không công cụ quảng cáo bên thứ ba, không tự động hoá trình duyệt.
6. Đọc lại trạng thái từ Meta sau mỗi lệnh ghi; không tin là đã đổi khi chưa đọc lại.

## Các phase

| # | Phase | Ước lượng | Trạng thái | Tiến độ |
|---|---|---|---|---|
| 01 | [Kiểm chứng quyền + API (cổng vào)](phase-01-access-and-api-spike.md) | 1 ngày + chờ chủ chuẩn bị tài khoản | Chờ chủ | 0% |
| 02 | [Đồng bộ chỉ đọc + trang Quảng cáo + báo cáo Telegram](phase-02-readonly-sync-and-reports.md) | 1–1.5 ngày | Chưa bắt đầu | 0% |
| 03 | [Đánh giá hiệu quả + đề xuất hành động](phase-03-evaluation-and-recommendations.md) | 1.5 ngày | Chưa bắt đầu | 0% |
| 04 | [Thực thi có duyệt: bật/tắt, ngân sách, trần](phase-04-approved-execution.md) | 1–1.5 ngày | Chưa bắt đầu | 0% |
| 05 | [Đề xuất và lên campaign theo từng video](phase-05-content-based-campaign-proposals.md) | 2 ngày | Chưa bắt đầu | 0% |
| 06 | [Học từ kết quả (đã bỏ phần tự tắt theo câu 5)](phase-06-learning-loop-and-guard.md) | 0.5–1 ngày | Chưa bắt đầu | 0% |
| 07 | [Chạy thật, ma trận xung đột, tài liệu](phase-07-verification-and-docs.md) | 1 ngày + vài ngày chờ số liệu thật | Chưa bắt đầu | 0% |

Tổng: 8–9 ngày làm việc, không đệm, chưa tính vài ngày campaign chạy thật mới đánh giá được. Tài khoản đã sẵn sàng (câu 2), nên không phải chờ Meta. Thứ tự: 01 -> 02 -> 03 -> 04 -> 05 -> 06 -> 07. Phase 02–03 chỉ đọc, an toàn để chạy sớm trên tài khoản thật.

## Luồng chính

```
Meta Ads (đọc)  --sync 3 lần/ngày-->  ad_* tables + ad_insights_daily
        |                                   |
        |                     đánh giá (luật trong mã) + AI giải thích (writer, claude_cli)
        |                                   v
        |                         ad_actions (proposed) --Telegram "Quảng cáo" / UI--> người duyệt
        |                                   v
        +<------ ghi qua Marketing API (đã duyệt, qua trần) <-- executed / rejected
video đã duyệt + post_metrics + phân tích xu hướng --> đề xuất campaign theo loại nội dung (phase 05)
```

## Quyết định chính

- Module mới `src/videocreator/ads/` (client, sync, evaluate, propose, execute), phiên bản Graph riêng `ADS_GRAPH_API_VERSION`, không đụng `posting/`.
- Bảng mới: `ad_accounts`, `ad_campaigns`, `ad_sets`, `ad_ads`, `ad_insights_daily`, `ad_actions`. Migration lấy **số kế tiếp còn trống lúc thực hiện** (plan TikTok `261114-tiktok-trend-scanning` cũng giữ số 010; ai làm trước dùng 010, sau dùng 011).
- Đánh giá = luật trong mã (ngưỡng minh bạch, có "chưa đủ dữ liệu") + AI viết lời giải thích và gợi ý sửa; AI không tự đặt kết luận bật/tắt vượt luật.
- Đề xuất theo nội dung = "sách chiến thuật" cố định trong mã (loại nội dung -> mục tiêu, KPI, đối tượng, vị trí) + AI điều chỉnh theo số liệu thật của chính tài khoản.
- Dùng Advantage+ của Meta (ngân sách cấp campaign, đối tượng và vị trí tự động) làm mặc định: Meta tối ưu miễn phí, app không tự xây bộ tối ưu.
- Telegram: chủ đề mới "Quảng cáo" cho đề xuất + nút duyệt; báo cáo ngày vào chủ đề "Báo cáo" sẵn có.

## Giới hạn nói thẳng

- Không cam kết "hiệu quả cao nhất": AI chỉ tối ưu dựa trên số liệu thật của tài khoản; tuần đầu thiếu dữ liệu nên đề xuất dựa trên sách chiến thuật chung.
- Meta đổi API thường xuyên (2026 đã đổi tên mức truy cập, bỏ ASC cũ, bỏ một số chỉ số). Mỗi đợt nâng phiên bản cần chạy lại test live.
- Mức truy cập thấp giới hạn số lượt gọi: đồng bộ vài lần/ngày, không theo thời gian thực.

## Quyết định của chủ (2026-11-14)

| # | Câu hỏi | Trả lời | Ảnh hưởng tới kế hoạch |
|---|---|---|---|
| 1 | Khách mua qua đâu | Nhắn tin Messenger/Instagram **và** website có Meta Pixel | Sách chiến thuật có cả mục tiêu nhắn tin (cuộc trò chuyện) và Doanh số (mua hàng, ROAS). Phase 01 kiểm Pixel nhận sự kiện mua. |
| 2 | Tài khoản | Đủ cả: Business Manager, tài khoản quảng cáo, thanh toán, doanh nghiệp đã xác minh | Phase 01 làm được ngay khi bắt đầu; không chờ Meta xác minh. |
| 3 | Trần mỗi campaign | **500.000đ/ngày** | `max_daily_budget_per_campaign = 500000` |
| 3b | Trần tổng | **5.000.000đ/ngày** | `max_total_daily_budget = 5000000`, tính trên MỌI campaign app quản lý, gồm cả campaign tạo tay (xem câu 4) |
| 4 | Campaign tạo tay | **Được quản lý đầy đủ** (tắt, bật, đổi ngân sách) | `manage_external = true`. Vẫn bắt buộc duyệt + trần. Campaign tạo tay đang có ngân sách > 500.000đ/ngày: app không được tăng thêm, chỉ được giảm/tắt; được giữ nguyên mức hiện có. |
| 5 | Tự tắt không chờ duyệt | **Không, luôn chờ duyệt** | Bỏ phần "tự tắt bảo vệ" khỏi phase 06 (YAGNI). Đề xuất tắt gấp được gửi Telegram với mức ưu tiên cao + nhắc lại sau 2 giờ nếu chưa duyệt. |
| 6 | Người duyệt | **Danh sách riêng, ít người hơn** | Cấu hình mới `ads.approver_user_ids` (Telegram); người duyệt video vẫn xem thẻ nhưng bấm duyệt bị từ chối. |
