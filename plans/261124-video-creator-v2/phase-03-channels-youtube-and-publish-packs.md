# Phase 03 (Đợt 1): Quản lý Kênh, Chính sách Duyệt 3 cấp, YouTube & Gói `.zip`

## Context links
- Plan cha: [plan.md](plan.md)
- Đặc tả: [docs/video-creator-v2-spec.md](../../docs/video-creator-v2-spec.md) (Mục 2, Mục 5.9)
- Phụ thuộc: [Phase 01](phase-01-multi-workspace-and-dual-lane-queue.md), [Phase 02](phase-02-video-style-engine-and-qc.md)

## Mục tiêu
Nâng cấp hệ thống phát hành từ 4 nền tảng đơn lẻ lên quản lý theo **Cụm Kênh (`accounts` gắn `workspace_id`)**, mở rộng hỗ trợ **YouTube (Shorts/Video dài)**, **Xuất Gói Đăng Bài `.zip`**, và hỗ trợ **3 cấp độ duyệt** (`single`, `bulk`, `autopilot`).

## Phạm vi Công việc
1. **Migration mở rộng `accounts` & `channels`**:
   - Nới constraint `accounts.platform` thêm `'youtube'`; bổ sung cấu hình khung giờ riêng, `approval_mode` cấp kênh/workspace, điểm QC tối thiểu cho Autopilot (`autopilot_min_score`).
   - Thêm giới hạn nền tảng mặc định cho `youtube` trong `config.py` (`PlatformLimitConfig`).
2. **YouTube Data API v3 Poster (`src/videocreator/posting/youtube.py`)**:
   - Hỗ trợ OAuth2 Google (lưu refresh token mã hóa trong `secrets_store`) và resumable upload video qua YouTube Data API v3 (`#Shorts` tự động cho video dọc `<= 60s`).
   - Lấy chỉ số `views`, `likes`, `comments` vào `post_metrics`.
3. **Xuất Gói Đăng Bài `.zip` (`src/videocreator/posting/publish_pack.py`)**:
   - Đóng gói file `.mp4` thành phẩm + ảnh bìa `cover.jpg` (có chèn tiêu đề tùy chọn) + tệp `captions.txt` / `metadata.json` tối ưu cho TikTok, Reels, Shorts, YouTube, Threads.
4. **Cơ chế Duyệt 3 Cấp độ (`single` / `bulk` / `autopilot`)**:
   - Duyệt theo lô (`bulk_approve_videos`): chọn nhiều video cùng lúc, xếp slot thông minh không trùng giờ vàng trên từng tài khoản.
   - Tự động duyệt & xếp lịch (`autopilot`): chỉ kích hoạt khi Workspace/Kênh bật `autopilot` VÀ video qua QC FFmpeg + đạt điểm `quality_score >= autopilot_min_score` (các Workspace `strict_footage` giữ mặc định `single` an toàn).

## Tiêu chí Nghiệm thu
- Test thật với SQLite + OAuth token flow + đóng gói `.zip` thật (mở kiểm tra nội dung file trong archive).
- Test thật phân quyền `strict_footage` từ chối đăng video không hợp lệ, trong khi `autopilot` tự chuyển video đạt QC sang `scheduled`.
