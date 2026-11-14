# Báo cáo Phase 18: Định tuyến ưu tiên gói thuê bao (Subscription-First Routing)

Ngày cập nhật: 2026-11-13
Cơ sở kiểm chứng: Spike S13 ([01-verification-results.md](01-verification-results.md)) và quyết định Hướng A của người dùng.

## 1. Nhà cung cấp CLI gói thuê bao chính: `claude_cli` (`claude -p`)

### 1.1 Đường dẫn thực thi trên Windows
- Không gọi qua `claude.cmd` hoặc `claude.ps1` vì npm shim trên Windows làm hỏng dấu nháy kép bên trong `--json-schema` (báo lỗi `--json-schema is not valid JSON`).
- Gọi trực tiếp file nhị phân `claude.exe` tại:
  `<npm_prefix>/node_modules/@anthropic-ai/claude-code/bin/claude.exe` (tìm tự động qua `shutil.which("claude")`).
- Không truyền cờ `--bare` vì `--bare` bỏ qua đăng nhập gói thuê bao và đòi `ANTHROPIC_API_KEY`.

### 1.2 Cờ không tương tác & Cô lập thư mục
- Chạy trong thư mục tạm rỗng riêng cho mỗi lời gọi (`tempfile.mkdtemp(prefix="vc-claude-")`), xoá ngay sau khi chạy xong để CLI không nạp `CLAUDE.md`, `.mcp.json` hay hook của dự án và không đọc được file ngoài thư mục tạm (`NFR-SEC-09`).
- Cờ cho `writer` / `checker` (chỉ văn bản):
  ```text
  claude.exe -p --model <sonnet|haiku|opus> --output-format json --json-schema <schema_json> --permission-mode dontAsk
  ```
- Cờ cho `vision` (đọc ảnh thu nhỏ từng shot):
  - Sao chép các ảnh thumbnail `shot_001.jpg`, `shot_002.jpg`, ... vào thư mục tạm.
  - Chỉ cấp quyền công cụ `Read`:
  ```text
  claude.exe -p --model sonnet --output-format json --json-schema <schema_json> --permission-mode dontAsk --allowedTools Read
  ```
- Prompt truyền qua `stdin` (`encoding="utf-8"`).

### 1.3 Định dạng đầu ra JSON của `claude -p`
Khi chạy với `--output-format json --json-schema ...`, stdout trả về một JSON object có cấu trúc:
```json
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "api_error_status": null,
  "num_turns": 2,
  "result": "...",
  "structured_output": { ... },
  "total_cost_usd": 0.086,
  "usage": {
    "input_tokens": 1200,
    "output_tokens": 450,
    "cache_read_input_tokens": 28000,
    "cache_creation_input_tokens": 0
  }
}
```
- Trường `structured_output` chứa dữ liệu đã khớp JSON Schema; được validate lại bằng Pydantic `schema.model_validate(data["structured_output"])`.
- Chi phí ghi vào `ai_usage`: `route = 'subscription'`, `cost_usd = 0.0`, `units_in = input_tokens`, `units_out = output_tokens`.

### 1.4 Phân loại lỗi CLI (`cli_base.py`)
1. **Hết hạn mức (`quota`)**:
   - Dấu hiệu trong `result` / `stderr` / `api_error_status`:
     - `api_error_status == 429`
     - Chuỗi chứa: `"rate limit"`, `"quota"`, `"usage limit"`, `"limit reached"`, `"resets at"`, `"try again in"`, `"overloaded"`
   - Hành động: nâng ngoại lệ `ProviderQuotaExhausted(provider="claude_cli", retry_after_s=...)`, đánh dấu `provider_state.resting_until = now + retry_after_s` (mặc định 3600 giây nếu không đọc được giờ hồi).
2. **Lỗi đăng nhập (`auth`)**:
   - Dấu hiệu: `api_error_status in (401, 403)` hoặc chuỗi chứa `"not logged in"`, `"please run claude login"`, `"authentication"`, `"invalid api key"`, `"unauthorized"`, `"oauth token"`.
   - Hành động: nâng `ProviderAuthError`, ghi nhận vào `provider_state.last_error` để báo người dùng đăng nhập lại trên máy chủ.
3. **Lỗi khác (`other`)**:
   - Timeout, lỗi cú pháp schema hoặc tiến trình con thoát khác 0 không thuộc 2 nhóm trên.

## 2. Trạng thái các đường khác (theo quyết định Hướng A)

- **`gemini_cli`**: Đã loại bỏ vì Google ngừng phục vụ tài khoản cá nhân trên Gemini CLI từ 18/06/2026.
- **`agy_cli` (Antigravity CLI)**: Tắt mặc định do mục 6 của Google Antigravity Additional Terms of Service chưa rõ ràng về việc phần mềm tự viết gọi `agy.exe`.
- **`gemini_api` & `claude_api`**: Đường API trả phí dự phòng, chịu sự kiểm soát của `budget.daily_usd` (mặc định 5 USD/ngày) và chính sách `ai.policy.api_fallback` (`auto` | `ask` | `never`).
- **`muse_api` (Meta Model API)**: Adapter tương thích OpenAI SDK, chỉ kích hoạt khi có khoá `MUSE_API_KEY` trong `secrets.enc`.
