# Đặc tả phần mềm: Video Creator V2 — AI Multi-Studio Platform

Phiên bản đặc tả: 2.0, ngày 2026-11-24 (nhánh `v2`).  
Kế hoạch triển khai đi kèm: [plans/261124-video-creator-v2/plan.md](../plans/261124-video-creator-v2/plan.md).  
Đặc tả V1 tham chiếu: [docs/video-creator-spec.md](video-creator-spec.md).

---

## 1. Tầm nhìn & Định vị Sản phẩm

**Video Creator V2** là nền tảng **AI Multi-Studio Đa thương hiệu / Đa chủ đề** chạy độc lập như một ứng dụng Desktop hoàn chỉnh trên từng máy nhân viên Windows (`%LOCALAPPDATA%\VideoCreatorV2` hoặc `VIDEOCREATOR_DATA`), hợp nhất toàn bộ thế mạnh của:

1. **`video-creating` (V1)**: Quét xu hướng 5 nguồn (YouTube, TikTok, Instagram Reels, Facebook Reels, Meta Ad Library qua Apify), bóc công thức bằng `rea-video`, kiểm soát dữ kiện sản phẩm, hàng đợi duyệt + Telegram Bot, đăng bài chính thức và đo số liệu hiệu quả.
2. **Hậu kỳ & Việt hóa gọn nhẹ (kiểu `iContent`)**: Tải/nhập video nguồn, tách nhạc/tiếng động nền (`UVR MDX-Net`), chép lời & lấy mốc thời gian (`Whisper`), dịch ép ngân sách âm tiết, 3 chế độ xử lý chữ cứng (`hardsub`), auto-ducking nhạc nền (`sidechaincompress`), chuẩn hóa `-14 LUFS`, phụ đề ASS nhảy từng chữ, QC tự động FFmpeg.
3. **Quy mô Multi-Studio & Nhân bản (kiểu `iCast`)**: Giao diện Next.js 15 / React 19 hiện đại, Video Style Engine (6 kiểu phụ đề, SFX, intro/outro, dựng lại đổi style nhanh), Tạo Batch & Biến thể A/B, Nhân vật & Ảnh AI đồng nhất, Tin tức → Video, Trình dựng kéo-thả FreeCut (MIT), Bảng vẽ Workflow Node (`@xyflow/react`), Tiểu thuyết / Podcast / Lip-sync, và Kênh Tự Chạy (Autopilot).

### 1.1 Nguyên tắc vận hành độc lập trên mỗi máy
- Mỗi bản cài đóng gói `.exe` (Inno Setup + Python + Node standalone + FFmpeg + `yt-dlp`) hoạt động **độc lập 100%** như phần mềm thương mại:
  - Có màn hình thiết lập ban đầu (**Welcome Wizard**) và bộ **Sao lưu / Khôi phục cấu hình**.
  - Tự nhập & xoay vòng nhiều API Keys (Gemini, Claude, OpenAI-compat, fal.ai, ElevenLabs...), ưu tiên gói thuê bao (`claude -p`, `gemini -p`) kèm trần chi phí ngày/tháng.
  - Tự kết nối OAuth tài khoản MXH phụ trách; duyệt bài trực tiếp trên giao diện App hoặc gắn Bot Telegram riêng (không dùng chung Bot Long-Polling giữa nhiều máy để tránh xung đột `409 Conflict`).
- Lưu trữ bảo mật: API Keys mã hóa cục bộ (DPAPI trên Windows / Fernet AES-128-CBC + HMAC-SHA256) trong `secrets.bin` / bảng cấu hình mã hóa; không bao giờ lộ ra log hay JSON API.

---

## 2. Mô hình Đa Thương hiệu (`Workspace`) & Chính sách Nội dung

Mọi dữ liệu nghiệp vụ được phân tách theo `workspace_id` trong cùng cơ sở dữ liệu SQLite (WAL), cho phép chuyển nhanh Workspace trên thanh Sidebar mà vẫn dùng chung kho Giọng đọc, Nhạc nền/SFX gốc, Model AI cục bộ và API Keys của máy.

### 2.1 Cấu hình mỗi `Workspace` (`V2-WS-01..04`)

| Thuộc tính | Giá trị cho phép | Ý nghĩa |
|---|---|---|
| `slug` | Chuỗi duy nhất (`default`, `bac-s925`, ...) | Định danh không gian làm việc |
| `name` | Chuỗi hiển thị | Tên thương hiệu / dự án / cụm kênh |
| `niche` | `general`, `jewelry`, `news`, ... | Ngành hàng / chủ đề gợi ý |
| `content_policy` | `strict_footage` \| `hybrid_remix` \| `full_ai` | Luật kiểm soát hình ảnh & nguồn video |
| `approval_mode` | `single` \| `bulk` \| `autopilot` | Cơ chế duyệt trước khi đăng |
| `default_aspect_ratio` | `9:16` (mặc định) \| `16:9` \| `1:1` | Tỉ lệ khung hình ưu tiên |
| `style_preset` | ID preset phong cách | Phong cách phụ đề/nhạc mặc định |

### 2.2 Ba chế độ kiểm soát nội dung (`content_policy`)

1. **`strict_footage` (Kênh Thương hiệu Chính — giữ trọn luật V1 `BR-PRD-*`)**:
   - Hình ảnh chứa sản phẩm **bắt buộc 100% từ footage tự quay**; cấm dùng bộ lọc màu/làm mịn/biến dạng AI trên `has_product = 1`.
   - Mọi thông số sản phẩm trong lời thoại/caption đối chiếu trực tiếp từ bảng `products`.
   - Video tham khảo xu hướng chỉ dùng phân tích công thức (`BR-REF-01..03`).
2. **`hybrid_remix` (Kênh Bán-Reup / Chuyển đổi)**:
   - Cho phép nhập video nguồn để Việt hóa/lồng tiếng hoặc ghép cảnh phụ, nhưng **cho phép tráo các cảnh cận/giới thiệu sản phẩm bằng shot thật** trong kho `shots` của Workspace.
3. **`full_ai` (Kênh Vệ tinh / Traffic / Truyện / Tin tức / Podcast)**:
   - Mở khóa toàn bộ AI sinh ảnh, AI video, nhân vật cố định, tin tức, tiểu thuyết và Việt hóa Reup đầy đủ (kèm biến đổi chống trùng lặp nội dung).

---

## 3. Kiến trúc Hệ thống 2 Tiến trình & Hàng đợi 2 Làn

### 3.1 Kiến trúc Tổng thể

```
┌─────────────────────────── Desktop Windows App ───────────────────────────┐
│  Launcher (pythonw / Electron-free app window: Edge/Chrome --app)          │
│   ├─ Frontend: Next.js 15 Standalone + React 19 + Tailwind v4 (port 3000)  │
│   │    └─ Rewrite /files/* & API calls -> http://127.0.0.1:8765/api/v1/*   │
│   └─ Backend: Python 3.11 + FastAPI + stdlib sqlite3 (WAL) (port 8765)     │
│        ├─ REST JSON API (/api/v1/*) + SSE (/api/v1/events, /logs/tail)     │
│        ├─ Dual-Lane JobWorker:                                             │
│        │    ├─ Làn `io` (mặc định 4 luồng): tải, quét trend, dịch, TTS, API│
│        │    └─ Làn `compute` (1–2 luồng): FFmpeg render, ASR, UVR, Remotion│
│        ├─ APScheduler (lịch đăng 5 MXH, quét trend, Autopilot, báo cáo)    │
│        └─ Subprocesses: ffmpeg, ffprobe, yt-dlp, rea-video, claude/gemini  │
└────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 Hàng đợi 2 Làn & Điều khiển Toàn cục (`V2-JOB-01..04`)
- Tách bạch hoàn toàn các tác vụ nhẹ/chờ mạng (**làn `io`**, cấu hình `worker.io_concurrency = 4`) khỏi các tác vụ nặng CPU/GPU (**làn `compute`**, cấu hình `worker.compute_concurrency = 1..2`) để việc quét trend, tải clip hoặc gọi API AI không bao giờ làm treo render FFmpeg và ngược lại.
- Hỗ trợ nút **Tạm dừng / Chạy tiếp toàn cục** (`POST /api/v1/queue/pause`, `POST /api/v1/queue/resume`): khi tạm dừng, các job đang chạy hoàn tất an toàn và worker không nhận job mới cho tới khi được bật tiếp.
- Mỗi bản ghi `jobs` lưu `workspace_id`, `lane` (`io`|`compute`), `progress` (`0.0..1.0`), `step` (bước hiện tại), `priority` (`10` user, `5` pinned, `0` background) và phục hồi tự động khi app khởi động lại.

---

## 4. Engine Hậu kỳ Nội bộ & Hệ thống AI

### 4.1 Tự chủ Pipeline FFmpeg & Gỡ bỏ MoneyPrinterTurbo (`V2-STY-01..05`)
- Gỡ bỏ sự phụ thuộc vào dịch vụ phụ **MoneyPrinterTurbo**, chuyển toàn bộ công đoạn ghép giọng, phụ đề, nhạc nền, SFX và khung hình về module nội bộ trong `src/videocreator/pipeline/`:
  - **Video Style Engine**: 6 kiểu phụ đề ASS động (`word_timings` karaoke/tô chữ kiểu TikTok, ô màu, neon, viền đậm, chữ tối giản, song ngữ) tuân thủ vùng an toàn `SafeZone`.
  - **Âm thanh thông minh**: Ngắt khoảng lặng đầu/cuối giọng đọc (`silenceremove`), tự cân bằng âm lượng, **Auto-Ducking** nhạc nền dưới giọng đọc bằng FFmpeg `sidechaincompress`, chuẩn hóa đầu ra `-14 LUFS`, chèn SFX chuyển cảnh ("vút", "ting") và thẻ Intro/Outro theo Workspace.
  - **Ép ngân sách âm tiết & Khớp shot**: Tính giới hạn âm tiết theo thời lượng shot ngay từ prompt; nếu giọng đọc vượt thời lượng cho phép thì tự rút gọn câu hoặc điều chỉnh `atempo` trong ngưỡng tự nhiên (`<= 1.35x`).
  - **Dựng lại nhanh theo Style mới**: Giữ nguyên voice/timeline đã dựng, chỉ áp lại preset phụ đề/nhạc/màu chữ và xuất file mới.
  - **QC Tự động trước duyệt/đăng**: Chạy FFmpeg `blackdetect`, `freezedetect`, `silencedetect`, `ebur128` kèm kiểm tra định dạng (`BR-FMT-01..05`) trước khi đưa sang hàng chờ duyệt hoặc Autopilot.

### 4.2 Trình Quản lý Model Cục bộ & Định tuyến AI (`V2-AI-01..03`)
- Giữ cơ chế **Subscription-First** (`claude -p`, `gemini -p`) + **Xoay vòng nhiều API Keys** cho Gemini, Claude, OpenAI-compat, fal.ai, ElevenLabs kèm giới hạn chi tiêu ngày/tháng.
- **On-Demand Local Models** (lưu tại `VIDEOCREATOR_DATA/models`, chỉ tải khi người dùng kích hoạt trong Cài đặt):
  - **VieNeu-TTS** (nhân bản giọng tiếng Việt offline), **Faster-Whisper** (chép lời + word timestamps), **UVR / MDX-Net ONNX** (tách vocal & giữ BGM/SFX), **OCR + Inpaint** (xóa hardsub), **Rembg** (tách nền nhân vật), và **Lip-sync**.

---

## 5. Hệ sinh thái 9 Trụ cột Studio & Tính năng

1. **Xu hướng & Bóc công thức (`Trends`)**: Giữ nguyên bộ quét 5 nguồn + dán link + phân tích sâu `rea-video`; bổ sung nút chuyển thẳng 1 hoặc N video xu hướng sang **Batch Studio** hoặc **Localize Studio**.
2. **Sản xuất từ Footage Thật (`Brand Studio`)**: Quản lý Sản phẩm, Footage, Kho Shot, gợi ý cắt khung `9:16` thông minh (`focus_x`), sửa lời kèm đồng hồ âm tiết và preview đồng bộ video.
3. **Studio Việt hóa / Reup & Đa ngữ hóa (`Localize Studio`)**:
   - Đủ **3 chế độ**: *Việt hóa Reup có biến đổi chống trùng lặp*, *Hybrid Remix (tráo cảnh cận sản phẩm bằng `shots` thật của Workspace)*, và *Quốc tế hóa ngược (Việt → Anh/Trung/Nhật...)*.
   - Đủ **3 cách xử lý hardsub gốc**: *Che dải mờ / hộp chữ thẩm mỹ*, *Crop khung*, và *OCR phát hiện tọa độ + AI Inpaint xóa chữ*.
4. **Tạo Hàng Loạt & Bán Hàng A/B (`Batch & Product A/B Studio`)**: Từ danh sách prompt, sản phẩm hoặc công thức xu hướng -> sinh hàng loạt video + 1–3 biến thể A/B mỗi mục; chạy lại từ đúng bước lỗi.
5. **Nhân vật Cố định & Tạo Ảnh AI (`Characters & Image Studio`)**: Thư viện nhân vật (ảnh tham chiếu, mô tả ngoại hình, seed, giọng đọc riêng, tách nền Rembg) để giữ đồng nhất diện mạo xuyên suốt mọi cảnh.
6. **Tin tức / Bài viết sang Video & Autopilot (`News & Autopilot`)**: Tóm tắt bài báo/RSS giữ đúng dữ kiện và xuất video kèm gói đăng bài.
7. **Trình dựng Timeline FreeCut (MIT) & Workflow Node (`Editor & Workflow`)**:
   - Nhúng bản build FreeCut (Việt hóa + bridge API đọc/ghi media của Workspace).
   - Bảng vẽ Workflow Node kéo-thả bằng `@xyflow/react` cho phép nối Nhân vật → Cảnh → Giọng → Render và lưu template JSON.
8. **Studio Chuyên biệt (`Novel`, `Podcast`, `Lip-sync`)**: Tiểu thuyết nhiều chương sang Video, Trình tạo Sóng nhạc Podcast (ưu tiên hỗ trợ mở rộng sang `16:9`), và Lip-sync nhép môi AI.
9. **Kênh & Phát hành Đa nền tảng (`Channels & Publishing`)**:
   - **5 nền tảng API chính thức**: `facebook`, `instagram`, `threads`, `tiktok`, **`youtube`** (Shorts/Video dài).
   - **Xuất Gói Đăng Bài `.zip`**: Video MP4 + ảnh bìa có tít + caption từng nền tảng.
   - **3 cấp độ duyệt theo Kênh**: `single` (duyệt từng bài trên Web/Telegram), `bulk` (duyệt cả lô), `autopilot` (tự xếp lịch đăng khi vượt ngưỡng điểm QC).
   - Hỗ trợ đầy đủ 3 khung hình (`9:16`, `16:9`, `1:1`), **tối ưu trọng tâm cho Video ngắn `9:16` ở Đợt 1**.

---

## 6. Bảo mật & Tương thích Kiểm thử
- Giữ nguyên cơ chế bảo vệ CSRF/Origin (`NonLocalhostBasicAuthMiddleware`) trên toàn bộ app, mở ngoại lệ có kiểm soát cho `allowed_origins` của giao diện Next.js cục bộ (`localhost:3000` / `127.0.0.1:3000`) chỉ khi không phải `Sec-Fetch-Site: cross-site`, vẫn từ chối tuyệt đối `cross-site`, `Origin: null` và origin lạ.
- Toàn bộ bài test (`pytest -m local`) chạy trên **SQLite thật, `JobWorker` thật, FFmpeg thật và `TestClient` thật**, không dùng dữ liệu giả lập trong DB/pipeline nội bộ.
