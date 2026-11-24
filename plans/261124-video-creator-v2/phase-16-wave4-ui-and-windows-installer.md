# Phase 16: Giao diện Next.js Đợt 4, Bộ cài Windows `.exe` Inno Setup & Nghiệm thu Toàn phần (`V2-PKG-01..03`)

## Mục tiêu
1. Xây dựng giao diện Next.js 15 Đợt 4 trong `web-next/`:
   - `/welcome`: Welcome Wizard 4 bước (kiểm tra runtime, workspace, AI keys & ngân sách, giọng đọc mặc định).
   - `/novel`: Studio Tiểu thuyết đa chương sang Video kèm checkpoint resume.
   - `/podcast`: Studio Sóng nhạc Podcast (`16:9` / `9:16` / `1:1`).
   - `/lipsync`: Studio Lip-sync nhân vật & giọng nói.
   - Cập nhật `/settings` (Sao lưu & Khôi phục `.vcx`, mở lại Welcome Wizard) và `AppShell.tsx` (menu Đợt 4 + banner nhắc cấu hình lần đầu).
   - Chạy `tsc --noEmit`, `lint`, `next build` và `copy-standalone-assets.mjs` bằng Node 24 LTS.
2. Cập nhật đóng gói Windows Desktop (`installer/` + `scripts/build_nuitka.ps1` + `THIRD_PARTY_NOTICES.md`):
   - Nâng cấp `installer/videocreator.iss` lên **Video Creator V2** (`2.0.0`, gỡ `install_mpt.cmd`, đóng gói `web-next/.next/standalone` + Python + runtime tùy chọn, `THIRD_PARTY_NOTICES.md`).
   - Cập nhật `installer/post_install.cmd`, `installer/launch.vbs`, `installer/Install-VideoCreator.cmd`, `installer/stage_bundle.ps1`, `installer/build.ps1`, `paths.py`, và `scripts/build_nuitka.ps1` (biên dịch `.pyd` tùy chọn).
   - Biên dịch kiểm chứng `installer/dist/VideoCreatorV2Setup.exe` bằng `ISCC.exe`.
3. Viết `tests/test_v2_phase16_packaging_and_wave4_e2e.py` và chạy toàn bộ `uv run pytest -m local -q` đạt 100%.
