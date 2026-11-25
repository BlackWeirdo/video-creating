# Báo cáo Bảo mật Fork & Quy trình Đo kiểm PoC — Muse Gateway (`vc-hardened`)

## 1. Bản vá bảo mật bắt buộc (`tools/muse-gateway-patches/0001-vc-hardening.patch`)

Bản vá áp trên `lynbyte/muse-gateway` @ `6050d45` (`v1.0.13`) triệt tiêu toàn bộ bề mặt thực thi lệnh từ xa (RCE) và đọc ngữ cảnh thư mục:

1. **`src/lib/toolBridge.ts`**:
   - `isCommandAllowed()` luôn trả `false` bất kể biến môi trường.
   - `runLocalCommand()` luôn ném lỗi từ chối thực thi.
   - `extractWorkspaceCwd()` trả `null` và `buildProjectContext()` trả chuỗi rỗng `""`.
2. **`src/lib/museDriver.ts`**:
   - Xóa hẳn vòng lặp đọc lệnh `parseCommandRequests` / `runLocalCommand` trong `chat()`, chỉ giữ nhánh tự trả lời câu hỏi làm rõ (`clarification`) và bù số lượng ảnh (`topUpFor`).
3. **`src/app/api/config/route.ts`**:
   - Trả cố định `cmdMode: "off"`, `hardened: true`, `fork: "vc-hardened"` để Video Creator V2 kiểm chứng (`assert_hardened_config_payload`) trước khi ghép nối hoặc gửi bất kỳ tác vụ nào.
4. **`src/app/api/update/route.ts`**:
   - Chặn `POST /api/update` (`HTTP 403`) để tránh tự chạy `npm i -g` ghi đè bản đã vá bằng bản upstream chưa vá.
5. **`src/app/v1/responses/route.ts`**:
   - Trả `410 Gone` cho `/v1/responses`.

### Lệnh áp bản vá và chạy unit test của Gateway

```powershell
git clone https://github.com/lynbyte/muse-gateway.git muse-gateway-vc
Set-Location muse-gateway-vc
git checkout 6050d45
git apply ..\video-creating\tools\muse-gateway-patches\0001-vc-hardening.patch
node --import ./scripts/test-resolve.mjs --test src/lib/gateway.test.ts src/lib/mcp.test.ts
```

---

## 2. Chạy Đo kiểm PoC Thực tế (Cổng quyết định ≥ 80% thành công)

Sau khi khởi động bản `vc-hardened` và đăng nhập tối thiểu **2 tài khoản Muse phụ** trong tab Cài đặt -> Muse Gateway:

```powershell
.\.venv\Scripts\python.exe scripts\benchmark_muse_gateway_poc.py `
  --base-url http://127.0.0.1:1412 `
  --api-key "<MUSE_GATEWAY_KEY>" `
  --count 10 `
  --duration 8 `
  --out-json logs\muse_poc_report.json
```

Tiêu chí đạt cổng vận hành sản xuất:
- `hardened: true` (`cmdMode == "off"`).
- `success_rate_pct >= 80.0` (tối thiểu 8/10 video 8s hoàn tất không lỗi).
- Máy chạy ≥ 3 tài khoản Muse song song khuyến nghị RAM ≥ 16 GB (mỗi tab headless tiêu thụ ~250–350 MB RAM).
