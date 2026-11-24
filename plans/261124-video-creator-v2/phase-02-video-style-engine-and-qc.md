# Phase 02 (Đợt 1): Video Style Engine, Phụ đề động, Auto-Ducking, QC & Gỡ MPT

## Context links
- Plan cha: [plan.md](plan.md)
- Đặc tả: [docs/video-creator-v2-spec.md](../../docs/video-creator-v2-spec.md) (Mục 4.1)
- Phụ thuộc: [Phase 01](phase-01-multi-workspace-and-dual-lane-queue.md)

## Mục tiêu
Loại bỏ sự phụ thuộc vào dịch vụ phụ MoneyPrinterTurbo (`engines/mpt_*`), tự chủ 100% pipeline dựng video và hậu kỳ âm thanh/phụ đề bằng FFmpeg + ASS + Pillow trong `src/videocreator/pipeline/`.

## Phạm vi Công việc
1. **Hệ thống Preset Phong cách (`style_presets` table / config)**:
   - Lưu danh sách Video Style Presets (tùy chỉnh theo Workspace hoặc dùng chung): font chữ tiếng Việt, cỡ chữ, vị trí `SafeZone`, 6 kiểu hiệu ứng phụ đề động (`karaoke_highlight`, `tiktok_pop`, `box_highlight`, `neon_glow`, `minimal_bottom`, `bilingual`), thẻ Intro/Outro, nhạc nền mặc định, mức chuyển động ảnh/video.
2. **TTS Thống nhất & `word_timings`**:
   - Tách riêng `src/videocreator/tts/` (chạy Edge TTS trực tiếp với `word_boundary` timings, mở sẵn interface cho VieNeu-TTS & ElevenLabs ở Đợt 2).
   - Cắt khoảng lặng đầu/cuối (`silenceremove`), đo thời lượng thực tế và áp `atempo <= 1.35` hoặc cảnh báo/rút gọn lời theo ngân sách âm tiết.
3. **Engine Phụ đề ASS Nhảy từng chữ & Mixer Âm thanh FFmpeg**:
   - Sinh file `.ass` từ `word_timings` với tag `\kf` / đổi màu từng từ, tự động né `SafeZone`.
   - Trộn track giọng + nhạc nền bằng `sidechaincompress` (auto-ducking) + SFX chuyển cảnh + chuẩn hóa `-14 LUFS` (`loudnorm`).
   - Hỗ trợ đa tỉ lệ khung hình (`9:16` trọng tâm, mở sẵn `16:9` và `1:1`).
4. **Tính năng "Dựng lại theo phong cách mới" & QC Tự động**:
   - Endpoint & job `restyle_video` tái sử dụng voice/shot đã cắt để áp Style Preset khác trong vài chục giây.
   - Bước QC FFmpeg (`blackdetect`, `freezedetect`, `silencedetect`, `ebur128`) gắn kết quả vào `preflight_json` trước khi gửi duyệt hoặc cho qua Autopilot.
5. **Gỡ bỏ MoneyPrinterTurbo**:
   - Chuyển chế độ dựng Nhanh (`engine = 'ffmpeg'`) sang pipeline nội bộ mới; bỏ khởi chạy `MPTServiceManager` trong `app.py` (giữ migration an toàn cho các bản ghi `videos.engine = 'mpt'` cũ).

## Tiêu chí Nghiệm thu
- Render video thật từ `tests/samples/clip1_6s.mp4` qua FFmpeg: kiểm tra bằng `ffprobe` đạt chuẩn H.264/AAC `-14 LUFS`, có track phụ đề ASS highlight và vượt qua QC tự động.
- Kiểm chứng `blackdetect` / `silencedetect` bắt chính xác video cố tình tạo lỗi đen/câm trong test thật.
