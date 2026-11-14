# Giai đoạn 09 và S12: MoneyPrinterTurbo

Cập nhật: 2026-11-14. Thay bản ngày 2026-11-13, vốn viết theo tài liệu và chưa từng chạy MoneyPrinterTurbo (MPT).

## 1. Kết luận S12: đạt một phần, lấy phương án lùi

Chạy thật MPT `v1.3.9` (commit `6992380`, 2026-10-21) trên máy chủ, script [spikes/s12_mpt_assemble.py](../../../spikes/s12_mpt_assemble.py), 3 đoạn footage thật 2,0 + 3,5 + 2,5 giây (tổng 8,0 giây), giọng `vi-VN-HoaiMyNeural-Female`.

| Tiêu chí | Kết quả |
|---|---|
| Cài và chạy API trên Windows | Đạt. `uv sync --frozen` 71 giây, venv 811 MB, API lên sau khoảng 20 giây |
| Giữ thứ tự đoạn (`sequential`) | Đạt. Điểm cắt ở 2,0 và 5,5 giây đúng như kịch bản |
| Không crop, không đổi tốc độ, không lấy stock | Đạt với nguồn 9:16 và `video_source = local` |
| Giọng tiếng Việt + phụ đề khớp giọng | Đạt. Phụ đề đúng dấu ("từng chút kiên nhẫn") |
| **Giữ độ dài từng đoạn** | **Không đạt.** MPT ép độ dài video bằng độ dài giọng đọc: giọng 6,24 giây thì video 6,27 giây (đoạn cuối bị cắt còn 0,8 giây); giọng 16,7 giây thì toàn bộ footage bị lặp lại hai lần |
| Thời gian dựng trên CPU | 82 giây cho video 6 giây; 169 giây cho video 17 giây |

Ghi thêm: MPT nén lại hình bằng MoviePy, tức thêm một lần nén ngoài hai lần cho phép của `BR-FMT-05`; âm thanh ra 44,1 kHz.

**Nhánh chọn (phương án lùi của S12 trong phase 01):** chỉ dùng MPT để tạo giọng đọc và mốc phụ đề. Lắp ráp vẫn do FFmpeg của app, nên độ dài footage theo kịch bản luôn được giữ, hình chỉ nén hai lần, phụ đề dùng chung kiểu ASS và vùng an toàn.

## 2. API thật đang dùng

- `POST /api/v1/subtitle` với `video_script`, `video_language`, `voice_name`, `voice_rate`, `bgm_type = ""`: tạo `audio.mp3` + `subtitle.srt` trong khoảng 2 giây.
- `GET /api/v1/tasks/{task_id}`: `state = 1` xong, `-1` lỗi.
- `GET /api/v1/download/{task_id}/audio.mp3` và `.../subtitle.srt`: app tải về thư mục làm việc, không dùng chung đường dẫn file với MPT.

Sai lệch của bản tích hợp cũ so với MPT thật (đã sửa):

| Bản cũ | Thực tế |
|---|---|
| Ghim `v1.2.6` | Bản mới nhất là `v1.3.9`; đã ghim bản này |
| `video_clip_duration = 999` | API từ chối với HTTP 400 (tối đa 15), nên mọi video `engine = mpt` đều âm thầm lùi về FFmpeg |
| Gửi đường dẫn tuyệt đối của đoạn cắt | MPT chỉ nhận file nằm trong `storage/local_videos` của nó |
| Cấu hình `enable_crop_to_fill`, `songs_dir`, mục `[tts]`, biến `MPT_CONFIG_FILE` | Không tồn tại trong MPT |
| Font `BeVietnamPro-SemiBold.ttf` | MPT chỉ kèm bản `Bold` và `Medium` |
| Giọng `vi-VN-Standard-A` (Gemini), `nova` (OpenAI) ghi là "thương mại" | Chưa từng thử; đã bỏ khỏi danh sách |
| App không bao giờ khởi động MPT | Đã nối vào vòng đời app |

## 3. Hiện thực sau khi sửa

- `engines/mpt_client.py`: `synthesize_voice` (gọi 3 endpoint ở mục 2).
- `engines/mpt_engine.py`: `try_voice_with_mpt`; MPT không phản hồi thì video vẫn dựng, chỉ có phụ đề, kèm ghi chú cho người duyệt (`FR-REN-05`).
- `engines/mpt_service.py`: sinh `config.toml` của MPT từ file mẫu của chính nó (ép `127.0.0.1` và cổng cấu hình), xoá thư mục nhạc kèm sẵn, chạy `python main.py`; app tự khởi động và tắt MPT.
- `pipeline/render.py` + `export.py`: có giọng đọc thì phụ đề theo mốc SRT của giọng (`FR-REN-07`), giọng trộn trên nền im lặng dài bằng footage, nhạc nền (nếu có) hạ còn 20%. Giọng dài hơn hình thì phần lời cuối bị cắt và người duyệt thấy ghi chú "nên rút lời hoặc thêm shot".
- Cài: `installer/install_mpt.cmd` vào `tools/mpt` (không commit).
- Test: `tests/test_mpt_voice_live.py` dựng thật một video có lồng tiếng (đạt: bản master 1080x1920, đúng 5,0 giây, âm thanh không im lặng); `tests/test_mpt_engine_local.py` kiểm tra đường lùi khi MPT tắt.

## 4. Còn thiếu của giai đoạn 09

| Việc | Lý do chưa có |
|---|---|
| S8: người dùng nghe và chấp nhận giọng; điều khoản thương mại | Ba giọng Edge TTS đã chạy (`vi-VN-HoaiMyNeural-Female`, `vi-VN-NamMinhNeural-Male`, `en-US-JennyNeural-Female`). Edge TTS không cần key nhưng điều khoản dùng cho quảng cáo chưa xác nhận; cần người dùng quyết định |
| Giọng trả tiền (Gemini, OpenAI, Azure, ElevenLabs) | MPT có hỗ trợ nhưng chưa thử; cần key |
| Nút nghe thử giọng (`FR-REN-06`) | Chưa làm |
| Kịch bản canh độ dài lời theo độ dài hình | Bộ lập kịch bản chưa biết tốc độ đọc; hiện chỉ cảnh báo sau khi dựng |
| Stock cho cảnh phụ (`FR-BRL-04`, mức "nên") | Chưa làm |
