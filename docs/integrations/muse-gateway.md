# Tích hợp Muse Gateway (`vc-hardened`) — Video Creator V2 (`2.4.0`)

Tài liệu kỹ thuật hướng dẫn cài đặt, vá bảo mật, vận hành đa luồng, kết nối từ xa qua Tailscale và sử dụng MCP cho tác nhân ngoài của **Muse Gateway** trong **Video Creator V2 (`2.4.0`)**.

---

## 1. Kiến trúc & Nguyên tắc Bảo mật Bắt buộc (`vc-hardened`)

- **Bản chất của Muse Gateway**: Tiến trình Next.js + `puppeteer-core` điều khiển trình duyệt Chromium/Edge không giao diện đăng nhập tài khoản `muse.ai` bằng cookie phiên, cho phép chạy song song **2 luồng render media / tài khoản** (`RENDERS_PER_ACCOUNT = 2`) với chi phí API `$0` (`route="subscription"`).
- **Lý do bắt buộc dùng bản vá `vc-hardened`**:
  - Repo gốc (`lynbyte/muse-gateway` v1.0.13) mặc định đặt `MUSE_CMD_MODE=auto` và quét mọi phản hồi của Muse để thực thi lệnh qua `cmd.exe` (`toolBridge.ts` + `museDriver.ts`), đồng thời đọc tệp cục bộ khi xuất hiện thẻ `<cwd>…</cwd>` trong prompt.
  - Bản vá chính thức lưu tại `tools/muse-gateway-patches/0001-vc-hardening.patch`:
    1. Khóa cứng `isCommandAllowed() -> false`, vô hiệu hóa `runLocalCommand()`, `extractWorkspaceCwd()`, `buildProjectContext()`.
    2. Xóa toàn bộ vòng lặp thực thi lệnh trong `museDriver.ts`.
    3. Khóa tự động cập nhật `POST /api/update -> 403` và `/v1/responses -> 410`.
    4. Trả cờ xác minh tại `GET /api/config`: `{"cmdMode": "off", "hardened": true, "fork": "vc-hardened"}`.
- **Cơ chế phòng vệ nhiều lớp của Video Creator V2**:
  - Trước mọi phiên ghép nối, khởi chạy sidecar hoặc điều phối tác vụ, `MuseGatewayClient.verify_ready_and_safe()` kiểm tra `cmdMode == "off"` và `hardened == true`. Nếu phát hiện gateway chưa vá, ứng dụng lập tức dừng sidecar và khóa hàng đợi ở trạng thái cảnh báo đỏ.
  - `sanitize_prompt()` lọc bỏ toàn bộ thẻ `<cwd>`, `<environment_context>` và ký tự điều khiển trước khi gửi sang gateway.
  - Proxy quản trị `muse_gateway/admin.py` loại bỏ hoàn toàn `cookies`, che mật khẩu proxy và không bao giờ gọi `?reveal=` trên khóa API.

---

## 2. Cài đặt & Khởi chạy Chế độ Local Sidecar (`127.0.0.1`)

### Bước 1: Chuẩn bị gói `muse-gateway` đã vá `vc-hardened`
```powershell
git clone https://github.com/lynbyte/muse-gateway.git
Set-Location muse-gateway
git checkout 6050d45
git apply c:\path\to\video-creating\tools\muse-gateway-patches\0001-vc-hardening.patch
npm ci
npm test
npm run build
```
Đặt thư mục đã build vào `<AppRoot>\tools\muse-gateway` hoặc cấu hình đường dẫn `muse_gateway.sidecar.gateway_entry` trong `config.toml`.

### Bước 2: Ghép nối 1 chạm & Đăng nhập Tài khoản Pool
1. Mở **Cài đặt → Muse Gateway** trong Video Creator V2.
2. Bấm **Khởi động / Gắn Sidecar** (chạy trên `127.0.0.1:1412` bằng Node 24 đóng gói sẵn, không lộ ra LAN).
3. Bấm **Kết nối 1 chạm (Pairing)** → bấm **1. Mở trang Allow trên Gateway** → chọn **Allow** → bấm **2. Hoàn tất lưu khóa**. Khóa API được mã hóa vào Windows DPAPI (`secrets.bin`) và tự động giới hạn quyền model (`muse-video`, `muse-image`, `muse-voice`, `muse-chat` + các Combo).
4. Trong mục **Tài khoản Muse & Chiến lược Pool**, bấm **Đăng nhập thêm tài khoản** để mở Chrome đăng nhập `muse.ai`; hệ thống tự động bắt cookie và xoay vòng theo `round-robin` / `fallback` / `fusion`.

---

## 3. Chế độ Máy Chủ Từ Xa (LAN / Tailscale HTTPS)

Khi chạy cụm trình duyệt Muse trên một máy trạm riêng có RAM lớn (16–32 GB) cho nhiều máy biên tập dùng chung:
1. Trên máy chủ Gateway: chạy bản `vc-hardened` phía sau Tailscale Serve (`https://<machine>.<tailnet>.ts.net`) hoặc reverse proxy TLS nội bộ.
2. Trên máy biên tập Video Creator V2:
   - Mở **Cài đặt → Muse Gateway**, chọn chế độ **Remote / Tailscale HTTPS** và điền URL `https://...`. (Ứng dụng từ chối `http://` không mã hóa ra ngoài IP công cộng).
   - Tích xác nhận gateway từ xa đang chạy bản `vc-hardened` (được ghi nhận vào `audit_log`) và lưu khóa API vào **Kho Khóa API** (`MUSE_GATEWAY_API_KEY`).
   - Ở chế độ `remote`, toàn bộ các route `/api/v1/muse/admin/*` tự động bị khóa (`403`) để bảo vệ thông tin phiên đăng nhập trên máy chủ.

---

## 4. Điều Phối Đa Luồng Không Chặn & Toàn bộ Điểm Nối Trong App

- **Bộ điều phối nền (`muse_gateway/dispatcher.py`)**: Chạy định kỳ mỗi 5 giây + nhận Webhook ký HMAC-SHA256 (`POST /api/v1/integrations/muse/webhook`). Không giữ worker `io` hay `compute` của ứng dụng trong thời gian chờ Muse render (2–6 phút).
- **Công thức năng lực**: `capacity = min(max_parallel, số_tài_khoản_hợp_lệ × renders_per_account)`, chia lượt công bằng (`round-robin`) giữa các Workspace và tuân thủ trần an toàn/tài khoản/ngày (`daily_cap_video_per_account`).
- **Tải media tức thì**: Ngay khi task hoàn tất, tệp `.mp4`/`.png`/`.mp3` được tải ngay về `media/` của ứng dụng để không bị mất khi gateway dọn bộ nhớ tạm.
- **Các điểm nối tính năng**:
  - **Muse Studio (`/muse`)**: Tạo video đơn, nhân bản 2–8 biến thể song song, **Sửa tiếp** trên cùng `thread_url` + `account_id`, **Storyboard nhiều cảnh** nối khung hình cuối (FFmpeg `-sseof -0.15`), sinh lô 1–4 ảnh và thu giọng WAV 48kHz.
  - **Nhân vật & Ảnh AI (`/characters`)**: Chuỗi dự phòng tự động `Google Imagen 3 → Muse Image → Nền đồ họa local`, kèm nút **Tạo 4 biến thể bằng Muse**.
  - **Giọng đọc TTS (`voice.vi_provider = "muse"`)**: 7 giọng Việt + 2 giọng Anh (`muse:<Voice Name>`), tự tách câu văn bản dài và cắt khoảng lặng bằng `trim_voice_silence` (`-45 dBFS`).
  - **Chat Provider (`muse_gateway`)**: Tương thích OpenAI JSON-schema (`$0`, `route="subscription"`), người dùng có thể thêm vào `ai.routes.writer` / `translator` / `checker`.
  - **Studios, Workflows, Autopilot, Trends & Telegram**: Tùy chọn `visual_source = "muse_video"` (tạm nghỉ `waiting_media` rồi tự động dựng tiếp khi đủ clip) cho **Tin tức**, **Tiểu thuyết**, **Batch A/B**; 3 nút đồ thị `muse_video_node`, `muse_image_node`, `muse_voice_node`; nguồn Autopilot `muse_video`; **Remix chuyển động** từ clip xu hướng (`full_ai` + xác nhận quyền); lệnh Telegram `/vid`, `/img`, `/voice`.

---

## 5. Sử dụng MCP của Muse Gateway cho Tác Nhân Ngoài (Claude Desktop / Cursor)

- Theo ràng buộc bảo mật nội bộ (`FR-STD-10`), `studio/agent.py` bên trong Video Creator V2 **không nối MCP, không chạy shell và không truy cập web**.
- Nếu lập trình viên muốn gọi trực tiếp công cụ tạo media của Muse từ Claude Desktop hoặc Cursor bên ngoài ứng dụng, có thể trỏ cấu hình MCP của công cụ ngoài vào `http://127.0.0.1:1412/v1/mcp` trên bản **fork `vc-hardened`** (với khóa API riêng đã giới hạn model).
