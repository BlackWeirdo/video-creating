# Phase 14: Studio Chuyên biệt — Tiểu thuyết, Sóng nhạc Podcast (`16:9`) & Lip-sync AI (`V2-STD-01..03`)

## Mục tiêu
1. Bổ sung migration `026_v2_specialized_studios.sql` cho các bảng `novel_projects`, `novel_chapters`, `podcast_projects`, và `lipsync_projects`.
2. Mở rộng `CREATIVE_REMIX_FILTERS` trong `src/videocreator/pipeline/ffmpeg.py` với `showwaves`, `showfreqs`, `showwavespic`, `avectorscope`, `sine`, `aevalsrc` (giữ nguyên danh sách strict `ALLOWED_FILTERS` cho `BR-PRD-01`).
3. Triển khai 3 module studio:
   - `src/videocreator/pipeline/novel_studio.py`: Tách tiểu thuyết đa chương theo tiêu đề chương hoặc ngưỡng từ, gắn nhân vật/phong cách, render hàng loạt từng chương kèm **checkpoint resume** bỏ qua chương đã sẵn sàng.
   - `src/videocreator/pipeline/podcast_studio.py`: Hỗ trợ hội thoại đa giọng (1–2 host) hoặc audio nguồn, mặc định khung hình `16:9` (`1920x1080`, hỗ trợ `9:16` / `1:1`), dựng sóng nhạc/phổ tần số FFmpeg thật (`showwaves` / `showfreqs`), `-14 LUFS`, phụ đề ASS và QC tự động.
   - `src/videocreator/pipeline/lipsync_studio.py`: Chân dung/nhân vật + giọng nói -> nhận diện `wav2lip_gan` cục bộ nếu có hoặc nội suy biên độ RMS (`wave` + `array('h')`) với hiệu ứng hoạt ảnh khẩu hình FFmpeg và QC tự động.
4. Expose `/api/v1/novels/*`, `/api/v1/podcasts/*`, `/api/v1/lipsync/*` trong `routes_specialized_v1.py`, đăng ký job làn `compute`, viết `tests/test_v2_phase14_novel_podcast_lipsync.py`.
