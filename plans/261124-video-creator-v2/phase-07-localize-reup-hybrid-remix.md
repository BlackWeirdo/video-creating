# Phase 07: Studio Việt hóa / Reup, Hybrid Remix & Quốc tế hóa (`V2-LOC-01..06`)

## Mục tiêu
1. Bổ sung migration `019_v2_localize_studio.sql` (`videos.target_lang` và bảng `localize_projects`).
2. Triển khai `src/videocreator/pipeline/localize.py` với đầy đủ 3 chế độ (`reup_vi`, `hybrid_remix`, `intl_export`) tuân thủ nghiêm `workspace.content_policy` (`strict_footage` chỉ cho phép `intl_export`; `hybrid_remix` yêu cầu ít nhất 1 shot thật và không áp dụng filter màu/biến dạng lên `has_product = 1`).
3. Hỗ trợ đầy đủ 3 phương thức xử lý hardsub FFmpeg thật (`blur_bar`, `crop_frame`, `ocr_inpaint` / `delogo`), chống trùng lặp hình ảnh cho `reup_vi`, ép ngân sách âm tiết khi dịch (`vi`, `en`, `zh`, `ja`, `ko`), phụ đề song ngữ và QC `-14 LUFS`.
4. Cung cấp `/api/v1/localize/*`, `/api/v1/trends/{trend_id}/send-to-localize` và kiểm thử `tests/test_v2_phase07_localize_studio.py`.
