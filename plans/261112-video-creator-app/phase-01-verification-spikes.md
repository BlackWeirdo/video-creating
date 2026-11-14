# Phase 01: Kiểm chứng + đăng ký tài khoản

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: không
- Docs: [research 01](research/researcher-01-social-and-trend-apis.md), [research 02](research/researcher-02-video-pipeline-and-packaging.md), [brainstorm mục 8, 9](../reports/brainstorm-2026-11-12-video-creator.md)

## Overview

- Ngày: 2026-11-12
- Mô tả: time-box 2 ngày (1 ngày cho S1–S10, 3 giờ cho S11, 2 giờ cho S12, phần còn lại là đệm chờ tài khoản). Xác nhận các điểm "chưa xác nhận" bằng lệnh/API thật, chốt phương án lùi. Người dùng khởi động các đăng ký có thời gian chờ.
- Ưu tiên: P0 (chặn mọi phase sau)
- Trạng thái triển khai: đang làm (phiên 1 ngày 2026-11-13; xem [kết quả](reports/01-verification-results.md))
- Trạng thái review: chưa review

## Key Insights

- Research để ngỏ gần hết phần Meta, TikTok, Ad Library, giá Gemini, TTS. Viết code trước khi kiểm chứng = rủi ro làm lại.
- Luật time-box: spike nào hết giờ mà chưa đạt -> lấy phương án lùi, không kéo dài.
- Code spike là đồ bỏ (thư mục `spikes/`), không tái dùng làm code sản phẩm.
- Nhiều spike cần tài khoản người dùng -> người dùng phải ngồi cùng phiên này.

## Requirements

Người dùng làm NGAY đầu ngày (có thời gian chờ):

| Việc | Ghi chú |
|---|---|
| Tài khoản Meta developer + tạo app (loại Business) | Thêm bản thân làm admin app |
| Xác minh danh tính Meta (cho Ad Library API) | Chờ vài ngày (chưa xác nhận) |
| Business verification Meta | Chỉ cần nếu S2 kết luận phải App Review; bắt đầu luôn cho chắc |
| IG chuyển Business, liên kết Page; tạo Page thử + IG thử | Dùng cho test live |
| Tài khoản Threads | Thêm làm tester trong app |
| TikTok developer app + website + trang privacy/terms | Audit yêu cầu; nộp sớm nhất có thể (xem S5) |
| Telegram bot (BotFather); tạo nhóm duyệt, thêm bot; lấy chat ID nhóm + user ID của 2–5 người duyệt | |
| Liệt kê 2–3 tài khoản mỗi nền tảng sẽ đăng (Page, IG Business, Threads, TikTok) và ngôn ngữ của từng tài khoản | Mỗi tài khoản IG phải liên kết 1 Page; mỗi tài khoản TikTok phải uỷ quyền riêng |
| Google Cloud project + YouTube Data API key | |
| Cài Claude Code và Gemini CLI trên máy chủ, đăng nhập bằng tài khoản thuê bao (Claude Pro/Max, Google AI Pro) của chủ máy | Đường chính cho AI chữ và nhìn ảnh (phase 18); mỗi gói là của 1 người, không chia sẻ đăng nhập |
| Anthropic API key và Gemini API key có billing, đặt hạn mức thấp | Chỉ làm dự phòng khi gói thuê bao hết hạn mức; có thể bỏ nếu chấp nhận chờ |
| Cài Node.js LTS trên máy chủ | Chỉ cần cho S11 và phase 17 (Remotion) |
| Thông tin 5–10 sản phẩm đầu tiên (tên, chất liệu, đá, kích thước, kỹ thuật, giá nếu công bố) | Nhập vào app ở phase 03; là nguồn sự thật cho lời và caption |
| Vài file nhạc nền + SFX đã có quyền dùng cho quảng cáo | Người dùng tự nạp (đã chốt) |
| Danh sách brand lớn, kênh YouTube, hashtag/từ khoá ngành cần theo dõi | Dùng ở phase 12 |
| Cloudflare R2 bucket + public domain (r2.dev hoặc custom) + API token | |
| 2–3 clip footage thật (30–60 giây) + 2–3 clip ngắn 5–10 giây | Clip ngắn dùng làm `tests/samples/` |

Spike (mỗi cái có tiêu chí đạt + phương án lùi):

| ID | Kiểm chứng | Time-box | Đạt khi | Phương án lùi |
|---|---|---|---|---|
| S1 | rea-video trên Windows, footage thật | 2 giờ | `rea-video decompose` chạy xong 2 clip, không cần agent, < 5 phút/clip CPU, `breakdown.json` có mốc shot dùng được | PySceneDetect tách shot + Gemini mô tả keyframe |
| S2 | Meta app Live mode, không App Review | 2 giờ | Video đăng bằng API lên Page thử và IG thử, xem được từ tài khoản KHÔNG có vai trò trong app | Nộp App Review; trong lúc chờ app xuất gói "video + caption" để đăng tay |
| S3 | Loại token + thời hạn | gộp S2 | `debug_token` cho thấy token Page/IG không hết hạn (System User) hoặc >= 60 ngày | Token 60 ngày + cảnh báo Telegram trước 7 ngày + đăng nhập lại |
| S4 | Redirect `http://localhost` cho OAuth Meta, Threads, TikTok | 1 giờ | Portal nhận URI và luồng trả `code` về app | Trang callback tĩnh HTTPS (Cloudflare Pages) hiện `code`, người dùng dán vào app |
| S5 | TikTok: điều kiện audit, inbox mode | 1 giờ | Biết hồ sơ audit cần gì; `/v2/post/publish/inbox/video/init/` với scope `video.upload` đưa video vào hộp nháp tài khoản thử | Direct Post `SELF_ONLY`, người dùng đổi công khai trong app; nếu cũng hỏng: gói đăng tay |
| S6 | Ad Library API | 1 giờ (sau khi xác minh xong) | `ads_archive` theo Page ID trả ad có `ad_delivery_start_time`, `ad_snapshot_url`, reach EU; biết có lấy được file video chính thức không | Chỉ metadata + link cho người xem; nếu không có quyền truy cập kịp: bỏ Ad Library khỏi tuần 2 |
| S7 | Gemini model ID + giá | 1 giờ | `client.models.list()` -> chọn 1 model flash hiểu video; chạy 1 clip 30 giây, ghi `usage_metadata`, tính ra USD/phút footage; structured output chạy | Gửi keyframe ảnh thay video; model rẻ hơn |
| S8 | Nghe thử TTS tiếng Việt | 1 giờ | Người dùng nghe 3 đoạn lời thật (Gemini TTS, OpenAI `gpt-4o-mini-tts`), chấp nhận >= 1 giọng; đọc điều khoản dùng thương mại | ElevenLabs; nếu không giọng nào đạt: tuần 1 không lồng tiếng Việt, chỉ phụ đề |
| S9 | FFmpeg build có libass + font Việt | 30 phút | Burn ASS có dấu tiếng Việt (Be Vietnam Pro) ra đúng chữ | Build khác (BtbN/gyan full) |
| S11 | 2 skill chạy thật trên Windows (điều kiện vào [phase 17](phase-17-studio-agent-two-skills.md)) | 3 giờ | Trong Claude Code, với 1 footage trang sức thật + 1 video xu hướng thật: skill `rea-video` phân tích xong có `VIDEO.md`; skill `video-shotcraft` dựng ra 1 mp4 DỌC 1080x1920 dùng footage thật qua `ClipCard`; ghi lại thời gian, chi phí token, lỗi trên Windows, và người dùng chấm chất lượng. Kiểm tra điều kiện giấy phép Remotion cho công ty | Không đạt phần dựng: phase 17 thu hẹp còn phân tích + kịch bản bằng agent, dựng bằng FFmpeg (phase 05) và chỉ mượn phụ đề/nhịp/SFX. Không đạt cả hai: bỏ phase 17, giữ rea-video CLI như phase 03 |
| S12 | MoneyPrinterTurbo làm engine lắp ráp (điều kiện của [phase 09](phase-09-beat-sync-sfx-voiceover.md)) | 2 giờ | Cài 1 bản ghim trên Windows, chạy API (`/docs`). Dựng 1 video 9:16 từ 3 đoạn local đã cắt sẵn, theo đúng thứ tự, lời tự cấp (không dùng LLM của MPT), giọng tiếng Việt, phụ đề, nhạc người dùng nạp. Đạt khi: thứ tự và độ dài từng đoạn được giữ, không crop, không đổi tốc độ, không lấy stock; ghi lại endpoint, thời gian dựng trên CPU, nhà cung cấp nào có giọng Việt | Chỉ dùng phần TTS + mốc phụ đề của MPT; nếu cũng không tách được: phase 09 tự viết TTS + trộn âm thanh như thiết kế cũ |
| S13 | Đường gói thuê bao (điều kiện của [phase 18](phase-18-subscription-first-routing.md)) | 2 giờ | Trên máy chủ, đăng nhập bằng tài khoản thuê bao của chủ máy: `claude -p` trả JSON hợp lệ cho 1 prompt viết kịch bản và mô tả đúng 3 ảnh thumbnail; `gemini -p` trả JSON và thử đọc 1 file video ngắn; ghi nguyên văn thông báo khi hết hạn mức (nếu gặp), thời gian mỗi lượt. Đọc điều khoản/trang trợ giúp HIỆN HÀNH của Anthropic và Google về dùng gói thuê bao với CLI không tương tác, ghi kết luận. Thử đăng ký Meta Model API (Muse Spark) bằng tài khoản thật, không dùng proxy | CLI nào không đạt hoặc điều khoản không cho: vai trò đó dùng API có trần tiền. Meta Model API không mở: Muse chỉ ở trạm việc tay |
| S10 | Lặt vặt | 1 giờ | Biết: giá quota `search.list` YouTube; endpoint video FB Page (`/videos` với `file_url` hay `/video_reels`); IG tải được `video_url` từ R2; giới hạn IG 50 hay 100/24h; spec video FB/IG (thời lượng, dung lượng, codec) và giới hạn ký tự caption/hashtag để điền `[platform_limits]` (phase 05) | Giả định xấu nhất (100 units/search; 50 bài/24h; MP4 H.264 AAC 1080x1920 30fps) |

## Architecture

Không có kiến trúc sản phẩm. Mỗi spike = 1 script độc lập trong `spikes/`, đọc key từ `spikes/.env` (không commit). Kết quả ghi vào 1 file báo cáo; các phase sau đọc file đó để chọn nhánh.

## Related code files

Tạo (đường dẫn từ gốc repo):
- `spikes/s1_rea_video.md` (lệnh đã chạy + thời gian), `spikes/s2_meta_post.py`, `spikes/s4_oauth_redirect.md`, `spikes/s5_tiktok_inbox.py`, `spikes/s6_ad_library.py`, `spikes/s7_gemini_video.py`, `spikes/s8_tts.py`, `spikes/s9_ass_burn.cmd`
- `spikes/.env` (gitignore), `.gitignore`
- `plans/261112-video-creator-app/reports/01-verification-results.md` (bảng: spike, đạt/không, bằng chứng, nhánh chọn)

## Implementation Steps

1. `git init`, `.gitignore` (`.env`, `spikes/.env`, `*.mp4`, `.venv`, data dir). Cài `uv`, Python 3.11, FFmpeg.
2. Người dùng bắt đầu toàn bộ bảng đăng ký ở trên (song song với bước 3–4).
3. S1: cài rea-video vào venv riêng (`uv venv spikes/.venv-rea`, `pip install -e ".[ocr]"`), chạy `decompose --no-packaging` trên 2 clip; ghi lỗi Windows, thời gian, cấu trúc `breakdown.json`. Thử `--vlm` với endpoint Gemini OpenAI-compat (không bắt buộc đạt).
4. S9, S7, S8: không phụ thuộc tài khoản social, làm trong lúc chờ Meta.
5. S2 + S3: lấy token (thử System User token trong Business Settings trước, rồi user token dài hạn), đăng 1 video lên Page thử và 1 Reel lên IG thử qua R2 URL, kiểm tra hiển thị công khai, chạy `debug_token`.
6. S4: thử đăng ký `http://localhost:<port>/oauth/callback` ở 3 portal.
7. S5: đọc trang audit + trang upload của TikTok; thử inbox upload.
8. S10: đọc docs, chạy 1 call `search.list` rồi xem quota trong Google Cloud Console.
9. S6: chạy khi xác minh danh tính xong (có thể sau ngày 1; không chặn tuần 1).
10. S11: trong Claude Code (2 skill đã cài ở `~/.claude/skills/`), yêu cầu phân tích 1 video xu hướng bằng `rea-video`, rồi dựng 1 video dọc từ footage thật bằng `video-shotcraft` theo cấu trúc đó. Ghi thời gian, chi phí, lỗi, điểm chất lượng của người dùng vào báo cáo. Không chặn tuần 1; kết quả quyết định phạm vi phase 17.
10b. S12: cài MoneyPrinterTurbo bản ghim vào `spikes/mpt/` (venv riêng), chạy API, dựng video thử theo tiêu chí; S8 (nghe thử giọng Việt) làm chung bằng các nhà cung cấp giọng của MPT.
11. Viết `01-verification-results.md`; cập nhật các phase bị ảnh hưởng (03, 04, 05, 07, 09, 11, 12, 13, 17) nếu nhánh lùi được chọn.

## Todo list

- [ ] Người dùng: bắt đầu mọi đăng ký trong bảng
- [x] S1 rea-video Windows (đạt, nhánh A)
- [ ] S2 Meta Live mode đăng công khai
- [ ] S3 thời hạn token
- [ ] S4 redirect localhost
- [ ] S5 TikTok audit + inbox
- [ ] S6 Ad Library (có thể trễ)
- [ ] S7 Gemini model + giá
- [ ] S8 nghe thử TTS
- [x] S9 libass + font Việt (đạt, 2026-11-13)
- [ ] S10 lặt vặt
- [ ] S11 (đạt một phần 2026-11-14: dựng Remotion + phiên agent thật chạy được; còn phân tích video xu hướng, người dùng chấm, giấy phép Remotion)
- [x] S12 MoneyPrinterTurbo (đạt một phần 2026-11-14: không giữ độ dài; lấy phương án lùi chỉ dùng giọng đọc + mốc phụ đề)
- [x] S13 đường gói thuê bao (chốt hướng A: `claude_cli`; `gemini -p` không còn dùng được; Meta Model API chưa thử)
- [ ] Viết báo cáo kết quả, cập nhật phase liên quan

## Success Criteria

- Mỗi spike có kết luận "đạt" hoặc "lùi sang X" kèm bằng chứng (output lệnh, link bài đăng thử, số token). Không còn ô "chưa biết" cho S1, S2, S3, S7, S9.
- Mọi đăng ký đã nộp; biết thời gian chờ dự kiến của từng cái.

## Risk Assessment

- S2 hỏng = rủi ro lớn nhất của cả plan: không đăng công khai được qua API cho tới khi App Review xong (có thể vài tuần). Giảm thiểu: nộp review ngay, tuần 1 dùng gói đăng tay.
- Xác minh danh tính/business có thể dài hơn 1 tuần -> S6 trễ, phase 12 làm Ad Library sau cùng.
- Người dùng không có mặt -> cả ngày bị chặn. Cần hẹn trước.

## Security Considerations

- Key/token chỉ nằm trong `spikes/.env`, đã gitignore. Không dán token vào file báo cáo.
- Bài đăng thử chỉ lên Page/IG thử, xoá sau khi kiểm tra.
- Xoá hoặc thu hồi token spike sau khi có luồng lưu secrets ở phase 02.

## Next steps

- Phase 02 bắt đầu được ngay sau S1, S7, S9 (không cần chờ Meta).
- Kết quả S2–S5 quyết định thiết kế xác thực ở phase 07 và 11.
