# Phase 05 (Đợt 1): Giao diện Next.js 15 Standalone Studio Shell & Các màn hình Đợt 1

## Context links
- Plan cha: [plan.md](plan.md)
- Đặc tả: [docs/video-creator-v2-spec.md](../../docs/video-creator-v2-spec.md) (Mục 3.1)
- Phụ thuộc: [Phase 04](phase-04-rest-api-v1-surface.md)

## Mục tiêu
Xây dựng ứng dụng Frontend **Next.js 15 (`output: "standalone"`) + React 19 + Tailwind CSS v4** trong thư mục `web-next/` của repo, chạy bằng Node.js `v24.22.1` (LTS) và kết nối với Backend FastAPI tại `/api/v1/*`, thay thế trải nghiệm đa màn hình cho Đợt 1.

## Phạm vi Công việc
1. **Khung App Shell (`web-next/`)**:
   - Thanh chuyển nhanh **Workspace** trên Sidebar (kèm huy hiệu `content_policy`: Strict / Hybrid / Full AI).
   - **Thanh trạng thái & Hàng đợi 2 làn** (`io` / `compute`) ở chân trang: lắng nghe `/api/v1/events` (SSE), hiển thị log trực tiếp từ `/api/v1/logs/tail` và nút **Đang chạy / Tạm dừng / Chạy tiếp**.
   - Rewrite `/api/v1/:path*` và `/files/:path*` sang FastAPI (`127.0.0.1:8765`).
2. **Các trang chức năng Đợt 1**:
   - `/` (Tổng quan Dashboard & Nút tạo nhanh)
   - `/trends` (Watchlist, quét 5 nguồn, dán link, xem công thức `rea-video` & đề xuất)
   - `/products`, `/footage`, `/shots` (Kho dữ liệu thật theo Workspace, kéo thả chỉnh `focus_x` 9:16)
   - `/videos` & `/videos/[id]` (Danh sách sản xuất, trình sửa lời thoại đồng hồ âm tiết + đồng bộ player `<video>` + đổi Style nhanh)
   - `/video-style` (Cấu hình 6 kiểu phụ đề nhảy chữ, nhạc ducking, intro/outro + xem thử)
   - `/approval`, `/channels` & `/accounts`, `/schedule`, `/performance` (Duyệt từng bài / duyệt lô, lịch đăng 7 ngày, tải gói `.zip`, 5 nền tảng gồm YouTube)
   - `/studio` (Phiên Studio Remotion) & `/settings` (AI Keys xoay vòng, trần chi phí, Subscription-First, cấu hình hàng đợi 2 làn)
3. **Launcher 2 tiến trình (`src/videocreator/__main__.py`)**:
   - Bật FastAPI (`8765`) + Next.js standalone (`3000`), chờ `/api/v1/health`, mở cửa sổ Edge/Chrome `--app` (fallback trình duyệt mặc định) và dọn sạch cả 2 tiến trình khi tắt.

## Tiêu chí Nghiệm thu
- `npm run typecheck`, `npm run lint` và `npm run build` trong `web-next/` thành công 0 lỗi, tạo ra `.next/standalone/server.js`.
- Chạy kiểm thử end-to-end thật giữa Next.js standalone + FastAPI backend qua trình duyệt/HTTP thật trên toàn bộ các luồng Đợt 1.
