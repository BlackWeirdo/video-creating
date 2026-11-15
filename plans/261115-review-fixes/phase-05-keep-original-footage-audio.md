# Phase 05: Giữ tiếng gốc của footage (F5)

## Context links

- [plan.md](plan.md), [scout F5](scout/scout-01-code-locations.md)
- Đặc tả: `FR-REN-01`, `FR-REN-02`, `FR-REN-08`, `BR-FMT-*` (AAC 48 kHz stereo), `NFR-PERF-02`

## Overview

- Ngày: 2026-11-15. Ưu tiên: trung bình (giá trị nội dung: tiếng gõ, mài, đánh bóng bạc). Trạng thái: xong, test local đạt. Review: đã review (code-reviewer), đã sửa các điểm cao và trung bình.
- Bước cắt shot luôn dùng `-an` → tiếng gốc luôn mất. Thêm tuỳ chọn giữ tiếng gốc, trộn nhỏ dưới lồng tiếng/nhạc.

## Key Insights

- `render_steps.cut_shot_segments` (`render_steps.py:92`) `-an`; `concat_segments` dùng `-c copy` → mọi đoạn phải CÙNG có tiếng với cùng thông số, nếu không concat lỗi hoặc mất tiếng. Shot từ footage không có tiếng cần đệm `anullsrc`.
- `export.normalize_to_master` (`export.py:47-90`) đã có nhánh `elif info.has_audio` (giữ tiếng nguồn khi không có giọng/nhạc) nhưng hiện không bao giờ chạy vì `cut.mp4` không có tiếng.
- Whitelist FFmpeg đã có `amix`, `volume`, `afade`, `atrim`, `anullsrc`, `loudnorm`, `aresample` → không phải mở thêm filter.
- `studio/export.py` cũng gọi `normalize_to_master` → tham số mới phải mặc định giữ hành vi cũ cho Studio.
- MPT (`add_voice_over`) chỉ trả file giọng; dựng cuối vẫn qua `normalize_to_master` → một chỗ sửa áp cho cả `ffmpeg` và `mpt`.
- `footage` có `has_audio`? Không chắc → dùng `probe_video(src_file).has_audio` lúc cắt (đã có, nhanh).

## Requirements

- Cấu hình `render.keep_original_audio: bool` (mặc định theo quyết định chủ dự án; khuyến nghị `False`), sửa được trong Settings, có hiệu lực ở lần dựng kế tiếp.
- Bật: mỗi đoạn cắt có track AAC 48 kHz stereo; shot không có tiếng → đoạn im lặng cùng độ dài. Concat `-c copy` vẫn chạy.
- Trộn: có giọng → giọng 1.0 + tiếng gốc 0.3 (+ nhạc 0.2 như cũ); chỉ nhạc → nhạc 1.0 + tiếng gốc 0.3; không giọng không nhạc → tiếng gốc 1.0 (nhánh `has_audio` sẵn có). Luôn `loudnorm` như cũ.
- Tắt: hành vi y như hiện tại (`-an`), không đổi thời gian dựng.
- `NFR-PERF-02` (video 20 s dựng < 2 phút) vẫn đạt.

## Architecture

- `config.py`: `class RenderConfig(BaseModel): keep_original_audio: bool = False` + `Settings.render`. Hằng số âm lượng đặt trong `export.py` (`SOURCE_AUDIO_UNDER = 0.3`), không đưa ra cấu hình (YAGNI).
- `cut_shot_segments(paths, planned_shots, work_dir, *, keep_audio: bool = False)`:

```
keep_audio and src has audio : ... -map 0:v:0 -map 0:a:0 -c:a aac -ar 48000 -ac 2 -b:a 128k
keep_audio and no audio      : add -f lavfi -t <dur> -i anullsrc=channel_layout=stereo:sample_rate=48000,
                               -map 0:v:0 -map 1:a:0 -c:a aac -ar 48000 -ac 2 -b:a 128k -shortest
not keep_audio               : -an (unchanged)
```

- `normalize_to_master(..., mix_source_audio: bool = False)`: khi `True` và `info.has_audio` thì thêm `[0:a]volume=0.3` vào `amix` ở nhánh giọng và nhánh nhạc (nhánh nhạc đổi sang `-filter_complex`). Studio không truyền → như cũ.
- `render.py`: `keep = settings.render.keep_original_audio`; truyền `keep_audio=keep` và `mix_source_audio=keep`.
- `web/templates/settings.html` + `api/routes_settings.py` (cả hai đang có thay đổi chưa commit): thêm một ô tích "Giữ tiếng gốc của footage (trộn nhỏ dưới giọng đọc/nhạc)".

## Related code files

- Sửa: `src/videocreator/config.py`, `src/videocreator/pipeline/render_steps.py`, `src/videocreator/pipeline/export.py`, `src/videocreator/pipeline/render.py`, `src/videocreator/api/routes_settings.py`, `src/videocreator/web/templates/settings.html`, `docs/video-creator-spec.md` (`FR-REN-02`)
- Test: mở rộng `tests/test_render.py`

## Implementation Steps

1. Đọc bản hiện tại của `config.py`, `routes_settings.py`, `settings.html` (chưa commit) trước khi sửa.
2. Thêm `RenderConfig`; đảm bảo `config.toml` cũ không có mục `[render]` vẫn nạp được (mặc định).
3. `cut_shot_segments` thêm `keep_audio` theo sơ đồ; `probe_video` từng file nguồn (cache theo đường dẫn trong vòng lặp).
4. `normalize_to_master` thêm `mix_source_audio`; viết lại hai nhánh `filter_complex` cho gọn, giữ đúng chỉ số input.
5. `render.py` nối cấu hình.
6. Settings UI + route lưu cờ.
7. Test `test_render.py` (FFmpeg thật, `tests/samples/`):
   - Tắt: master có đúng 1 track tiếng (im lặng/ nhạc) như trước — test cũ phải còn xanh.
   - Bật, một clip có tiếng + một clip không có tiếng (tạo bằng FFmpeg thật từ clip mẫu với `-an` trong thư mục tạm của test) → concat thành công; `ffprobe` thấy `cut.mp4` có track AAC 48 kHz; tổng độ dài khớp.
   - Bật + nhạc: master có tiếng; đo `volumedetect` (hoặc `astats`) đoạn có tiếng gốc khác im lặng (> -60 dB).
   - Đo thời gian dựng video 20 s không vượt quá xa test cũ (ghi lại số, không đặt ngưỡng cứng trong test).
8. Đặc tả `FR-REN-02`: "Tuỳ chọn giữ tiếng gốc footage, trộn nhỏ dưới giọng/nhạc; mặc định <theo quyết định>".
9. Suite xanh; commit `feat(render): option to keep original footage audio under voice and music`.

## Todo list

- [ ] `RenderConfig.keep_original_audio`
- [ ] Cắt đoạn có tiếng / đệm im lặng
- [ ] Trộn tiếng gốc trong `normalize_to_master`
- [ ] Ô tích trong Settings
- [ ] Test FFmpeg thật (có tiếng, không tiếng, trộn nhạc)
- [ ] Đặc tả, suite xanh, commit

## Success Criteria

- Bật cờ: video dựng từ footage có tiếng nghe được tiếng gốc nhỏ dưới giọng/nhạc; footage không tiếng không làm hỏng concat.
- Tắt cờ: kết quả giống hệt trước (test cũ xanh).

## Risk Assessment

- Lệch đồng bộ tiếng/hình nhỏ khi cắt `-ss` trước `-i` và mã hoá lại AAC: chấp nhận cho tiếng nền; nếu nghe lệch thì thêm `aresample=async=1` (đã trong whitelist).
- Footage có tiếng nói/ồn lớn làm bẩn video: vì vậy khuyến nghị mặc định TẮT.
- Bản quyền: tiếng gốc là footage tự quay của chủ shop → không có rủi ro bản quyền nhạc, trừ khi lúc quay có nhạc nền phát trong phòng (ghi chú trong Settings).

## Security Considerations

- Không đổi đường xử lý file; mọi lệnh vẫn qua `run_ffmpeg` với whitelist filter.

## Next steps

- Nếu cần chọn theo từng footage/ từng video: làm sau khi có nhu cầu thật (YAGNI).
