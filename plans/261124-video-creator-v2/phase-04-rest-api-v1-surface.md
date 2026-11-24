# Phase 04 (Đợt 1): Hoàn thiện Lớp JSON REST API `/api/v1/*` cho toàn bộ tính năng Đợt 1

## Context links
- Plan cha: [plan.md](plan.md)
- Đặc tả: [docs/video-creator-v2-spec.md](../../docs/video-creator-v2-spec.md) (Mục 3.1)
- Phụ thuộc: [Phase 01](phase-01-multi-workspace-and-dual-lane-queue.md), [Phase 02](phase-02-video-style-engine-and-qc.md), [Phase 03](phase-03-channels-youtube-and-publish-packs.md)

## Mục tiêu
Hoàn chỉnh toàn bộ bề mặt REST API JSON (`/api/v1/*`) theo `workspace_id` và chuẩn phản hồi thống nhất (Pydantic schemas + HTTP status codes + phân trang), phục vụ giao diện Next.js 15 ở Phase 05 mà vẫn giữ các route HTMX V1 chạy bình thường.

## Phạm vi Công việc
1. **Nhóm Endpoint Quản trị Tài nguyên theo Workspace**:
   - `products`, `footage`, `shots`, `assets` (nhạc nền, SFX, cảnh phụ), `voices` (catalog + test TTS preview).
   - Phục vụ file media an toàn qua `/files/*` (thumbnail, footage, output MP4, cover).
2. **Nhóm Endpoint Sản xuất & Style**:
   - `videos`: danh sách, lọc trạng thái/workspace, tạo plan, sửa lời/shot, dựng (`render`), dựng lại theo style (`restyle`), chấm điểm QC/Vision, xem trước phụ đề.
   - `styles`: CRUD Video Style Presets.
   - `studio`: phiên Studio Remotion theo workspace (tạo session, xác nhận kịch bản, sửa prompt).
3. **Nhóm Endpoint Xu hướng & Đề xuất**:
   - `trends`: watchlist, quét thủ công, dán link, xem kết quả phân tích `rea-video`, danh sách đề xuất và nút chuyển đổi thành video plan.
4. **Nhóm Endpoint Duyệt, Lịch đăng, Tài khoản & Hệ thống**:
   - `approvals`: duyệt đơn lẻ, duyệt hàng loạt (`bulk-approve`), từ chối, tải gói `.zip`.
   - `accounts` & `oauth`: kết nối/ngắt kết nối FB, IG, Threads, TikTok, YouTube; cấu hình slots và chế độ duyệt.
   - `posts` & `performance`: lịch đăng 7 ngày, retry bài lỗi, số liệu `24h/72h/7d`.
   - `settings` & `ai`: cấu hình provider, xoay vòng API keys, trần chi phí ngày/tháng, backup/export config bundle.

## Tiêu chí Nghiệm thu
- Toàn bộ endpoint `/api/v1/*` có test `TestClient` thật kiểm tra cách ly dữ liệu giữa 2 Workspace khác nhau, validation lỗi `400/404/422` và không làm gãy bất kỳ route V1 nào.
