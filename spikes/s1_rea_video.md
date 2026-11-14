# S1: rea-video trên Windows

Trạng thái: **ĐẠT** (2026-11-13). Chốt **Nhánh A** (`rea-video decompose` trong venv riêng).

## Môi trường

- Windows 10 Pro 19045, i7-9750H, 8 GB RAM, không dùng GPU.
- Python 3.11.18 (uv 0.13.8), FFmpeg 9.0.2 full build (gyan.dev).
- rea-video 0.1.0, commit `d2751643311a635d6b4649e6c8a4975fcb30dab4` (2026-11-13), clone tại `spikes/vendor/rea-video`.

## Lệnh cài đặt đã chạy

```powershell
git clone https://github.com/JuneYaooo/rea-video spikes/vendor/rea-video
uv venv spikes/.venv-rea --python 3.11
uv pip install --python spikes/.venv-rea -e "spikes/vendor/rea-video[ocr]"
uv pip uninstall --python spikes/.venv-rea opencv-python
uv pip install --python spikes/.venv-rea --reinstall --no-deps "opencv-python-headless>=4.8,<5"
```

## Kết quả chạy `decompose` trên 2 footage thật (1080x1920, 60fps, 20.07s)

1. **`clip1.mp4` (`01. XUC XAC`, 20.07s, 1080x1920 60fps)**:
   - Chạy bản tách stems + OCR (`--no-packaging --no-vlm --no-asr`): **294.2 giây** (trong đó ~94 giây tải model ONNX lần đầu: `UVR-MDX-NET-Inst_HQ_3.onnx` 67 MB, `bandit-v2-multi.onnx` 149 MB, `face_detection_yunet_2023mar.onnx`; thời gian xử lý thực ~200 giây). Phát hiện **16 shot**.
   - Chạy bản tối ưu cho tách shot footage (`--no-packaging --no-vlm --no-asr --no-ocr --no-stems --no-speakers`): **120.7 giây (~2 phút)**, riêng bước phát hiện điểm cắt chỉ mất **7 giây**, tạo đầy đủ `breakdown.json` và ảnh từng shot trong `shots/`.
2. **`clip2.mp4` (`02. NHAN MOI`, 20.07s, 1080x1920 60fps)**:
   - Chạy bản tách stems + OCR (`--no-packaging --no-vlm --no-asr`, model đã cache): **237.1 giây (~3.95 phút < 5 phút)**. Phát hiện **20 shot**, tách `stems/original.wav`, `vocals.wav`, `music.wav`, đo BPM (191.4 BPM) và 6 sự kiện SFX.

## Cấu trúc `breakdown.json` dùng cho Phase 03

Mảng `shots` ở cấp cao nhất:
```json
{
  "schema": "rea_video.breakdown.v1",
  "summary": {"duration": 20.0, "shots": 16},
  "shots": [
    {
      "id": "shot_001",
      "index": 1,
      "start": 0.0,
      "end": 0.15,
      "duration": 0.15,
      "start_frame": 0,
      "end_frame": 9,
      "assets": {
        "sheet": "shots/shot_001.jpg",
        "first_frame": "shots/shot_001_first.jpg",
        "last_frame": "shots/shot_001_last.jpg"
      }
    }
  ]
}
```

## Ghi chú cho Phase 03 và Phase 13

- **Phase 03 (nhập footage của mình)**: Gọi `rea-video decompose <file> -o <work> --no-packaging --no-vlm --no-asr --no-ocr --no-stems --no-speakers` (bỏ tách nhạc/OCR tiếng Trung không cần thiết khi nhập footage thô, giảm một nửa thời gian CPU). Sau đó lọc bỏ shot `< 0.7s` và chia đều shot `> 8.0s` thành đoạn `3–5s` theo `FR-FTG-05`.
- **Phase 13 / 17 (phân tích video tham khảo xu hướng)**: Gọi `rea-video decompose <file> -o <rea_dir> --no-vlm` để lấy trọn vẹn `VIDEO.md`, `breakdown.json`, `storyboard.jpg`, BPM, stems và packaging.
- Phải đảm bảo thư mục chứa `ffmpeg.exe` và `ffprobe.exe` nằm trong `PATH` của tiến trình con khi gọi `rea-video`.
