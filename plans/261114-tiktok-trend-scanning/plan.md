# Kế hoạch: xu hướng đa nền tảng, thêm TikTok (theo dõi tài khoản + dán link + chia suất đều)

Ngày: 2026-11-14 (sửa lần 2 cùng ngày theo phản hồi của chủ). Trạng thái: chưa bắt đầu, chưa viết mã. Gốc repo: `c:\Project Video Creator\`.
Nguồn: [scout 01](scout/scout-01-trend-pipeline-touchpoints.md), [spike chạy thật](reports/01-spike-ytdlp-tiktok-real-run.md) (ưu tiên hơn research khi khác nhau), [research 01](research/researcher-01-tiktok-official-data-access.md), [research 02](research/researcher-02-ytdlp-tiktok-extraction.md), [đặc tả](../../docs/video-creator-spec.md), [CLAUDE.md](../../CLAUDE.md).

## Tóm tắt

Chủ cần video xu hướng của CẢ TikTok, YouTube, Instagram, Facebook Reels và quảng cáo. Kế hoạch gồm 3 việc:
1. Thêm nguồn `tiktok` vào đường quét sẵn có (watchlist -> quét -> chấm điểm -> tải tham khảo -> rea-video -> đề xuất -> Telegram), đọc số liệu công khai bằng yt-dlp (công cụ dòng lệnh đọc/tải video, đã ghim phiên bản trong app), không đăng nhập.
2. Dán link / gửi link qua Telegram cho video của bất kỳ nền tảng nào; bài tự chọn được ưu tiên phân tích và đề xuất.
3. Chia suất tải, phân tích, đề xuất đều giữa 5 nền tảng; bật thật các nguồn Instagram / Facebook / quảng cáo khi có token Meta.

## Các phase

| # | Phase | Ước lượng thật | Trạng thái | Tiến độ |
|---|---|---|---|---|
| 01 | [Migration 010 + bộ đọc TikTok + config](phase-01-migration-adapter-config.md) | 5–6 giờ | Chưa bắt đầu | 0% |
| 02 | [Kiểm tra đầu vào watchlist + giao diện](phase-02-watchlist-validation-ui.md) | 2–3 giờ | Chưa bắt đầu | 0% |
| 03 | [Dán link 5 nền tảng (giao diện + Telegram)](phase-03-pasted-link-intake.md) | 6–8 giờ | Chưa bắt đầu | 0% |
| 04 | [Chia suất đều giữa nền tảng + ưu tiên bài tự chọn](phase-04-fair-share-across-platforms.md) | 4–5 giờ | Chưa bắt đầu | 0% |
| 05 | [Bật thật Instagram, Facebook Reels, quảng cáo](phase-05-meta-sources-activation.md) | 4–10 giờ + chờ Meta | Chờ chủ cấp token Meta | 0% |
| 06 | [Chạy thật, ma trận xung đột, tài liệu](phase-06-verification-docs.md) | 4–6 giờ (phần lớn chờ máy) | Chưa bắt đầu | 0% |

Tổng phase 01–04 + 06: 3–4 ngày làm việc, không đệm. Phase 05 tính riêng vì phụ thuộc Meta. Thứ tự: 01 -> 02 -> 03 -> 04 -> 06; 05 làm lúc nào có token. Test viết ngay trong phase tạo ra mã.

## Mỗi nền tảng làm được gì (nói thẳng)

| Nền tảng | Tự động | Bằng tay |
|---|---|---|
| YouTube Shorts | Từ khoá + kênh (đang chạy) | Dán link |
| TikTok | CHỈ tài khoản chủ chọn | Dán link / Chia sẻ qua Telegram (kể cả video ở tab "Đề xuất") |
| Instagram | Tài khoản brand + hashtag, sau khi có token Meta (mã có, chưa chạy thật) | Dán link (nếu đọc được không đăng nhập) hoặc nạp file |
| Facebook Reels | Chưa có; phụ thuộc quyền Meta, thử ở phase 05 | Dán link hoặc nạp file |
| Quảng cáo | Meta Ad Library, chỉ quảng cáo có phân phối ở EU, sau xác minh danh tính | Dán link Thư viện quảng cáo / Creative Center |

## Đăng nhập tài khoản TikTok để quét tab "Đề xuất": KHÔNG làm

- Đăng nhập chính thức (TikTok Login Kit / Display API): app chỉ đọc được video của CHÍNH tài khoản đó. Không có quyền nào cho tab "Đề xuất", tìm kiếm hay hashtag. Vô ích cho việc này.
- Đăng nhập không chính thức (lấy cookie phiên rồi giả làm trình duyệt gọi API nội bộ): làm được về kỹ thuật, nhưng (a) TikTok khoá tài khoản khi phát hiện, và nếu là tài khoản thương hiệu thì mất luôn kênh đăng bài; (b) phải giả chữ ký và vân tay trình duyệt, hỏng liên tục, trái `BR-REF-04` và quyết định đã chốt "không trình duyệt giả lập"; (c) yt-dlp có cookie cũng không quét được hashtag (bộ đọc đang hỏng hẳn).
- Thay thế trong kế hoạch: người lướt tab "Đề xuất" trên điện thoại, gặp video hay bấm Chia sẻ -> Telegram -> bot nhận, phân tích, ưu tiên đề xuất (phase 03 + 04).

## Quyết định chính

1. Nguồn `tiktok`, `src/videocreator/trends/tiktok.py`, `kinds = ("account",)`; giới hạn lịch sự trong `[trends]`: 15 video/tài khoản, nghỉ 5 s, 20 lượt đọc/ngày.
2. Bị chặn / lỗi lạ -> dừng nguồn tiktok hết lần quét; lỗi riêng 1 tài khoản -> quét tiếp tài khoản sau.
3. ~~Migration `010_watch_items_tiktok.sql`~~ **Đã làm 2026-11-14** trong [plan nguồn Facebook](../261114-meta-reels-facebook-sources/plan.md): `010_watch_items_more_sources.sql` đã nhận cả `tiktok` và `facebook`. Phase 01 bỏ bước viết migration, chỉ còn adapter + config. Kiểm tra đầu vào Watchlist (phase 02) và dán link Facebook/Instagram (một phần phase 03) cũng đã có; phase 03 chỉ còn thêm host TikTok/YouTube vào `trends/links.py`.
4. `/watchlist/add` kiểm nguồn + loại, sai trả 400 kèm câu tiếng Việt.
5. Bài dán: `metrics.pinned = true`, job `analyse_trend` phân tích ngay, trần 20 link/ngày.
6. Chọn bài để tải / phân tích / đề xuất: xoay vòng theo 5 nhóm nền tảng, bài `pinned` trước. Sửa `analyse.py`, `suggest.py` (thay quyết định cũ "không sửa").
7. Không sửa: `rank.py`, `download.py`, mã ĐĂNG bài TikTok và `[tiktok]`. Không cookie, không proxy, không thêm `curl_cffi`.
8. Test không mock: mẫu JSON thật đã ghi, SQLite thật, test live TikTok bật bằng `VIDEOCREATOR_LIVE_TIKTOK=1`.

## Giới hạn nói thẳng

- Điều khoản TikTok cấm thu thập tự động. Ở đây: số liệu công khai, <= 20 yêu cầu quét + <= 20 link/ngày, không đăng nhập, dùng nội bộ. Cùng "vùng xám" chủ đã chấp nhận ở giả định 5 của đặc tả; không phải được TikTok cho phép.
- yt-dlp có thể hỏng bất kỳ lúc nào nền tảng đổi trang. Khi hỏng: nguồn đó không ra bài mới, phần còn lại vẫn chạy. Quy trình nâng phiên bản: phase 06.
- Bộ đọc Instagram, Ad Library viết từ tài liệu, chưa chạy thật: coi là chưa xong tới khi phase 05 chạy.

## Rollback (quay lui)

Tắt các mục `tiktok` trong Watchlist -> không còn yêu cầu nào tới TikTok. Migration 010 để nguyên (chỉ nới CHECK). Chia suất theo nền tảng khi chỉ có 1 nền tảng cho kết quả như cũ. Chi tiết: [phase 06](phase-06-verification-docs.md).

## Câu hỏi chưa giải quyết

1. **Trần đề xuất/ngày**: 5 nền tảng nhưng đặc tả đang là 3/ngày. Kế hoạch đặt mặc định 5 (đổi được trong config). Chủ xác nhận 5, hay giữ 3 và xoay vòng qua ngày?
2. **9 job kẹt `waiting_quota`**: nên xử lý trước khi bật (mỗi lần quét thêm lượt phân tích). Chủ chưa trả lời.
3. **Câu chữ lỗi của yt-dlp** khi bị chặn / tài khoản không tồn tại chưa biết; phase 01 bước 2 thử thật.
4. **Instagram / Facebook có đọc được link đơn khi không đăng nhập không**: chưa thử; phase 03 bước 1.
5. **Bot Telegram có thấy tin nhắn thường trong nhóm không** (privacy mode); phase 03 bước 2. Không thấy thì dùng `/link <url>` hoặc chủ tắt privacy mode trong BotFather.
6. **Facebook Reels tự động**: cần quyền "Page Public Content Access" qua App Review; chưa biết API có trả Reels + lượt xem của Page khác không; phase 05 bước 5.
7. Tên tài khoản TikTok chứa `429`/`613` có thể làm dừng nguồn thừa khi tài khoản đó lỗi. Chấp nhận, không sửa `scan.py`.
