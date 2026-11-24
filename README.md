# Video Creator V2

Phần mềm Desktop AI đa Studio sản xuất, Việt hóa/Remix và đăng video đa nền tảng (9:16, 16:9, 1:1) vận hành hoàn toàn trên máy PC CPU văn phòng.

## Tính năng chính

- **Studio Việt hóa & Hybrid Remix (`/localize`)**: Tách giọng & nhạc nền MDX-Net (`Kim_Vocal_2.onnx`), quét phụ đề cứng bằng `RapidOCR` + `Faster-Whisper`, phân biệt người nói `3D-Speaker ONNX`, dịch theo ngân sách âm tiết (AI `translator` hoặc dự phòng offline `NLLB-200`), xóa chữ cứng `boxblur` / `LaMa ONNX`, lồng tiếng `Edge TTS` hoặc nhân bản giọng `VieNeu-TTS v3 Nano` trên CPU.
- **Studio Chuyên biệt (`/podcast`, `/novel`, `/news`, `/characters`, `/batch`, `/editor`)**: Giọng đọc thật + Giọng Kênh MC thu trực tiếp, tách nền `rembg` (`u2net`), avatar Podcast sáng theo lượt nói, trình dựng FreeCut (MIT) nhúng sẵn và thanh tiến trình bất đồng bộ trực tiếp qua SSE (`/api/v1/events`).
- **Bộ cài Windows Offline (`VideoCreatorV2Setup.exe`)**: Đóng gói sẵn Python 3.11, `.venv` thư viện AI CPU, Node 24 LTS, FFmpeg/FFprobe, `yt-dlp.exe`, `uv.exe`, FreeCut và Next.js 15 Standalone — cài đặt 100% không cần mạng Internet.

## Chạy ứng dụng (Môi trường phát triển)

```powershell
# Cài đặt dependencies (bao gồm công cụ kiểm thử)
uv sync --extra dev

# Build giao diện Next.js 15 Standalone
cd web-next
npm run lint
npm run build
cd ..

# Mở ứng dụng Desktop (cửa sổ pywebview + Next.js Studio UI)
uv run videocreator

# Hoặc chạy chế độ máy chủ headless
uv run videocreator --headless
```

Thư mục dữ liệu mặc định nằm tại `%LOCALAPPDATA%\VideoCreatorV2` (có thể ghi đè qua biến môi trường `VIDEOCREATOR_DATA` hoặc cờ `--data-dir`).

## Đóng gói Bộ cài Offline (`.exe`)

```powershell
powershell -ExecutionPolicy Bypass -File installer\stage_bundle.ps1 -IncludeRuntimes
ISCC.exe installer\videocreator.iss
```

## Chạy kiểm thử

```powershell
# Bộ kiểm thử local chuẩn (không cần mạng / không cần GPU)
uv run pytest -m local -q

# Bộ kiểm thử suy luận thật với các mô hình AI CPU đã cài
uv run pytest -m models -v
```
