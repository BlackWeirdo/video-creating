# Phase 05: Render lõi FFmpeg 9:16 + phụ đề ASS

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 04](phase-04-ai-provider-remix-plan.md); S9 của [phase 01](phase-01-verification-spikes.md)
- Docs: [research 02 mục 4](research/researcher-02-video-pipeline-and-packaging.md)

## Overview

- Ngày: 2026-11-12
- Mô tả: biến `plan_json` thành mp4 1080x1920: cắt shot, ghép, burn phụ đề ASS, nhạc nền đơn giản (cắt theo độ dài, chuẩn hoá âm lượng). Lồng tiếng, phụ đề khớp giọng, SFX và chạy lô thuộc phase 09 (engine MoneyPrinterTurbo); cắt theo nhịp nhạc thuộc chế độ Studio (phase 17).
- Ưu tiên: P0
- Trạng thái triển khai: hoàn thành (2026-11-13)
- Trạng thái review: đã kiểm thử (`pytest -m local`)

## Key Insights

- Định dạng xuất đa nền tảng (yêu cầu người dùng 2026-11-12):
  - MỘT bản master cho mọi nền tảng, không xuất riêng từng nơi: MP4, H.264 High, `yuv420p`, 1080x1920 (9:16), 30 fps cố định, quét liên tục, màu bt709, GOP 2 giây đóng, `-movflags +faststart`; AAC-LC stereo 48 kHz 128 kbps trở lên, luôn có track âm thanh (video không lời vẫn chèn track im lặng); âm lượng chuẩn hoá khoảng -14 LUFS.
  - `pipeline/export.py` có 1 hàm `normalize(src) -> master.mp4` dùng chung cho cả chế độ Nhanh (FFmpeg) và Studio (đầu ra Remotion ở phase 17 cũng phải đi qua hàm này).
  - `pipeline/preflight.py`: `check(master, platform) -> list[lỗi]` bằng `ffprobe`, đối chiếu bảng giới hạn từng nền tảng trong `config.toml` (`[platform_limits.<tên>]`: thời lượng tối thiểu/tối đa, dung lượng tối đa, tỉ lệ, fps, codec). Chạy ngay sau render: video không đạt cho nền tảng nào thì hiện rõ trên màn hình duyệt và tin Telegram ("không đăng được TikTok: dài quá X giây"), và tài khoản của nền tảng đó bị bỏ tick.
  - Giới hạn chính thức từng nền tảng (thời lượng, dung lượng, bitrate) CHƯA xác nhận: lấy ở S10 phase 01 cho FB/IG, ở bước đọc docs phase 11 cho Threads/TikTok. Trước khi có số chính thức dùng mức an toàn: 5–90 giây, dưới 100 MB.
  - Vùng an toàn giao diện: phụ đề và chữ không nằm trong khoảng 15% trên, 25% dưới và 12% mép phải của khung (nơi các app phủ nút, caption, tên tài khoản). Tỉ lệ để trong config, chỉnh sau khi xem bài đăng thật.
  - Ảnh bìa: xuất kèm 1 khung `cover.jpg` (mặc định khung ở 1 giây, đổi được lúc duyệt) cho nền tảng nào nhận ảnh bìa qua API.

- Độ chính xác sản phẩm (yêu cầu người dùng 2026-11-12), phần của phase này:
  - Render chỉ được: cắt theo thời gian, scale, crop, ghép, chồng chữ/phụ đề, trộn âm thanh. KHÔNG bộ lọc màu, không làm nét/làm mịn AI, không upscale AI, không đổi tốc độ trên shot `has_product = 1` (màu bạc và đá phải đúng như quay). Danh sách filter FFmpeg cho phép là 1 hằng số, test khẳng định lệnh render không chứa filter ngoài danh sách.
  - Footage dọc 9:16: không crop. Footage ngang: không tự crop giữa khung; mặc định đặt nguyên khung trên nền mờ, hoặc dùng vùng crop người dùng đã chọn cho footage đó trong UI (lưu `footage.crop_json`). Không dùng AI đoán vùng crop ở v1.
  - Phụ đề và chữ đặt trong vùng an toàn dưới/trên, không đè lên giữa khung nơi sản phẩm thường nằm.
  - Bitrate đủ cao để giữ chi tiết chạm khắc (CRF 18, preset slow cho bản đăng; bản xem thử Telegram 720p là bản riêng, không phải bản đăng).

- Re-encode từng shot về cùng codec/fps/size rồi concat `-c copy`: ổn định hơn 1 filtergraph khổng lồ, lỗi shot nào biết shot đó.
- Phụ đề trên Windows: chạy ffmpeg với `cwd` = thư mục làm việc, tên file ASCII, `subtitles=sub.ass:fontsdir=fonts` -> tránh escape đường dẫn.
- Đầu ra: đúng bản master mô tả ở mục "Định dạng xuất đa nền tảng" phía trên (AAC 48 kHz); spec chính thức từng nền tảng chưa xác nhận, xem S10.
- Thời điểm phụ đề lấy thẳng từ kịch bản (mỗi shot 1 dòng `text`), không cần ASR.

## Requirements

- Job `render`: `planned` -> `rendering` -> `rendered` (tự chuyển tiếp `pending_approval`) hoặc `failed` kèm đuôi stderr.
- Đưa về 9:16 theo quy tắc ở Key Insights (footage dọc giữ nguyên; footage ngang dùng `footage.crop_json` hoặc nguyên khung trên nền mờ; KHÔNG tự crop giữa khung), tôn trọng metadata xoay.
- Phụ đề: font Be Vietnam Pro (OFL, bundle trong repo), viền đậm, đặt ngay phía trên vùng cấm 25% dưới (trong vùng an toàn), tự xuống dòng; hiển thị đúng dấu tiếng Việt.
- Nhạc: chọn ngẫu nhiên 1 file trong `assets` kind `music` (người dùng tự nạp qua UI); cắt bằng độ dài video, fade out 0.5 giây, `loudnorm I=-14`. Không có nhạc -> video im lặng có track audio rỗng (một số nền tảng từ chối file thiếu audio: chưa xác nhận, làm an toàn).
- Xem lại kết quả ngay trong UI; nút render lại.

## Architecture

```
pipeline/ffmpeg.py     # run(args, cwd, timeout) -> raise RenderError(stderr_tail); đường dẫn ffmpeg từ paths
pipeline/subtitles.py  # build_ass(lines:[(start,end,text)], style) -> str
pipeline/render.py     # render(video_id): work dir -> segments -> concat -> subs -> audio -> export.normalize -> preflight
pipeline/export.py     # normalize(src) -> master.mp4 (spec master duy nhất) + cover.jpg; ALLOWED_FILTERS
pipeline/preflight.py  # check(master, platform) -> list[lỗi] theo [platform_limits]
api/routes_assets.py   # upload/list/xoá nhạc
```

Các bước trong `work/<video_id>/` (xoá khi xong, giữ khi lỗi để debug):
1. Mỗi shot -> đoạn trung gian chất lượng cao (không phải bản đăng): footage dọc `-vf "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30"`; footage ngang dùng `crop` theo `crop_json` rồi scale, hoặc chồng nguyên khung lên bản phóng to làm mờ của chính nó. `-c:v libx264 -preset veryfast -crf 14 -pix_fmt yuv420p -an seg_NN.mp4`.
2. `concat` demuxer -> `cut.mp4`.
3. Ghi `sub.ass`; burn phụ đề và mã hoá bản cuối trong CÙNG 1 lần (`-crf 18 -preset slow`) để hình chỉ qua 2 lần nén.
4. Trộn nhạc + `loudnorm`; `export.normalize()` bảo đảm đúng spec master (48 kHz, track audio luôn có, `+faststart`) -> `media/output/<video_id>.mp4` + `cover.jpg`; cập nhật `output_path`, `duration_s`.
5. `preflight.check()` cho cả 4 nền tảng; lưu kết quả vào `videos` để màn hình duyệt hiển thị.

## Related code files

Tạo: `src/videocreator/pipeline/ffmpeg.py`, `pipeline/subtitles.py`, `pipeline/render.py`, `api/routes_assets.py`, `web/templates/assets.html`, `web/templates/video_detail.html`, `assets/fonts/BeVietnamPro-*.ttf`, `tests/test_render.py`, `tests/test_subtitles.py`.
Sửa: `app.py` (handler `render`), `api/routes_videos.py` (POST render), `paths.py` (ffmpeg, fonts).

## Implementation Steps

1. `ffmpeg.py`: wrapper subprocess, kiểm tra `ffmpeg -filters` có `subtitles` lúc khởi động (cảnh báo nếu thiếu).
2. `subtitles.py`: sinh ASS (PlayResX 1080, PlayResY 1920), escape ký tự đặc biệt, ngắt dòng theo độ dài.
3. `render.py` theo 4 bước; mỗi bước lỗi -> `failed` + stderr.
4. Upload/list nhạc; probe độ dài lưu `assets.duration_s`.
5. Trang chi tiết video: player, trạng thái, nút render/render lại.
6. Test `-m local` (FFmpeg thật, clip mẫu thật, kịch bản viết tay trong test trỏ vào shot thật trong DB tạm): ffprobe đầu ra đúng 1080x1920, 30 fps, h264 + aac, thời lượng = tổng shot (sai số < 0.2 giây); render có dòng phụ đề tiếng Việt không lỗi; shot_id không tồn tại -> `failed` có thông báo; ffprobe bản master khớp từng mục của spec (h264, yuv420p, 30 fps, aac 48 kHz, có track audio kể cả khi không nhạc); mọi filter trong các lệnh đã chạy thuộc `ALLOWED_FILTERS`; `preflight.check` trả lỗi đúng khi đặt giới hạn thời lượng thấp hơn video; clip mẫu quay ngang không bị crop giữa khung.

## Todo list

- [x] Wrapper ffmpeg + kiểm tra libass (`pipeline/ffmpeg.py`)
- [x] Sinh ASS (`pipeline/subtitles.py`)
- [x] Pipeline render 5 bước (`pipeline/render.py`)
- [x] `export.normalize` + danh sách filter cho phép + ảnh bìa (`pipeline/export.py`)
- [x] `preflight.check` + bảng `platform_limits` (`pipeline/preflight.py`)
- [x] Xử lý footage ngang (crop đã chọn / nền mờ) + vùng an toàn phụ đề
- [x] Quản lý nhạc nền (`api/routes_assets.py`, `web/templates/assets.html`)
- [x] UI xem video + render lại (`web/templates/video_plan.html`)
- [x] Test local render thật (`tests/test_subtitles.py`, `tests/test_render.py`)

## Success Criteria

- 3 kịch bản từ phase 04 render ra 3 file mp4 khác nhau, xem được trong app, phụ đề đúng dấu, có nhạc.
- Video 20 giây render < 2 phút trên PC không GPU.
- `pytest -m local` xanh.

## Risk Assessment

- Lệch A/V hoặc giật ở điểm nối do footage VFR: đã ép `fps=30` khi cắt; nếu còn lỗi, thêm `-vsync cfr`.
- Footage quay ngang: không crop giữa khung (xem Key Insights); bản "nguyên khung trên nền mờ" kém đẹp hơn quay dọc -> khuyên quay dọc. Không làm auto-reframe bằng AI (YAGNI).
- Chữ phụ đề dài tràn khung: giới hạn ký tự/dòng trong prompt phase 04 + ngắt dòng ở đây.

## Security Considerations

- Mọi đối số ffmpeg truyền dạng list (không shell string); text phụ đề chỉ đi vào file ASS, không vào dòng lệnh.
- File nhạc upload: kiểm tra đuôi + probe được mới nhận.

## Next steps

- Phase 06 lấy video `pending_approval` đưa vào hàng chờ duyệt.
- Phase 09 thay bước 4 (audio) bằng bản đầy đủ.
