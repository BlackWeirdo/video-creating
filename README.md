# Video Creator

Phần mềm nội bộ sản xuất và đăng video ngắn (9:16) cho thương hiệu trang sức bạc thủ công.

## Yêu cầu môi trường

- Windows 10/11 (khuyến nghị 64-bit)
- Python 3.11 (quản lý bằng `uv`)
- FFmpeg full build (có `libass`, `libx264`)

## Chạy ứng dụng

```powershell
# Cài đặt dependencies vào .venv
uv sync --all-extras

# Mở cửa sổ ứng dụng Desktop (pywebview)
uv run videocreator

# Hoặc chạy chế độ không cửa sổ (mở http://127.0.0.1:8765 trong trình duyệt)
uv run videocreator --headless
```

Thư mục dữ liệu mặc định nằm tại `%APPDATA%\VideoCreator` (có thể ghi đè qua biến môi trường `VIDEOCREATOR_DATA` hoặc cờ `--data-dir`).

## Chạy kiểm thử (không dùng mock)

```powershell
uv run pytest -m local
```
