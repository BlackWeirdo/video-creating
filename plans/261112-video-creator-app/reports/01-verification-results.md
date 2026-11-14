# Giai đoạn 01: kết quả kiểm chứng

Cập nhật: 2026-11-14 (12:24). Trạng thái chung: ĐANG LÀM. Đạt: S1, S7, S9, S13. Đạt một phần: S11, S12. Mới đọc tài liệu: S5, S10. Chưa làm: S2, S3, S4, S6, S8 (mục 4). Xem báo cáo chuyển giao mới nhất: [handoff-2026-11-14-to-claude.md](handoff-2026-11-14-to-claude.md).

Cách đọc cột "Kết luận": **Đạt** = đã chạy thật và thấy kết quả. **Đạt một phần** = có phần đã chạy thật, phần còn lại ghi rõ. **Mới đọc tài liệu** = chưa gọi API thật, số liệu lấy từ trang chính thức, phải xác nhận lại bằng lệnh thật. **Chưa làm** = chưa có gì.

## 1. Bảng kết quả

| Spike | Kết luận | Bằng chứng | Nhánh chọn |
|---|---|---|---|
| S1 rea-video trên Windows | **Đạt** | `decompose` chạy thành công trên 2 clip 1080x1920 60fps 20s: bản đủ stems+OCR mất 237s, bản tách shot `--no-ocr --no-stems` mất 120.7s ([s1_rea_video.md](../../../spikes/s1_rea_video.md)) | **Nhánh A**: `rea-video decompose` trong venv riêng |
| S2 Meta đăng công khai không review | Chưa làm | Tài liệu bên thứ ba nói quyền mức Standard dùng được cho Page của người có vai trò trong app; chưa có nguồn chính thức, chưa đăng thử | Chưa chốt |
| S3 loại và hạn token | Chưa làm | — | Chưa chốt |
| S4 redirect `localhost` | Chưa làm | — | Chưa chốt |
| S5 TikTok hộp nháp + audit | Mới đọc tài liệu | Mục 2.3 | Tạm: hộp nháp bằng `FILE_UPLOAD`; chờ thử thật |
| S6 Ad Library | Chưa làm | Chờ xác minh danh tính | — |
| S7 Gemini model + giá | **Đạt** | `GEMINI_API_KEY` hoạt động thật qua `google-genai` SDK (`client.models.list()`, structured JSON output cho vision/writer/checker). `gemini-3.8-flash` chạm trần free-tier 20 RPD khi describe hàng loạt; đã bổ sung `gemini-3.6-flash` trong `config.toml` | `gemini_api` (`gemini-3.6-flash` / `gemini-3.8-flash`) làm dự phòng tự động khi `claude_cli` hết hạn mức |
| S8 nghe thử giọng Việt | Chưa làm | Cần key và người dùng nghe | — |
| S9 libass + font Việt | **Đạt** | Mục 2.1 | Dùng FFmpeg full build của gyan.dev + file font kèm app |
| S10 lặt vặt | Mới đọc tài liệu | Mục 2.2 | Điền `[platform_limits]` theo mục 2.2, đánh dấu chưa xác nhận |
| S11 hai skill trên Windows | Đạt một phần (2026-11-14) | Remotion dựng video dọc từ footage thật (78 giây cho 8 giây); phiên Studio thật với `claude -p` chạy trọn vòng trong 1 phút 56 giây. `ClipCard` của skill cắt footage thành vuông nên không dùng cho hình sản phẩm. Chưa làm: phân tích video xu hướng, người dùng chấm chất lượng, giấy phép Remotion. Chi tiết: [17-studio-spike.md](17-studio-spike.md) | Studio làm đầy đủ, dùng thành phần toàn khung của app thay `ClipCard` |
| S12 MoneyPrinterTurbo | Đạt một phần (2026-11-14) | Chạy thật `v1.3.9`: giữ thứ tự, không crop, giọng Việt và phụ đề đúng; nhưng ép độ dài video theo giọng đọc (cắt cụt hoặc lặp footage). Chi tiết: [09-mpt-integration.md](09-mpt-integration.md) | **Phương án lùi**: chỉ dùng MPT cho giọng đọc + mốc phụ đề, FFmpeg của app lắp ráp |
| S13 đường gói thuê bao | **Đạt (chốt Hướng A)** | Mục 2.4 | **Hướng A (đã chốt 2026-11-13)**: `claude_cli` đứng đầu cho `vision`, `writer`, `checker`, `studio`; `gemini_api`/`claude_api` dự phòng; bỏ `gemini_cli`; `agy_cli` tắt mặc định |

## 2. Chi tiết

### 2.1 S9: FFmpeg, libass, font tiếng Việt (đạt)

- FFmpeg 9.0.2 full build (gyan.dev, cài bằng winget `Gyan.FFmpeg`), có `--enable-libass --enable-libx264 --enable-libfreetype --enable-libharfbuzz`.
- Font Be Vietnam Pro (Regular, SemiBold, Bold; giấy phép OFL) tải từ repo `google/fonts`, nạp bằng `fontsdir`, không cần cài vào Windows.
- Lệnh: [spikes/s9_ass_burn.cmd](../../../spikes/s9_ass_burn.cmd) với [spikes/s9_test.ass](../../../spikes/s9_test.ass). Ra MP4 1080x1920; ba khung hình trích ra hiện đúng "Nhẫn bạc 925 chế tác thủ công" và chuỗi thử "ngỗng, nghiêng, khuỷu, đượm, ỡ ẵ ỹ ặ ử", dấu chồng không vỡ, tự xuống dòng.
- Ghi chú cho phase 05: đường dẫn repo có dấu cách và dấu hai chấm của ổ đĩa, nên bộ lọc `subtitles` chỉ nhận đường dẫn tương đối một cách an toàn. Chạy ffmpeg với thư mục làm việc là thư mục chứa file `.ass` và font.

### 2.2 S10: giới hạn nền tảng (mới đọc tài liệu chính thức, chưa gọi thật)

| Mục | Giá trị | Nguồn |
|---|---|---|
| Instagram: số bài qua API | 100 bài trong 24 giờ trượt; carousel tính 1 | Meta, Content Publishing |
| Instagram: `video_url` | File phải nằm trên máy chủ truy cập công khai lúc gọi | như trên |
| Instagram: trạng thái container | `GET /<container>?fields=status_code`: `IN_PROGRESS`, `FINISHED`, `PUBLISHED`, `ERROR`, `EXPIRED`; hỏi 1 lần/phút, tối đa 5 phút; container hết hạn sau 24 giờ | như trên |
| Instagram: spec Reels, giới hạn caption | Trang chính thức đã đọc KHÔNG ghi; các nguồn ngoài mâu thuẫn nhau (90 giây hay 15 phút; 100 MB, 300 MB hay 1 GB) | Chưa có số tin được |
| Facebook Page: endpoint | `POST /{page-id}/video_reels` (`upload_phase=start`) → `POST rupload.facebook.com/video-upload/{video-id}` (file nhị phân, hoặc header `file_url`) → `upload_phase=finish`, `video_state=PUBLISHED` | Meta, Reels Publishing API |
| Facebook Page: `file_url` | http/https, máy chủ phải cho user agent `facebookexternalhit/1.1` | như trên |
| Facebook Reels: spec | MP4; 9:16; 1080x1920 (tối thiểu 540x960); 24–60 fps cố định, quét liên tục; 3–90 giây; H.264/H.265; 4:2:0; GOP đóng 2–5 giây; AAC-LC 48 kHz stereo từ 128 kbps. Không ghi dung lượng tối đa | như trên |
| Facebook Reels: số bài | 30 bài qua API mỗi Page trong 24 giờ trượt | như trên |
| Facebook: quyền | `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`; token Page của người có quyền `CREATE_CONTENT` | như trên |
| YouTube: quota | `search.list` có xô riêng: 100 lượt gọi/ngày (mỗi lượt 1 đơn vị); `videos.insert` 100 lượt/ngày; mọi endpoint khác chung 10.000 đơn vị/ngày; `videos.list`, `channels.list`, `playlistItems.list` 1 đơn vị | Google, quota cost |

Hệ quả:
- `BR-FMT-01` (bản master) khớp spec Facebook Reels, không cần sửa. Giới hạn tạm 5–90 giây của `BR-FMT-03` đúng với Facebook.
- Phase 12: YouTube chỉ có 100 lượt `search.list` mỗi ngày (khác giả định "100 đơn vị mỗi lượt"). Lấy video của kênh trong danh sách theo dõi bằng `playlistItems.list`, để dành `search.list` cho từ khoá.
- Phase 07: giới hạn 30 bài/Page/ngày và 100 bài/IG/ngày lớn hơn nhiều so với 5–10 video/ngày.
- Còn thiếu: spec Reels và giới hạn caption chính thức của Instagram, Threads, TikTok (phase 11 đọc tiếp).

### 2.3 S5: TikTok (mới đọc tài liệu chính thức, chưa gọi thật)

- Hộp nháp: `POST /v2/post/publish/inbox/video/init/`, scope `video.upload`. Nguồn `FILE_UPLOAD` (gửi file bằng PUT theo chunk, URL tải lên sống 1 giờ) hoặc `PULL_FROM_URL`.
- `PULL_FROM_URL` đòi tên miền của URL đã được xác minh quyền sở hữu (`url_ownership_unverified`). Vì vậy dùng `FILE_UPLOAD`, không đi qua R2 cho TikTok.
- Giới hạn: 6 yêu cầu/phút mỗi token; tối đa 5 video chờ trong hộp nháp mỗi 24 giờ mỗi tài khoản (`spam_risk_too_many_pending_share`). Với 5–10 video/ngày, mỗi tài khoản TikTok nhận tối đa 5 video/ngày qua đường này.
- App chưa audit (đăng trực tiếp): tối đa 5 người dùng đăng trong 24 giờ, chỉ `SELF_ONLY`, tài khoản phải đang để riêng tư lúc đăng. Trang hướng dẫn chỉ nói về đăng trực tiếp; KHÔNG nói các hạn chế này có áp cho hộp nháp hay không. Phải thử thật.
- Audit: đòi giao diện hiện tên người tạo, cho người dùng tự chọn quyền riêng tư và tương tác, khai báo nội dung thương mại, xem trước, đồng ý rõ ràng, hỏi trạng thái. Có câu "API client không được chỉ là ứng dụng thử và phải hướng tới đông người dùng": một app nội bộ có thể KHÔNG qua audit. Nếu vậy TikTok ở chế độ hộp nháp lâu dài, đúng như rủi ro đã ghi trong đặc tả mục 16.
- Chưa biết: thời gian audit, có cần video demo không.

### 2.4 S13: đường gói thuê bao

**`claude -p` cho vai trò viết: đạt.** Lệnh: [spikes/s13_claude_cli.py](../../../spikes/s13_claude_cli.py) `writer`. Claude Code 2.1.199, đăng nhập bằng gói thuê bao.
- Một lượt viết kịch bản 5 shot + caption: 22,7 giây, mã thoát 0, `structured_output` khớp lược đồ, chỉ dùng `shot_id` được cấp, tổng 20 giây, không bịa thông số sản phẩm khi prompt nói không có dữ liệu.
- Đầu ra JSON có sẵn các trường app cần: `is_error`, `api_error_status`, `structured_output`, `usage`, `total_cost_usd` (ước tính phía máy khách: 0,086 USD cho lượt này nếu tính theo giá API), `permission_denials`, `session_id`.
- Phát hiện cho phase 18:
  1. Trên Windows phải gọi thẳng `...\npm\node_modules\@anthropic-ai\claude-code\bin\claude.exe` với đối số dạng danh sách. Gọi qua `claude.cmd`/`claude.ps1` làm hỏng dấu nháy trong `--json-schema` (lỗi "`--json-schema is not valid JSON`").
  2. Chạy trong thư mục tạm rỗng, nếu không nó nạp `CLAUDE.md`, hook và `.mcp.json` của thư mục hiện tại.
  3. Cờ `--bare` KHÔNG dùng đăng nhập gói thuê bao (đòi API key), và tài liệu ghi `--bare` "sẽ thành mặc định cho `-p` trong một bản sau". Phải ghim phiên bản Claude Code và kiểm tra lại mỗi lần nâng cấp.
  4. Mỗi lượt gọi kéo theo khoảng 29 nghìn token ngữ cảnh hệ thống (phần lớn đọc từ cache), và một model nhỏ chạy kèm. Nên tính hạn mức theo số lượt, không theo độ dài prompt.
- **`claude -p` cho vai trò `vision` (đọc ảnh thu nhỏ): đạt.** Chạy `python spikes/s13_claude_cli.py vision` trên 3 ảnh thu nhỏ trích từ `clip1.mp4` (`shot_1.jpg`, `shot_2.jpg`, `shot_3.jpg`) với `--allowedTools Read`: hoàn tất trong 24,2 giây, mã thoát 0, `is_error: False`, trả về `structured_output` khớp lược đồ (mô tả tiếng Việt đúng thực tế hình ảnh chế tác nhẫn bạc, gắn 5 thẻ mỗi ảnh, phân biệt đúng cảnh có/không có sản phẩm, chấm chất lượng 3–4/5).

**Điều khoản Anthropic (trang trợ giúp hiện hành, ghi chú mới nhất 07/10/2026):** khi đăng nhập bằng gói, `claude -p` và Agent SDK "vẫn tính vào hạn mức gói thuê bao"; thay đổi đã công bố cho tháng 6/2026 (tách phần này sang tín dụng riêng) đang TẠM HOÃN, chưa huỷ. Trang không nói gì về chạy tự động không người trông. Kết luận: dùng được hôm nay; có rủi ro chính sách đổi lại, đã có phương án lùi là API (đặc tả mục 16).

**`gemini -p` bằng gói Google AI Pro: KHÔNG đạt.** Thông báo chính thức trên GitHub của Gemini CLI (discussion #28017) và trang quota của Gemini CLI (cập nhật 18/06/2026): từ 18/06/2026 Gemini CLI ngừng phục vụ tài khoản cá nhân, gồm Google AI Pro, Ultra và bậc miễn phí. Chỉ còn chạy với API key trả tiền hoặc giấy phép doanh nghiệp. Google chuyển người dùng cá nhân sang Antigravity CLI (lệnh `agy`), được nói là chưa đủ tính năng như Gemini CLI. Chưa kiểm tra: `agy` có chế độ không tương tác không, có đọc video không, điều khoản có cho chạy tự động không.

**Antigravity CLI (`agy -p`), thử theo lựa chọn B của người dùng: chạy được về kỹ thuật, điều khoản CHƯA rõ.** Lệnh: [spikes/s13_agy_cli.py](../../../spikes/s13_agy_cli.py) `writer`.
- Cài bằng script chính thức `https://antigravity.google/cli/install.ps1` (đã đọc trước khi chạy: tải file nhị phân, đối chiếu SHA-512, đặt vào `%LOCALAPPDATA%\agy\bin`, thêm PATH). `agy.exe` 1.5.8, chữ ký số hợp lệ của Google LLC.
- Có chế độ không tương tác: `-p=<prompt>` (prompt phải gắn liền với cờ, không đọc từ stdin), `--output-format json`, `--json-schema`, `--sandbox`, `--print-timeout`, `--model`.
- Một lượt viết kịch bản cùng prompt và lược đồ với Claude, model `gemini-3.8-flash-medium`: 45,7 giây, mã thoát 0, `status: SUCCESS`, `structured_output` khớp lược đồ, tiếng Việt đúng dấu, không bịa thông số. Dùng 13,7 nghìn token (4,8 nghìn là suy nghĩ). Chậm gấp đôi `claude -p` (22,7 giây).
- `agy models` liệt kê Gemini 4 Argon/Hydrogen, Gemini 3.8 Flash, và cả Claude Opus/Sonnet 5.5.
- Máy này đã ở trạng thái đăng nhập sẵn; CHƯA xác nhận đó là tài khoản nào và có phải gói Google AI Pro không (người dùng kiểm tra bằng `/usage` trong `agy`).
- Chưa làm: đọc file video (chờ footage; script có chế độ `video`); nguyên văn thông báo hết hạn mức. Người dùng trên diễn đàn Google báo gói Pro bị khoá "Individual quota reached" sau rất ít lượt; hạn mức hồi mỗi 5 giờ, có trần tuần (nguồn diễn đàn, chưa tự kiểm).
- **Điều khoản (Google Antigravity Additional Terms of Service, mục 6):** cấm "dùng phần mềm, công cụ hay dịch vụ của bên thứ ba để truy cập Dịch vụ" (ví dụ nêu: OpenClaw dùng OAuth của Antigravity), nói Dịch vụ không được dùng "kèm với sản phẩm không do chúng tôi cung cấp", và có thể đình chỉ tài khoản. Văn bản không nói một chương trình tự viết gọi file `agy.exe` nguyên bản có bị tính là "phần mềm bên thứ ba" hay không. Trên diễn đàn Google có hai câu trả lời trái nhau (một nói chạy `agy -p` cục bộ cho cá nhân là được, một nói để công cụ khác điều khiển `agy` bằng đăng nhập cá nhân có thể bị xử lý); không câu nào là phát ngôn chính thức. Kết luận: KHÔNG xác nhận được là được phép.

**Meta Model API (Muse Spark):** chưa thử, cần tài khoản người dùng.

## 3. Quyết định cần người dùng chốt

**Vai trò `vision` khi không còn `gemini -p` bằng gói thuê bao.** Đặc tả mục 8.1 đang xếp `gemini_cli` đứng đầu cho `vision` và `checker`. Ba hướng:

| Hướng | Nội dung | Được | Mất |
|---|---|---|---|
| A (khuyến nghị) | `vision` và `checker`: `claude_cli` trước, `gemini_api` dự phòng. Bỏ `gemini_cli` | Chắc chắn chạy; một CLI duy nhất phải bảo trì; vẫn đạt mục tiêu 90% lượt qua gói thuê bao | Claude chỉ xem ảnh thu nhỏ, không xem video chuyển động (`FR-AI-07`); mọi việc dồn vào một gói Claude nên dễ chạm hạn mức hơn |
| B | Thử Antigravity CLI trong S13; đạt thì thay `gemini_cli` bằng `agy_cli` | Giữ được hai gói thuê bao chia tải; có thể xem video | Thêm 1–2 giờ kiểm chứng, công cụ còn mới, có thể không có chế độ không tương tác |
| C | `vision` dùng thẳng `gemini_api` (trả tiền, trong hạn mức 5 USD/ngày) | Xem video trực tiếp, chất lượng mô tả shot tốt nhất | Trả tiền theo lượt; không còn "ưu tiên gói thuê bao" cho vai trò này |

Người dùng chọn B ngày 2026-11-13. Kết quả thử (mục 2.4): `agy -p` chạy được và trả JSON đúng lược đồ, nhưng điều khoản mục 6 của Antigravity không cho phép rõ ràng việc một app tự viết gọi nó, và có nêu khả năng đình chỉ tài khoản Google. Vì vậy B chưa đạt tiêu chí "điều khoản cho phép" của S13.

Khuyến nghị sau khi thử: lấy hướng A làm mặc định (`claude_cli` trước, `gemini_api` dự phòng). Thêm `agy_cli` như một nhà cung cấp TẮT mặc định, chỉ bật khi người dùng tự chấp nhận rủi ro điều khoản, và chỉ sau khi thử đọc video đạt.

**Cập nhật 2026-11-13:** Người dùng đã xác nhận chọn **Hướng A**. Đã cập nhật mục 8.1 của đặc tả, phase 18 và `config.py`.

## 4. Việc đang chờ người dùng

Đã hoàn tất & kiểm chứng thực tế ngày 2026-11-14:
1. 9 file footage trang sức bạc S925 thật tải từ Google Drive (`PROCESS`) -> nhập kho `footage #1..#9` (120 shots).
2. `YOUTUBE_API_KEY`, `GEMINI_API_KEY`, và Telegram bot `@VideoCreatorSocialBot` (nhóm `VideoCreator_SS` với 6 topic) đã cài vào `secrets.bin` / `spikes/.env` và chạy thật.

Còn chờ cho S2–S6, S8:
1. App Meta + Page thử + IG thử + Cloudflare R2 bucket/domain công khai (S2, S3, S4).
2. TikTok developer app + redirect URI HTTPS/localhost (S4, S5).
3. Xác minh danh tính Meta cho Ad Library API (S6).
4. Nghe thử giọng đọc tiếng Việt (S8) và 1–2 file nhạc nền nếu muốn bật lồng tiếng/nhạc bản quyền riêng.

## 5. Ghi chú môi trường máy chủ

- Máy đang dùng: i7-9750H, **8 GB RAM** (đặc tả khuyến nghị 16 GB), ổ C còn 77 GB (khuyến nghị 100 GB). Sẽ đo RAM khi chạy S1, S11, S12 trước khi kết luận máy này làm máy chủ được.
- Đã cài trong phiên này: uv 0.13.8 (winget), Python 3.11.18 (uv). Antigravity CLI 1.5.8 (script chính thức). Có sẵn: Git, Node.js 24.22.1, FFmpeg 9.0.2 full, Claude Code 2.1.199. Chưa có: yt-dlp.
- `git` chưa có `user.name`/`user.email`; cần đặt trước lần commit đầu.

## 6. Nguồn đã đọc

- Meta, Content Publishing: https://developers.facebook.com/documentation/instagram-platform/content-publishing
- Meta, Reels Publishing API: https://developers.facebook.com/documentation/video-api/guides/reels-publishing
- TikTok, Upload video (inbox): https://developers.tiktok.com/doc/content-posting-api-reference-upload-video
- TikTok, Content Sharing Guidelines: https://developers.tiktok.com/doc/content-sharing-guidelines
- Google, YouTube quota cost: https://developers.google.com/youtube/v3/determine_quota_cost
- Gemini CLI, thông báo ngừng phục vụ tài khoản cá nhân: https://github.com/google-gemini/gemini-cli/discussions/28017
- Gemini CLI, quota: https://geminicli.com/docs/resources/quota-and-pricing/
- Anthropic, Agent SDK với gói Claude: https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan
- Claude Code, chạy không tương tác: https://code.claude.com/docs/en/headless
- Google Antigravity Additional Terms of Service: https://antigravity.google/terms
- Diễn đàn Google AI (không chính thức), dùng `agy` tự động với gói cá nhân: https://discuss.ai.google.dev/t/is-google-ai-pro-antigravity-cli-automation-with-codex-permitted/187241 và https://discuss.ai.google.dev/t/is-invoking-the-official-agy-cli-from-a-local-ai-coding-assistant-allowed-on-an-individual-google-ai-account/185992
