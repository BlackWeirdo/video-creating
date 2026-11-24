# Phase 08: Batch Studio & Biến thể Sản phẩm A/B kèm Checkpoint Resume (`V2-BAT-01..05`)

## Mục tiêu
1. Bổ sung migration `020_v2_batch_ab_studio.sql` với bảng `batch_runs` và `batch_items`.
2. Xây dựng `src/videocreator/pipeline/batch_studio.py` sinh lô video + `1..3` biến thể A/B/C từ danh sách Prompt, Sản phẩm hoặc Công thức Xu hướng, xoay vòng góc hook & `style_preset`.
3. Lưu checkpoint theo từng bước (`queued -> planned -> completed`) và cho phép retry đúng các item lỗi từ bước dở dang mà không tạo trùng `videos` row.
4. Cung cấp `/api/v1/batches/*`, `/api/v1/trends/send-to-batch` và kiểm thử `tests/test_v2_phase08_batch_ab_studio.py`.
