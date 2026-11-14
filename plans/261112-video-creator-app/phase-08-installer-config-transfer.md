# Phase 08: Bộ cài .exe + xuất/nhập cấu hình + headless

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 07](phase-07-posting-facebook-instagram.md) (hoặc bất kỳ lúc nào sau phase 05 nếu muốn thử bộ cài sớm)
- Docs: [research 02 mục 5](research/researcher-02-video-pipeline-and-packaging.md)

## Overview

- Ngày: 2026-11-12
- Mô tả: file cài Inno Setup cho Windows; nút xuất/nhập cấu hình để chuyển máy; mật khẩu khi mở UI từ máy khác; tự chạy cùng Windows. Chạy headless trên Linux VPS là TUỲ CHỌN, cắt được (máy chủ đã chốt là PC Windows bật 24/7).
- Ưu tiên: P1 (tiêu chí tuần 1, nhưng cắt được nếu trượt)
- Trạng thái triển khai: hoàn thành (2026-11-13)
- Trạng thái review: đã kiểm thử (`pytest -m local`)

## Key Insights

- Không PyInstaller (rea-video + onnxruntime/opencv + subprocess dễ lỗi hidden import).
- Venv của uv không chắc di dời được -> cách chính: bộ cài kèm `uv.exe` + source + `uv.lock`, sau khi copy chạy `uv sync --frozen` tại máy đích (cần internet, app vốn cần internet). Lùi: venv dựng sẵn bằng `uv venv --relocatable`.
- Dependency dạng git cần `git` trên máy đích -> rea-video (nếu dùng) đóng thành wheel đặt trong `vendor/`, cài vào venv riêng `tools/rea`.
- `secrets.bin` mã hoá DPAPI không mang sang máy khác được -> export phải giải mã rồi mã hoá lại bằng mật khẩu người dùng nhập.
- Export KHÔNG gồm `media/` (quá nặng); muốn mang footage thì copy thư mục tay.

## Requirements

- `VideoCreatorSetup.exe`: cài vào `{localappdata}\Programs\VideoCreator` (không cần admin), shortcut Start Menu + Desktop, gỡ cài đặt được; dữ liệu `%APPDATA%\VideoCreator` giữ lại khi gỡ.
- Bộ cài kèm: source, `uv.exe`, `uv.lock`, `ffmpeg.exe` + `ffprobe.exe`, font, wheel vendor. Kiểm tra WebView2 Runtime, thiếu thì chạy bootstrapper Evergreen.
- Shortcut chạy không hiện cửa sổ console.
- Settings: "Xuất cấu hình" -> `videocreator-export.vcx` (zip: `config.toml`, `app.db`, `secrets.enc`); "Nhập cấu hình" hỏi mật khẩu. Nhập trên máy mới đặt `role = "client"` trừ khi người dùng chọn "máy này là máy chủ mới" (tránh 2 máy cùng chạy bot).
- Máy chủ Windows: tuỳ chọn trong bộ cài "Chạy cùng Windows" (shortcut trong Startup); `docs/install.md` hướng dẫn tắt sleep/hibernate và đặt giờ hoạt động của Windows Update ngoài khung giờ đăng.
- Tự cập nhật (cắt được; ý tưởng từ Muse2Tele, tự viết): app kiểm tra file phiên bản ở nơi người dùng cấu hình (thư mục chia sẻ hoặc GitHub Releases của chính họ), báo trên trang chủ + Telegram, bấm để tải bộ cài mới; sao lưu `app.db` + config trước khi cập nhật. Không tự cài khi chưa bấm.
- Bộ cài phải build lại sau phase 09 (thêm `tools/mpt` cho MoneyPrinterTurbo: tải lúc cài, không nhét vào file .exe), sau phase 13 (thêm `yt-dlp`) và phase 17 (thêm `vendor/skills/`, nút kiểm tra Node.js); ghi phiên bản bộ cài trong trang Settings.
- (Tuỳ chọn) Headless Linux: `uv run videocreator --headless --host 0.0.0.0 --port 8765`; file mẫu systemd.
- Khi host khác `127.0.0.1`: bắt buộc đặt mật khẩu UI (HTTP Basic, 1 mật khẩu chung); thiếu mật khẩu thì từ chối khởi động.

## Architecture

```
installer/videocreator.iss      # Inno Setup script
installer/build.ps1             # gom file, tải ffmpeg/uv theo phiên bản ghim, gọi ISCC
installer/post_install.cmd      # uv sync --frozen; tạo venv tools/rea; in log
installer/launch.vbs            # chạy pythonw -m videocreator không console
deploy/videocreator.service     # systemd mẫu
src/videocreator/transfer.py    # export_config(password) / import_config(file, password, as_server)
src/videocreator/auth.py        # middleware Basic auth khi bind ngoài localhost
```

- `secrets.enc`: scrypt(password) -> khoá Fernet (`cryptography`).
- Import: dừng worker/bot -> thay file -> migrate -> yêu cầu khởi động lại app.

## Related code files

Tạo: các file trên; `tests/test_transfer.py`; `docs/install.md` (cài máy mới + chuyển máy + VPS).
Sửa: `__main__.py` (cờ host, kiểm tra mật khẩu), `app.py` (middleware), trang Settings, `paths.py` (ffmpeg bundle).

## Implementation Steps

1. `transfer.py` + nút Settings. Test `-m local`: export -> import vào thư mục dữ liệu tạm khác, đọc lại được secret; sai mật khẩu báo lỗi, không ghi đè.
2. `auth.py` + kiểm tra khởi động. Test local: request thiếu mật khẩu nhận 401 (TestClient trên app thật).
3. `build.ps1`: ghim phiên bản uv, FFmpeg (ghi nguồn + license build), tạo thư mục staging.
4. `videocreator.iss`: Files, Icons, Run (`post_install.cmd`), kiểm tra WebView2 qua registry.
5. Build, cài trên máy dev vào đường dẫn khác, chạy thử.
6. Checklist tay trên MÁY THỨ HAI sạch (cần người dùng): cài, mở app, nhập file export, render 1 video, bấm giờ.
7. (Tuỳ chọn, chỉ khi người dùng có VPS) Chạy headless trên VPS Linux: `uv sync`, cài ffmpeg bằng apt, mở UI qua trình duyệt với mật khẩu.

## Todo list

- [x] Export/import + test (`transfer.py`, `test_transfer.py`)
- [x] Basic auth khi bind ngoài localhost (`auth.py`)
- [x] Script build + staging (`installer/build.ps1`, `installer/post_install.cmd`, `installer/launch.vbs`)
- [x] Inno Setup script (`installer/videocreator.iss`)
- [x] Tự chạy cùng Windows + hướng dẫn tắt sleep (`docs/install.md`)
- [x] File mẫu systemd (`deploy/videocreator.service`)
- [x] `docs/install.md`

## Success Criteria

- Máy thứ hai: từ file `.exe` + file export đến lúc mở được app có đủ tài khoản, < 15 phút.
- Sau nhập cấu hình ở máy thứ hai, bot KHÔNG chạy ở đó (role client) trừ khi chọn làm máy chủ.
- Máy khác trong mạng nội bộ mở được UI của máy chủ qua trình duyệt, UI đòi mật khẩu.
- Khởi động lại máy chủ: app tự chạy, bot trả lời `/status` mà không ai phải mở app.

## Risk Assessment

- `uv sync` lúc cài hỏng do mạng/proxy -> bộ cài báo lỗi rõ + nút chạy lại; phương án lùi venv relocatable.
- SmartScreen cảnh báo exe chưa ký: chấp nhận (nội bộ), ghi trong hướng dẫn. Không mua chứng chỉ ký (YAGNI).
- rea-video trên máy đích lỗi dù máy dev chạy: nếu xảy ra, chuyển hẳn sang nhánh PySceneDetect.
- Dễ trượt: lỗi chỉ lộ ra trên máy sạch. Nếu hết tuần 1: máy chủ chạy bằng `uv run`, bộ cài sang tuần 2.

## Security Considerations

- File export chứa toàn bộ token -> luôn mã hoá bằng mật khẩu; cảnh báo không gửi qua chat không mã hoá.
- Bind `0.0.0.0` chỉ nên dùng trong LAN/Tailscale hoặc sau reverse proxy HTTPS; Basic auth trên HTTP trần qua internet là không an toàn, ghi rõ trong `docs/install.md`.
- FFmpeg build GPL: dùng nội bộ không phát hành ra ngoài thì ổn; ghi nguồn build trong repo.

## Next steps

- Hết phạm vi tuần 1 (cùng phase 09). Tuần 2 bắt đầu ở phase 10.
