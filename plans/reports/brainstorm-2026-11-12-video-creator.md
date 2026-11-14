# Brainstorm: Video Creator nội bộ (trang sức bạc thủ công)

Ngày: 2026-11-12. Trạng thái: đã có plan tại `plans/261112-video-creator-app/plan.md`. File này là LỊCH SỬ quyết định; nhiều mục đã được thay đổi sau đó (máy chủ là PC thay vì VPS, tích hợp 2 skill qua chế độ Studio, app tự tải video tham khảo, lộ trình 4 đợt). Chỗ nào khác plan thì plan đúng.
Lưu ý: giá, giới hạn API, quy định review nêu dưới đây theo hiểu biết sẵn có, chưa tra lại. Mục "Việc kiểm chứng ngày 1" liệt kê điểm phải xác nhận.

## 1. Bài toán

- Đội nội bộ tự quay video sản phẩm trang sức bạc thủ công.
- Cần 5–10 video/ngày cho social: xây thương hiệu, bán hàng, làm creative quảng cáo.
- Muốn: từ footage gốc → nhiều video khác nhau (remix + cảnh AI) → duyệt → đăng FB, IG, Threads, TikTok → điều khiển và nhận báo cáo qua Telegram.
- Thêm: quét video xu hướng cùng ngành và brand lớn → đề xuất video nên sản xuất.
- Tích hợp rea-video (https://github.com/JuneYaooo/rea-video) để phân tích video.
- Code bằng Claude Code. Mong muốn có bản dùng được sau 1 tuần.

## 2. Quyết định đã chốt

| Hạng mục | Quyết định |
|---|---|
| Kiểu tạo video | Remix trước; generative sau, chỉ cho cảnh phụ |
| Nguồn video | Tự sản xuất, không vướng bản quyền |
| Người dùng | Nội bộ, không bán |
| Sản lượng | 5–10 video/ngày |
| Đăng bài | API chính thức từng nền tảng, không qua dịch vụ trung gian |
| Duyệt | Bắt buộc người duyệt trước khi đăng |
| Lồng tiếng | Chọn theo từng video: không / tiếng Việt / tiếng Anh |
| Hạ tầng | Chấp nhận có VPS |
| Cài đặt | Phải cài sang máy khác thuận tiện |

## 3. Phương án đã cân nhắc

### 3.1 Đóng gói và kiến trúc

| Phương án | Ưu | Nhược |
|---|---|---|
| **A. App Python + cửa sổ native (pywebview) + file cài `.exe`** (chọn) | Một codebase, cùng ngôn ngữ với rea-video; cài bằng 1 file; cùng code chạy headless trên VPS | Bộ cài nặng (Python + FFmpeg); model tách âm tải lần chạy đầu |
| B. Electron/Tauri + Python sidecar | Giao diện đẹp hơn, auto-update sẵn | Hai ngôn ngữ, hai tiến trình, đóng gói phức tạp; không kịp 1 tuần |
| C. Docker Compose | Chuẩn cho VPS | Trên Windows cần Docker Desktop, truy cập file video local rườm rà, khó cho người không kỹ thuật |

Chọn A. Chi tiết:
- Backend FastAPI + SQLite + FFmpeg; UI web render trong cửa sổ pywebview.
- Môi trường Python quản lý bằng `uv`; đóng gói bằng Inno Setup (kèm FFmpeg).
- Cấu hình và token nằm trong 1 thư mục dữ liệu, có nút xuất/nhập để chuyển máy.
- Ràng buộc: Telegram bot và bộ lên lịch chỉ được chạy ở **một** máy (hai máy cùng poll một bot token sẽ xung đột). Máy đó là "máy chủ": VPS hoặc 1 PC bật 24/7. Các máy khác chỉ dựng video, hoặc mở UI của máy chủ qua trình duyệt.

### 3.2 Đăng bài

| Phương án | Ưu | Nhược |
|---|---|---|
| **API chính thức** (chọn theo yêu cầu) | Miễn phí, bền, không phụ thuộc bên thứ ba | Phải đăng ký app developer từng nền tảng; TikTok cần audit |
| Dịch vụ trung gian | Nhanh nhất | Tốn phí, đã loại |
| Browser automation | Không cần review | Vi phạm điều khoản, dễ khoá tài khoản, đã loại |

Hệ quả của API chính thức:
- **Facebook Page, Instagram, Threads:** cần Meta developer app ở chế độ Live; tài khoản IG phải là Business/Creator. App nội bộ, người dùng có vai trò trong app thì nhiều khả năng không cần App Review đầy đủ (phải kiểm chứng).
- **Instagram/Threads:** video thường phải ở URL public → cần bucket lưu trữ (Cloudflare R2/S3) hoặc VPS phục vụ file.
- **TikTok:** app chưa audit chỉ đăng được private. Nộp audit ngay ngày 1. Trong lúc chờ: đẩy video vào hộp nháp TikTok, người dùng bấm đăng trong app.

### 3.3 Quét xu hướng

Không nền tảng nào có API chính thức cho "video đang trend theo ngành". Các nguồn dùng được:

| Nguồn | Chính thức | Lấy được gì |
|---|---|---|
| Instagram Business Discovery | Có | Bài đăng và lượt tương tác của tài khoản Business/Creator khác theo username → theo dõi brand lớn |
| Instagram Hashtag Search | Có | Top bài theo hashtag, giới hạn khoảng 30 hashtag/tuần |
| YouTube Data API | Có | Tìm Shorts theo từ khoá, lượt xem, kênh brand |
| Meta Ad Library API | Có, hạn chế | Quảng cáo thương mại có phân phối ở EU (kèm reach EU, ngày bắt đầu chạy); xem mục 3.3.1 |
| TikTok | Không | Chỉ có qua scraper bên thứ ba (Apify...), tốn phí, vùng xám điều khoản |

Chọn: danh sách brand theo dõi + hashtag/từ khoá, quét bằng IG Business Discovery, YouTube Data API và Meta Ad Library API. TikTok để sau, quyết định khi thấy thiếu.

#### 3.3.1 Meta Ad Library (yêu cầu bổ sung)

- API chính thức (`ads_archive`) chỉ trả quảng cáo thương mại **có phân phối ở EU** (và quảng cáo chính trị toàn cầu). Brand trang sức quốc tế lớn hầu hết chạy ở EU → phủ được. Đối thủ chỉ chạy ở Việt Nam → API không có.
- Cần xác minh danh tính tài khoản developer (giấy tờ tuỳ thân) trước khi được gọi API; có thời gian chờ.
- Không có số liệu chi tiêu hay chuyển đổi của quảng cáo thương mại. Chỉ số thay thế cho "hiệu quả": số ngày đã chạy liên tục, còn đang chạy hay không, số biến thể cùng creative, reach EU.
- API trả link xem quảng cáo (`ad_snapshot_url`), không trả file video. Lấy file để đưa qua rea-video phải tải từ trang snapshot → vùng xám điều khoản, dễ hỏng khi Meta đổi trang.
- Quảng cáo ngoài EU: chỉ có cách scrape trang web Ad Library (tự làm hoặc Apify) → không chính thức, có thể bị chặn. Không làm ở bản đầu.

Cách dùng: quét theo danh sách Page brand + từ khoá → lọc video chạy ≥30 ngày và còn active → xếp hạng theo thời gian chạy và reach → top đưa vào luồng phân tích chung.

Luồng đề xuất: quét định kỳ → xếp hạng theo tương tác → top video đưa qua rea-video lấy cấu trúc (hook, nhịp cắt, thứ tự cảnh) → LLM đối chiếu với kho footage sẵn có → đề xuất "nên làm video X theo công thức Y" → gửi Telegram.

Lưu ý: tải video của người khác chỉ để phân tích nội bộ, không đăng lại. Chỉ học cấu trúc, dựng bằng footage của mình.

### 3.4 rea-video

- Python 3.10+, FFmpeg, CLI, Apache-2.0 → gọi như tiến trình con.
- Hai vai trò: (1) tách shot footage của mình để remix; (2) mổ xẻ video tham khảo ở mục 3.3 — đây là vai trò đúng thiết kế của nó.
- Rủi ro: thiết kế cho agent điều khiển, docs tiếng Trung; chưa xác nhận CLI chạy trọn pipeline không cần agent. Phương án lùi: tách shot bằng PySceneDetect + Gemini mô tả cảnh.

### 3.5 Generative

- Cận cảnh sản phẩm luôn dùng footage thật (AI hay làm sai hoa văn, đá, độ bóng → sai lệch sản phẩm khi bán hàng/quảng cáo).
- AI chỉ sinh cảnh phụ, hoặc tạo chuyển động từ ảnh sản phẩm thật.
- Lớp provider là một interface mỏng.

### 3.5.1 Nhiều lựa chọn model (đã chốt 2026-11-12)

Ba ô chọn model độc lập trong cài đặt:

| Vai trò | Lựa chọn | Ghi chú |
|---|---|---|
| Bộ não | Gemini (đọc thẳng video), Claude (`claude-opus-5-5` / `claude-sonnet-5-5` / `claude-haiku-5-5`), GPT | Claude API chỉ nhận ảnh → app trích khung hình từng shot. Mặc định: Gemini mô tả shot, Claude viết kịch bản + caption. Có từ tuần 1 |
| Sinh video | Veo 3 trực tiếp (mặc định), Sora 2 trực tiếp, và adapter cổng model (fal.ai hoặc Replicate) cho Kling, Runway, Luma, Seedance, Hailuo | Người dùng đã chấp nhận cổng model. Tuần 3 |
| Giọng đọc | Gemini TTS (mặc định), OpenAI TTS, ElevenLabs | Nghe thử tiếng Việt trước khi chốt |

- Hiện chi phí ước tính trước khi sinh video; hạn mức chi phí mỗi ngày.
- Thử chế độ ảnh → video trên ảnh trang sức bạc thật trước khi chọn model mặc định.

### 3.6 video-shotcraft (https://github.com/Vincentwei1021/video-shotcraft)

- Là skill cho Claude Code/Codex: agent tự viết code React (Remotion) để dựng phim quảng cáo motion graphics từ ảnh chụp màn hình sản phẩm phần mềm. Đầu ra 1920×1080 ngang. Không xử lý footage quay thật.
- Không tích hợp nguyên khối vào app, vì:
  - Không có API/CLI "đưa đầu vào → ra video"; phần quyết định là agent viết code mới cho từng video. Nhúng vào app = chạy một coding agent cho mỗi video: chậm, tốn token, kết quả không ổn định ở mức 5–10 video/ngày.
  - Lệch loại nội dung: thiết kế cho giao diện phần mềm, không phải cận cảnh trang sức dọc 9:16.
  - Kéo thêm Node.js + Remotion + Chrome headless vào bộ cài; Remotion cần giấy phép trả phí với công ty trên quy mô nhỏ; nhiều phần chỉ test trên macOS.
  - Phần đăng bài của nó dùng Upload-Post (dịch vụ trung gian, đã loại).
- Phần lấy được:
  - Ý tưởng cắt theo nhịp nhạc và thêm hiệu ứng âm thanh (Freesound) → áp vào bước dựng FFmpeg.
  - Thư viện shot nhóm chữ, chuyển cảnh, outro → làm mẫu cho vài template Remotion cố định (intro logo, phụ đề động, thẻ giá/chất liệu, outro kêu gọi mua), nhận tham số JSON, app gọi `remotion render`. Để tuần 3 trở đi, chỉ khi phụ đề FFmpeg không đủ đẹp.
  - Dùng nguyên bản ngoài app, trong Claude Code, cho video thương hiệu đặc biệt (ra mắt bộ sưu tập).

### 3.6.1 Đính chính và quyết định mới (2026-11-12)

- Đính chính: video-shotcraft dùng được footage mp4 (`assets/lib/ClipCard.tsx` bọc `OffthreadVideo`). Nhận định "không xử lý footage quay thật" ở trên là sai một phần; đúng là: nó thiết kế cho phim ngang về phần mềm, dọc + trang sức là dùng ngoài thiết kế gốc.
- Người dùng quyết định: tích hợp cả rea-video và video-shotcraft vào app, và có chế độ dựng lại video theo prompt dùng 2 skill + footage + video xu hướng.
- Cách làm: chế độ "Studio" chạy agent (Claude Agent SDK) nạp 2 skill, song song với chế độ "Nhanh" (FFmpeg). Chi tiết: plan phase 17; điều kiện: spike S11 ở phase 01.

### 3.7 Google Flow qua CDP (đã loại khỏi phạm vi, 2026-11-12)

- Ý tưởng: điều khiển Chrome thật qua CDP để dùng Google Flow bằng gói thuê bao thay cho Veo API trả theo giây.
- Người dùng quyết định: chưa dùng, bám kế hoạch ban đầu. Không nằm trong plan `261112-video-creator-app`.
- Lý do chính: vi phạm điều khoản Google (rủi ro khoá tài khoản), phụ thuộc chi tiết giao diện dễ đổi, không chạy trên VPS, chỉ text-to-video.
- Nếu xét lại sau: làm thành 1 `VideoGenProvider` thử nghiệm, tắt mặc định, tài khoản Google riêng; thử tay nửa ngày trước khi viết.

### 3.8 MoneyPrinterTurbo và Muse2Tele (2026-11-13)

MoneyPrinterTurbo (https://github.com/harry0703/MoneyPrinterTurbo): MIT, Python 3.11+, REST API + CLI, chạy Windows, nhận tư liệu local, nhiều nhà cung cấp giọng, phụ đề theo TTS hoặc whisper, 9:16/16:9/1:1, chạy lô.
- Tích hợp: chạy như dịch vụ phụ, làm engine lắp ráp cho chế độ Nhanh (lồng tiếng, phụ đề, nhạc, chuyển cảnh, chạy lô, thêm tỉ lệ khung); nguồn stock và AI video của nó dùng cho cảnh phụ không chứa sản phẩm. Plan phase 09, 14; điều kiện: spike S12.
- Không dùng: LLM viết kịch bản của nó (lời phải từ thông tin sản phẩm), stock/AI cho cảnh sản phẩm, crop/đổi tốc độ, nhạc mặc định (không rõ quyền), tính năng đăng bài.

Muse2Tele (https://github.com/vitbau246/Muse2Tele): công cụ quản lý hàng loạt tài khoản muse.ai qua trình duyệt giả lập dấu vân tay (Camoufox, FoxProfile) + proxy nước ngoài, đọc/ghi bằng cách điều khiển giao diện web; AutoPost điều khiển Facebook Business Suite, TikTok, YouTube Studio bằng trình duyệt; tạo hàng loạt Page/kênh. Không thấy giấy phép.
- KHÔNG tích hợp phần lõi: nhiều tài khoản + giả lập trình duyệt + proxy để tránh bị chặn, đăng bài bằng tự động hoá trình duyệt, tạo/đổi thương hiệu Page hàng loạt. Lý do: vượt cơ chế kiểm soát của nền tảng (rủi ro khoá toàn bộ tài khoản thương hiệu), ngược quyết định "chỉ API chính thức" và quyết định loại Google Flow qua CDP, không có giấy phép dùng lại code.
- Lấy Ý TƯỞNG giao diện Telegram, tự viết lại: topic theo mảng, phản ứng trạng thái, tin tiến độ, gộp album, reply theo ngữ cảnh, chấm điểm tự động rồi làm lại có giới hạn, gói chỉ dẫn, tự cập nhật. Plan phase 16, 08.
- Nếu muốn dùng model Muse để viết: thêm như 1 `AIProvider` qua API chính thức của nhà cung cấp (nếu có), không qua tài khoản web.

### 3.9 Ưu tiên gói thuê bao, thêm Muse (2026-11-13)

- Yêu cầu: dùng tối đa Claude Pro, Gemini Pro, Muse; gọi API ít nhất có thể; thêm Muse để tạo video và kịch bản.
- Đường hợp lệ duy nhất để phần mềm dùng gói thuê bao: CLI chính thức của hãng (`claude -p`, `gemini -p`) đăng nhập bằng tài khoản của chủ máy. Không lấy token trình duyệt, không điều khiển giao diện web, không proxy lách vùng, không nhiều tài khoản.
- Muse = dòng model của Meta. Muse Spark (chữ) có API chính thức trả theo token, preview, theo nguồn tra được chỉ mở cho nhà phát triển ở Mỹ. Muse Video chưa có API.
- Thiết kế: bộ định tuyến thử gói thuê bao trước, API là dự phòng tắt được; "trạm việc tay" cho việc tạo video trong app thuê bao (Muse/Meta AI, Gemini, Flow). Plan phase 18; điều kiện: spike S13.
- Giới hạn: hạn mức gói nhỏ nên có lúc phải chờ; điều khoản/tính phí cho dùng lập trình đã đổi trong 2026 và các nguồn mâu thuẫn, phải đọc bản hiện hành; gói thuê bao không bao gồm hạn mức API.

## 4. Giải pháp đề xuất

Luồng chính:

1. Nhập footage → rea-video tách shot, mô tả → lưu kho shot (SQLite).
2. Gemini lập kịch bản remix (chọn shot, thứ tự, lời, caption bài đăng).
3. FFmpeg dựng 9:16: phụ đề, nhạc, lồng tiếng tuỳ chọn (Việt/Anh).
4. Hàng chờ duyệt trong UI; duyệt nhanh qua Telegram.
5. Đăng theo lịch qua API chính thức; lưu kết quả.
6. Telegram bot: `/status`, `/post`, `/report`, nhận đề xuất xu hướng.

Stack: Python 3.11, FastAPI, SQLite, FFmpeg, pywebview, python-telegram-bot, APScheduler, uv, Inno Setup, R2 cho file public.

## 5. Lộ trình

1 tuần không đủ cho toàn bộ. Thứ tự:

| Giai đoạn | Nội dung |
|---|---|
| Tuần 1 | Luồng 1–4, đăng Facebook Page + Instagram, Telegram bot cơ bản, bộ cài `.exe`. Nộp audit TikTok và tạo Meta app ngay ngày 1 |
| Tuần 2 | Threads, TikTok (nháp hoặc public nếu qua audit), lên lịch tự động, quét xu hướng + đề xuất |
| Tuần 3 | Cảnh phụ bằng AI (Veo/Sora), provider thứ hai, báo cáo hiệu quả bài đăng |

## 6. Rủi ro

| Rủi ro | Giảm thiểu |
|---|---|
| TikTok audit chậm hoặc bị từ chối | Dùng chế độ đẩy vào hộp nháp |
| Meta đổi chính sách, token hết hạn | Token dài hạn, cảnh báo hết hạn qua Telegram |
| rea-video không chạy được ngoài agent | Thử nửa ngày đầu; lùi về PySceneDetect + Gemini |
| 5–10 video/ngày na ná nhau → giảm reach | Đa dạng công thức từ mục xu hướng; người duyệt loại bản trùng |
| Chi phí generative | Giới hạn ngân sách/ngày trong app; chỉ cảnh phụ |
| Render nặng trên VPS | VPS chỉ lên lịch, đăng, bot; render ở PC. Nếu render trên VPS cần khoảng 4 vCPU/8GB |

Chi phí ước tính 150–300 video/tháng: remix vài chục USD (Gemini + giọng đọc); generative thêm khoảng $1–3/clip 8 giây.

## 7. Tiêu chí thành công

- Tuần 1: từ 1 footage ra ≥3 bản remix khác nhau, duyệt và đăng thành công lên Page + IG từ app; bot trả lời `/status`.
- Cài trên máy thứ hai bằng 1 file, chạy được trong 15 phút.
- Sau tuần 2: ≥5 video/ngày đăng đúng lịch, không thao tác tay ngoài bước duyệt; mỗi tuần có ≥5 đề xuất video từ xu hướng.

## 8. Việc kiểm chứng ngày 1

1. Meta app chế độ Live, không App Review: bài đăng có public với Page/IG của mình không.
2. Điều kiện và thời gian audit TikTok Content Posting API; chế độ hộp nháp.
3. `docs/cli.md` của rea-video: chạy trọn pipeline bằng CLI, thời gian xử lý 1 video trên máy không GPU.
4. Giá hiện tại Gemini, Veo, Sora, TTS.
5. Instagram Business Discovery có trả `media_url` video của tài khoản khác không.
6. Meta Ad Library API: phạm vi quốc gia hiện tại, các trường reach trả về, quy trình xác minh danh tính, cách lấy file video từ snapshot.

## 9. Việc người dùng cần chuẩn bị

- Xác minh danh tính tài khoản Meta developer để dùng Ad Library API (làm sớm vì có thời gian chờ).
- Tài khoản Meta developer; Page Facebook; IG chuyển sang Business và liên kết Page; tài khoản Threads.
- Tài khoản TikTok developer, website + trang chính sách quyền riêng tư (audit yêu cầu).
- Bot Telegram (BotFather), API key Gemini, key YouTube Data API.
- VPS hoặc PC bật 24/7 làm máy chủ; bucket R2.
- Danh sách brand lớn và hashtag/từ khoá ngành cần theo dõi.
