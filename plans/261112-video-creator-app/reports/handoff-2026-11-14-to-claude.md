# Báo cáo bàn giao sang Claude Code (2026-11-14)

Tài liệu này tổng hợp toàn bộ kết quả đã kiểm chứng, thay đổi mã nguồn, cấu hình runtime và trạng thái dữ liệu tính đến **2026-11-14 12:24 (GMT+7)** để Claude Code tiếp tục triển khai từ hiện trạng thực tế trong `c:\Project Video Creator\`.

> **Lưu ý bảo mật:** Toàn bộ giá trị khóa bí mật (`TELEGRAM_BOT_TOKEN`, `YOUTUBE_API_KEY`, `GEMINI_API_KEY`) được lưu cục bộ trong `C:\Users\DELL 7590\AppData\Local\VideoCreator\secrets.bin` và `spikes/.env` (đều không commit vào git). Không ghi khóa thật vào báo cáo hay code.

---

## 1. Kiểm tra `/migrate-workflows`

- Đã quét các thư mục workflow cũ toàn cục (`~/.gemini/config/global_workflows`, `~/.gemini/config/workflows`) và trong workspace (`c:\Project Video Creator\{.agents,_agents,.agent,_agent}\workflows`).
- Kết quả: **Không tồn tại file workflow cũ nào** (`wf_dirs existing: []`), nên không cần chuyển đổi hay dọn dẹp legacy workflow. Hệ thống command/agent/skill của Claude nằm sẵn trong `.claude/` và kế hoạch nguồn nằm trong `plans/261112-video-creator-app/`.

---

## 2. Thay đổi mã nguồn đã thực hiện trong repo (`c:\Project Video Creator\`)

1. **`src/videocreator/config.py`**:
   - Trong `_default_prices()`, đã thêm cấu hình giá cho `"gemini-2.5-flash"` (`input_per_million_usd=0.15`, `output_per_million_usd=0.60`) bên cạnh `"gemini-3.8-flash"`.
2. **`src/videocreator/trends/analyse.py`**:
   - Nâng `REA_DECOMPOSE_TIMEOUT_S = 1800` (từ 600s lên 1800s cho video tham khảo dài ~3 phút chạy CPU).
   - Khôi phục lệnh chạy **đủ bước** của `rea-video decompose` trong `run_rea_decompose_reference`:
     `[rea_bin, "decompose", str(video_path), "-o", str(out_dir), "--no-vlm", "--lang", "en"]` (không dùng `--no-ocr --no-stems --no-packaging`).
   - Thêm `_has_full_rea_cache(out_dir)` (kiểm tra `stems/` hoặc khóa `"packaging"` trong `breakdown.json`) và `_read_rea_outputs(out_dir)` để đọc lại `VIDEO.md`, `timeline.md`, `*storyboard*.jpg` nếu cache đủ bước đã tồn tại.
3. **`src/videocreator/trends/suggest.py`**:
   - Trong `summarize_shot_library`, đổi thứ tự truy vấn SQL sang ưu tiên các shot đã có mô tả trước:
     `ORDER BY (description IS NOT NULL AND description != '') DESC, quality DESC, id ASC`.
   - Trong `make_suggestions`, cập nhật prompt yêu cầu AI điều chỉnh nhịp/cấu trúc theo kho shot hiện có và ghép `recommended_shot_ids` thực tế; nếu `cand.recommended_shot_ids` khác rỗng thì chuẩn hóa `missing_shots = ""` và bỏ hậu tố `(cần quay thêm: ...)` khỏi `text` để thẻ Telegram Topic `Xu hướng` luôn hiện nút **`🎬 Tạo 1 video`** và **`🎬 Tạo 3 bản`** (thay vì chỉ hiện `Bỏ qua`).

### Kiểm thử đã chạy gần nhất sau lần sửa cuối:
- `.venv\Scripts\pytest.exe tests/test_tg_messages.py tests/test_suggestion_flow.py -q` -> **5 passed in 1.70s**.

---

## 3. Cấu hình môi trường & runtime (`C:\Users\DELL 7590\AppData\Local\VideoCreator\`)

- **Máy chủ FastAPI + JobWorker + Telegram Bot**: đang chạy tại `http://127.0.0.1:8765` (`GET /health` trả về `{"status":"ok","role":"server","version":"0.1.0"}`).
- **`secrets.bin`** (và `spikes/.env`): đã lưu `TELEGRAM_BOT_TOKEN` (`@VideoCreatorSocialBot`), `YOUTUBE_API_KEY`, `GEMINI_API_KEY` (`spikes/.env` còn có `TELEGRAM_TEST_CHAT_ID`).
- **`config.toml`**:
  - `ai.policy.api_fallback = "auto"`
  - `ai.gemini_model = "gemini-3.6-flash"` (đã đổi từ `"gemini-3.8-flash"` do free-tier của `gemini-3.8-flash` chạm trần `20` request/ngày trong đợt describe; có đủ bảng giá `[prices."gemini-2.5-flash"]`, `[prices."gemini-3.8-flash"]`, `[prices."gemini-3.6-flash"]`).
  - Các role `vision`, `writer`, `checker`, `studio` xếp `"claude_cli"` đầu tiên và `"gemini_api"` dự phòng ngay sau.
  - `[telegram]`: `allowed_chat_ids = [-1004423070089]`, `approver_user_ids = [8273197414]`.
- **Bảng `settings` trong `app.db`**:
  - `tg_topics_json`: Group `VideoCreator_SS`, `chat_id = -1004423070089`, `threads = {"trends": 3, "approvals": 4, "posted": 5, "manual": 6, "alerts": 7, "reports": 8}`.

---

## 4. Trạng thái dữ liệu & sản phẩm thực tế trong `app.db` và `media/`

- **Sản phẩm (`products`, 5 mục)**:
  1. `Nhẫn bạc S925` (`Bạc S925`)
  2. `Khuyên tai bạc S925` (`Bạc S925`)
  3. `Xúc xắc bạc S925` (`Bạc S925`)
  4. `Đinh tán bạc S925` (`Bạc S925`)
  5. `Mặt dây chuyền bạc S925` (`Bạc S925`)
- **Footage thật từ Google Drive (`PROCESS`, folder `1QhUZbn00Lfv4wJtiVTfnyCM2_NXe4scJ`)**:
  - Đã tải 9 file `.mov` về `media/gdrive_import/`: `01_XUC_XAC.mov`, `02_NHAN_MOI.mov`, `02_NHAN_MOI_RAW.mov`, `03_PROCESS_DEMO.mov`, `04_ADS_TI_NI.mov`, `04_TI_NI.mov`, `05_CBDG.mov`, `06_SLAN_RING.mov`, `07_BELT.mov`.
  - Đã chuẩn hóa sang `footage/1.mp4` .. `footage/9.mp4` (đều `status = 'analysed'`), tách tổng cộng **120 shots** trong bảng `shots`:
    - Footage `#1..#3`: **24 shots** đã có `description` chi tiết.
    - Footage `#4..#9`: **96 shots** đã tách xong bằng `rea-video`, đang đợi job `describe` (`#10, #12, #14, #16, #18, #20` ở trạng thái `waiting_quota`).
- **Xu hướng & phân tích tham khảo**:
  - Watchlist `#1`: `youtube / keyword = 'handcrafted silver ring'`.
  - Đã quét **15 `trend_items`** từ YouTube Data API v3; video top #1 (`uXKZIjBL9hU`, tác giả `AdamJewellery`) đã tải về `reference/ref_1.mp4`, chạy đủ `rea-video decompose` vào `reference/rea_1/` (`1222.2s`), và phân tích cấu trúc lưu `analysis_json`.
  - Đã tạo lại **2 đề xuất xu hướng** (`suggestions` `#4` `Craftsmanship ASMR Showcase` và `#5` `Raw to Refined Transformation`) khớp trực tiếp `shot_id` trong kho shot hiện tại (`missing_shots = ""`). Cả hai đều được người dùng bấm chọn **`🎬 Tạo 3 bản`** trên Telegram (`status = 'accepted'`).
- **Video đã dựng (`videos`)**:
  - `video_1.mp4` .. `video_7.mp4`: các bản dựng trực tiếp từ footage trước đó (`suggestion_id = NULL`, `pending_approval`).
  - `video_8.mp4` (`6.9/10`, `superseded`), `video_9.mp4` (`6.7/10`, `superseded`), **`video_10.mp4`** (`15.30s`, `suggestion_id = 4`, **`quality_score = 8.8/10`**, `pending_approval`, đã gửi sang Telegram `Chờ duyệt`), `video_11.mp4` (`6.9/10`, `superseded`, `suggestion_id = 5`), `video_13.mp4` (`14.13s`, `suggestion_id = 4`, `pending_approval`), cùng `video #12` (`waiting_quota`) và `#14` (`scoring` khi chụp trạng thái).

---

## 5. Việc cần Claude Code làm tiếp

1. **Hoàn tất mô tả 96 shot còn lại (`footage #4..#9`)**:
   - Phiên hạn mức của `claude_cli` có lịch hồi lúc `12:20pm (Asia/Bangkok)`. Kiểm tra bảng `provider_state` và `jobs` (`#10, #12, #14, #16, #18, #20`, `#27`), xóa cooldown cũ nếu đã qua hạn và đưa các job `waiting_quota` về `queued` (hoặc chạy trực tiếp bằng `claude_cli` khi phiên mới hoạt động) để toàn bộ 120 shot đều có `description`.
2. **Hoàn thiện các spike/phase đăng bài thật (khi người dùng cung cấp tài khoản/key)**:
   - **S2, S3, S4, Phase 07/11/15**: Lấy token Meta/Instagram/Threads/TikTok và Cloudflare R2 bucket để test đăng thật (`pytest -m live`).
   - **S8 / Phase 09**: Nghe thử giọng đọc tiếng Việt (MoneyPrinterTurbo / Edge TTS) nếu người dùng muốn bật lồng tiếng (`default_voice_lang` hiện là `"none"`).
   - **Phase 17 (Studio)**: Thử dựng 1 bản Studio hoàn chỉnh kết hợp dữ liệu phân tích xu hướng `reference/rea_1/`.
3. **Commit git gọn gàng (khi người dùng yêu cầu)**:
   - Repo chưa tạo commit đầu và `git` chưa đặt `user.name`/`user.email`; mọi file bí mật (`.env`, `spikes/.env`, `secrets.bin`) phải tiếp tục được `.gitignore` loại trừ.
