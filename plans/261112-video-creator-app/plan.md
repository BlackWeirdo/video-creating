# Plan: Video Creator nội bộ (trang sức bạc thủ công)

Ngày: 2026-11-12 (đã rà soát nhất quán cùng ngày). Trạng thái: đang làm; bảng tiến độ rà lại ngày 2026-11-14 (cột "Tiến độ" là ước lượng, "xong" chỉ ghi khi đã chạy thật) — xem thêm [báo cáo bàn giao Claude Code 2026-11-14](reports/handoff-2026-11-14-to-claude.md). Gốc repo: `c:\Project Video Creator\`. Đặc tả hành vi (mã yêu cầu FR/BR/NFR, mô hình dữ liệu, trạng thái): [docs/video-creator-spec.md](../../docs/video-creator-spec.md); phase nào hiện thực yêu cầu nào xem mục 13 của đặc tả. Nguồn: [brainstorm](../reports/brainstorm-2026-11-12-video-creator.md) (lịch sử quyết định; chỗ nào khác plan này thì plan này đúng), [research 01](research/researcher-01-social-and-trend-apis.md), [research 02](research/researcher-02-video-pipeline-and-packaging.md), [CLAUDE.md](../../CLAUDE.md).

## Mục tiêu

Footage tự quay -> kho shot gắn sản phẩm -> kịch bản (Gemini xem, Claude viết) -> dựng 9:16 -> người duyệt (UI + Telegram) -> đăng theo lịch qua API chính thức (FB Page, IG, Threads, TikTok) -> báo cáo Telegram. Quét xu hướng -> phân tích bằng rea-video -> đề xuất video. Hai chế độ dựng: Nhanh (FFmpeg) và Studio (agent + rea-video + video-shotcraft, theo prompt).

## Kiến trúc chốt

- 1 process Python 3.11: FastAPI + worker job + APScheduler + Telegram bot, chung 1 event loop. UI: Jinja2 + HTMX (không build step), mở trong pywebview hoặc trình duyệt. Node.js chỉ cần cho Studio (phase 17).
- SQLite (stdlib `sqlite3`, WAL, migration bằng `PRAGMA user_version`). Không ORM. Layout, schema, state: [phase 02](phase-02-project-skeleton.md).
- 3 interface mỏng: `Poster` (posting), `AIProvider` (LLM/video understanding), `TrendSource`. TTS và video-gen là hàm/protocol riêng, chỉ thêm khi phase cần.
- Model chọn được trong Settings theo vai trò, qua bộ định tuyến ưu tiên gói thuê bao (phase 18): vision (Gemini, Claude), writer (Claude, Gemini, Muse Spark), giọng đọc (qua MoneyPrinterTurbo), sinh video (việc tay trong app thuê bao; Veo, Sora, cổng model qua API khi bật).
- MỘT máy chủ làm mọi việc (PC Windows bật 24/7); máy khác (`role = client`) mở UI máy chủ qua trình duyệt. Không đồng bộ giữa nhiều máy. VPS là tuỳ chọn.

## Quyết định người dùng đã chốt (2026-11-12)

| Hạng mục | Quyết định | Phase |
|---|---|---|
| Máy chủ | PC Windows bật 24/7 | 08, 10 |
| Nhạc nền, SFX | Người dùng tự nạp file đã có quyền dùng | 05, 09 |
| Tài khoản | 2–3 mỗi nền tảng; chọn tài khoản đích lúc duyệt | 07, 10, 11, 16 |
| Caption | Ngôn ngữ chọn theo video; AI viết riêng từng nền tảng | 04, 06 |
| Người duyệt | Nhóm Telegram 2–5 người, một người duyệt là đủ, ghi lại ai duyệt | 06 |
| Hạn mức AI/ngày | 5 USD remix + 15 USD sinh video; Studio có trần riêng (đặt sau S11) | 04, 14, 17 |
| Video tham khảo | App tự tải bằng yt-dlp (top N, chỉ phân tích nội bộ, tự xoá) | 13 |
| Lịch đăng | Tự xếp vào khung giờ cố định, đặt được theo từng tài khoản | 10 |
| Hai chế độ dựng | "Nhanh" (FFmpeg, hằng ngày) và "Studio" (agent nạp 2 skill, dựng theo prompt, lưu được thành mẫu). Cả hai xuất 1 bản master MP4 H.264/AAC 1080x1920, kiểm tra định dạng từng nền tảng trước khi đăng | 05, 07, 11, 17 |
| Telegram | Bảng điều khiển chính: quyết định tạo video và quyết định đăng đều trong chat | 06, 13, 16 |
| Độ chính xác sản phẩm | Hình sản phẩm chỉ từ footage thật, không sửa điểm ảnh; lời chỉ dùng thông tin sản phẩm người dùng nhập; người duyệt kiểm tra cuối | 03, 04, 05, 06, 14, 17 |
| MoneyPrinterTurbo | Dịch vụ phụ, engine lắp ráp cho chế độ Nhanh: lồng tiếng, phụ đề, nhạc, chạy lô; stock/AI video chỉ cho cảnh phụ. Tắt LLM viết lời, crop, đăng bài của nó (cần S12 đạt) | 09, 14 |
| Muse2Tele | Chỉ lấy ý tưởng giao diện Telegram (topic, phản ứng, chấm điểm, gói chỉ dẫn, tự cập nhật), tự viết lại. KHÔNG tích hợp phần nhiều tài khoản + trình duyệt giả lập + proxy + đăng bài bằng trình duyệt Google Flow qua CDP cũng loại khỏi phạm vi | 08, 16 |
| Ưu tiên gói thuê bao | AI chữ/nhìn ảnh và Studio chạy qua CLI chính thức (`claude -p`, `gemini -p`) bằng gói của chủ máy; API chỉ dự phòng, tắt được. Tạo video bằng Muse/Gemini/Flow qua "trạm việc tay"; các model video qua API (Kling, Seedance, Veo...) vẫn có sẵn, chọn khi cần. Muse Spark viết kịch bản qua API chính thức nếu đăng ký được (cần S13) | 18, 14, 17 |

## Phases (liệt kê theo THỨ TỰ THỰC HIỆN; "tuần N" trong các phase file = đợt N ở đây)

| # | Phase | Đợt | Ước lượng | Trạng thái | Tiến độ |
|---|---|---|---|---|---|
| 01 | [Kiểm chứng + đăng ký tài khoản](phase-01-verification-spikes.md) | 1 | 2 ngày (time-box) | Đang làm: S1, S7, S9, S13 đạt (kèm YouTube key, Gemini key, Telegram bot, footage thật); S11, S12 đạt một phần; S5, S10 mới đọc tài liệu; S2, S3, S4, S6, S8 chưa làm (chờ tài khoản Meta/TikTok/R2 & nghe TTS) | 65% |
| 02 | [Khung dự án, DB, config, secrets, log](phase-02-project-skeleton.md) | 1 | 0.5 ngày | Xong, test local đạt | 100% |
| 03 | [Sản phẩm + nhập footage + kho shot](phase-03-footage-import-shot-library.md) | 1 | 1 ngày | Xong, đã nạp 5 sản phẩm S925 + 9 footage Google Drive (120 shot, 24 shot đã mô tả, 96 shot chờ describe) | 100% |
| 04 | [AI provider (Gemini + Claude) + kịch bản + luật sản phẩm + trần ngân sách](phase-04-ai-provider-remix-plan.md) | 1 | 1 ngày | Xong: chạy thật Gemini API (`gemini-3.8-flash` / `gemini-3.6-flash`) + kịch bản + kiểm tra sự thật | 100% |
| 18 | [Ưu tiên gói thuê bao: provider CLI, định tuyến, Muse Spark](phase-18-subscription-first-routing.md) (cần S13) | 1 | 1 ngày | Xong định tuyến `claude_cli` -> dự phòng `gemini_api` (`api_fallback = auto`) chạy thật trong worker; Muse và `claude_api` chưa có key | 90% |
| 05 | [Dựng FFmpeg 9:16 + phụ đề + bản master + kiểm tra định dạng](phase-05-ffmpeg-render-core.md) | 1 | 1–1.25 ngày | Xong, test local đạt; sửa font phụ đề ngày 2026-11-14 | 100% |
| 06 | [Hàng chờ duyệt + Telegram bot cơ bản](phase-06-approval-queue-telegram-bot.md) | 1 | 1 ngày | Đã chạy thật với bot `@VideoCreatorSocialBot` (nhóm `VideoCreator_SS`), gửi video + 6 nút duyệt vào topic `Chờ duyệt` | 90% |
| 07 | [Đăng Facebook Page + Instagram (R2), nhiều tài khoản](phase-07-posting-facebook-instagram.md) | 1 | 1.25–1.75 ngày | Đã viết mã, test local đạt; CHƯA đăng thật lên Facebook/Instagram/R2 (chờ S2, S3) | 60% |
| 08 | [Bộ cài .exe + xuất/nhập cấu hình + tự chạy cùng Windows](phase-08-installer-config-transfer.md) | 1 | 0.75–1 ngày | Đã viết script; CHƯA build bộ cài (máy chưa có Inno Setup), chưa thử trên máy thứ hai | 40% |
| 09 | [Engine MoneyPrinterTurbo: lồng tiếng, phụ đề, nhạc, chạy lô](phase-09-beat-sync-sfx-voiceover.md) (cần S12 đạt) | 1 (dễ trượt) | 1–1.5 ngày | Lồng tiếng + phụ đề theo giọng chạy thật (viết lại ngày 2026-11-14 theo S12); còn S8, nghe thử, giọng trả tiền | 70% |
| 10 | [Lên lịch tự động + retry + cảnh báo](phase-10-scheduling-retry-alerts.md) | 2 | 0.5 ngày | Đã viết mã, test local đạt; chưa chạy một ngày thật | 70% |
| 11 | [Threads + TikTok](phase-11-threads-tiktok.md) | 2 | 1 ngày + chờ audit | Đã viết mã; CHƯA gọi Threads/TikTok thật (chờ S4, S5). Rà mã 2026-11-14: sửa lỗi biến chưa khai báo khi TikTok đăng xong và thêm tải lên nhiều phần cho file trên 64 MB theo tài liệu TikTok | 50% |
| 12 | [Nguồn xu hướng + xếp hạng](phase-12-trend-sources.md) | 2 | 1–1.5 ngày | Xong phần YouTube Data API v3 (quét thật 15 `trend_items` theo watchlist); Ad Library/IG chưa chạy (chờ S6) | 75% |
| 13 | [Tải + phân tích video xu hướng (rea-video) + đề xuất](phase-13-trend-analysis-suggestions.md) | 2 | 1.5 ngày | Xong: tải `ref_1.mp4`, chạy đủ `rea-video decompose` (`rea_1`), phân tích Gemini, sinh đề xuất khớp kho shot (`#4`, `#5`) & dựng thành công `video #10` (`8.8/10`) | 95% |
| 16 | [Điều khiển app qua Telegram + chấm điểm tự động](phase-16-telegram-control-center.md) | 2 | 1.75–2.25 ngày | Chạy thật qua 6 topic Telegram (`Xu hướng`, `Chờ duyệt`...): nhận thao tác bấm nút tạo video trên Telegram + chấm điểm Vision (`video #10` đạt `8.8/10`) | 85% |
| 17 | [Studio: dựng theo prompt bằng agent + 2 skill](phase-17-studio-agent-two-skills.md) (cần S11 đạt) | 3 | 3–4 ngày | Chạy thật (2026-11-14) trong hàng đợi việc: kịch bản → điểm dừng xác nhận → dựng Remotion → giọng đọc từng cảnh → bản master; sửa bằng prompt; dựng từ mẫu không cần agent. Còn: phân tích video tham khảo (chờ video xu hướng), cắt theo nhịp nhạc, caption, chọn shot trong form (xem [báo cáo](reports/17-studio-spike.md)) | 70% |
| 14 | [Cảnh phụ: trạm việc tay + Kling/Seedance/Veo qua API + stock](phase-14-generative-broll.md) | 4 | 2–2.5 ngày | Đã viết mã, test luật đạt; CHƯA sinh clip thật qua API nào. 2026-11-14: thêm đề xuất cảnh phụ tự động (`FR-BRL-06`), chạy thật qua `claude_cli`: prompt Việt + Anh, look đồng nhất theo số đo rea-video của video mẫu, nút huỷ; sửa 3 nút mẫu gợi ý bị hỏng | 55% |
| 15 | [Báo cáo hiệu quả bài đăng](phase-15-performance-report.md) | 4 | 0.5 ngày | Đã viết mã, test tính toán đạt; CHƯA lấy số liệu thật. Rà mã 2026-11-14: Instagram đổi chỉ số `plays` (đã bị bỏ) sang `views` | 60% |

Mỗi phase = 1 phiên Claude Code (phase 17 cần 3–4 phiên), kết thúc bằng thứ chạy và xem được. Phụ thuộc: 01 -> 02 -> 03 -> 04 -> 18 -> 05 -> 06 -> 07 -> 08; 09 cần 05 và S12; 10, 11 cần 07; 12 cần 02 + 04 + 07; 13 cần 12 và S1; 16 cần 06 + 10 + 13; 17 cần 03 + 04 + 06 + 13 và S11; 14 cần 05; 15 cần 07. Migration đánh số theo thứ tự thực hiện (xem phase 02).

## Kiểm thử (không mock)

- `pytest -m local`: FFmpeg thật trên clip mẫu thật (người dùng cấp 2–3 clip 5–10 giây vào `tests/samples/`), SQLite thật, state machine thật.
- `pytest -m live`: gọi API thật (Gemini, Claude, R2, Telegram, Meta, YouTube...). Thiếu key thì skip, không giả lập. Cần tài khoản thử của người dùng. Thao tác cần người (bấm nút Telegram, OAuth, nghe giọng đọc, chấm chất lượng video): checklist tay trong từng phase.

## Rủi ro lịch (nói thẳng)

- Tổng ước lượng: đợt 1 = 10.75–12.25 ngày, đợt 2 = 6–7 (đã tính sao lưu/dọn đĩa), đợt 3 = 3–4, đợt 4 = 2.5–3; cộng 22–26 ngày làm việc, KHÔNG có đệm. Thực tế nên tính 6–7 tuần. Bản dùng được đầu tiên (hết phase 07) sau khoảng 9–10 ngày làm việc.
- Dễ trượt nhất: 07 (Meta Live mode/App Review, nằm ngoài tầm kiểm soát), 08 (máy thứ hai), 09 (TTS tiếng Việt), 11 (TikTok audit), 12 (quyền Ad Library/IG), 17 (nhiều ẩn số nhất, chỉ làm khi S11 đạt).
- Cắt theo thứ tự: (1) phase 09 còn nhạc nền đơn giản; (2) bộ cài 08, máy chủ chạy `uv run`; (3) Instagram hashtag; (4) Ad Library; (5) Workbench và Telegram "Sửa:" ở 17; (6) Sora trực tiếp và stock ở 14 (Kling, Seedance, Veo qua API không cắt); (7) phase 15.
- Nếu spike Meta hỏng (cần App Review): dùng gói "tải video + caption" để đăng tay tới khi review xong.

## Câu hỏi chưa giải quyết (đều được trả lời bằng spike ở phase 01 hoặc bước đọc docs của phase liên quan)

1. Meta: app Live không review có đăng công khai được không; loại token; 2–3 Page/IG có chung 1 Business không (S2, S3).
2. TikTok: hồ sơ audit, có cần video demo không, 1 app chưa audit uỷ quyền được mấy tài khoản (S5, phase 11).
3. rea-video và video-shotcraft trên Windows; chi phí và thời gian 1 phiên Studio; giấy phép Remotion cho công ty (S1, S11). MoneyPrinterTurbo có giữ thứ tự/độ dài đoạn, không crop, có giọng Việt dùng được cho thương mại không (S12).
4. Giới hạn chính thức từng nền tảng: thời lượng, dung lượng, ký tự caption (S10, phase 11). `yt-dlp` tải được nguồn nào; Ad Library có lấy được file không (S6, phase 13). Cổng model sinh video: fal.ai hay Replicate (phase 14).
5. Điều khoản hiện hành cho `claude -p`/`gemini -p` bằng gói thuê bao; hạn mức Pro có đủ không hay cần Max; Gemini CLI có đọc video không; Meta Model API có mở cho tài khoản người dùng không (S13).
