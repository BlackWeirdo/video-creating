# Hướng dẫn Cài đặt, Chuyển máy & Vận hành 24/7 (Phase 08)

## 1. Cài đặt trên máy chủ Windows 24/7

1. Cài đặt công cụ nền:
   - Python 3.11 + `uv` (`winget install astral-sh.uv`)
   - FFmpeg (`winget install Gyan.FFmpeg`)
   - Claude Code CLI (`npm install -g @anthropic-ai/claude-code`) và chạy `claude login` bằng tài khoản gói thuê bao của chủ máy.
2. Tại thư mục dự án `c:\Project Video Creator`:
   ```powershell
   uv sync --frozen
   uv run videocreator
   ```
3. Để tự chạy cùng Windows: tích tuỳ chọn "Tự động chạy cùng Windows" trong bộ cài `VideoCreatorSetup.exe` hoặc tạo shortcut tới `installer\launch.vbs` trong thư mục `shell:startup`.
4. Cấu hình nguồn điện Windows (Power & Sleep):
   - Đặt **Sleep = Never** khi cắm điện.
   - Đặt **Active Hours** của Windows Update ngoài các khung giờ đăng bài (`08:00–22:00`).

## 2. Chuyển máy (Xuất / Nhập file `.vcx`)

1. Trên máy cũ: vào **Settings -> Xuất file .vcx**, đặt mật khẩu (>= 4 ký tự) và tải file `videocreator-export.vcx`.
   - File `.vcx` chứa `config.toml`, `app.db` và các khoá bí mật đã được mã hoá bằng `scrypt + Fernet`.
   - File `.vcx` **không** chứa thư mục `media/` và **không** chứa phiên đăng nhập CLI (`claude login`); trên máy mới cần tự chạy `claude login`.
2. Trên máy mới: vào **Settings -> Nhập cấu hình**, chọn file `.vcx` và nhập mật khẩu.
   - Mặc định sau khi nhập, máy mới được đặt `role = "client"` để tránh 2 máy cùng chạy Telegram bot gây lỗi `Conflict`.
   - Chỉ tích **"Đặt máy này làm máy chủ mới (`role = server`)"** khi bạn đã tắt hẳn máy chủ cũ.

## 3. Mở giao diện từ máy khác trong mạng nội bộ (LAN / Tailscale)

1. Vào **Settings -> Kho bí mật**, đặt giá trị cho khoá `UI_PASSWORD`.
2. Đổi `host = "0.0.0.0"` (hoặc IP LAN/Tailscale của máy chủ) và lưu lại.
3. Khi truy cập từ máy khác, trình duyệt sẽ yêu cầu mật khẩu HTTP Basic Auth (`UI_PASSWORD`). Không mở trực tiếp cổng HTTP trần ra Internet công cộng nếu không qua Tailscale hoặc Reverse Proxy HTTPS.
