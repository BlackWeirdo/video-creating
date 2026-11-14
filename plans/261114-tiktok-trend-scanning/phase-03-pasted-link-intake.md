# Phase 03: Dán link video từ 5 nền tảng (giao diện + Telegram)

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 01](phase-01-migration-adapter-config.md) (`run_yt_dlp_json`, `classify_ytdlp_failure`, ánh xạ trường). Không phụ thuộc phase 02.
- Docs: [spike](reports/01-spike-ytdlp-tiktok-real-run.md) mục "Not tested", [research 01](research/researcher-01-tiktok-official-data-access.md), [scout 01](scout/scout-01-trend-pipeline-touchpoints.md)
- Mã liên quan: `src/videocreator/api/routes_trends.py:181` (route nạp file tham khảo tay, đã có), `src/videocreator/tg/handlers.py`

## Overview

- Ngày: 2026-11-14 (viết lại cùng ngày theo quyết định của chủ: BẮT BUỘC làm, mở rộng ra mọi nền tảng)
- Mô tả: chủ thấy 1 video hay ở bất kỳ đâu (tab "Đề xuất" của TikTok, Reels, Shorts, Thư viện quảng cáo), dán link vào ô trên `/trends` HOẶC bấm Chia sẻ -> Telegram gửi cho bot. App đọc số liệu của đúng video đó, lưu thành bài xu hướng, phân tích, và ưu tiên đưa vào đề xuất.
- Ưu tiên: P1 (đây là đường duy nhất đưa video từ tab "Đề xuất" của TikTok vào app, xem plan.md mục "Đăng nhập tài khoản TikTok")
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Tab "Đề xuất" (For You) của TikTok không quét tự động được (plan.md). Cách thay thế: người lướt bằng điện thoại, gặp video hay thì Chia sẻ -> Telegram. Một thao tác, không rủi ro cho tài khoản.
- yt-dlp bản đang ghim có bộ đọc video đơn cho cả 5 nơi: `TikTok`, `vm.tiktok`, `youtube`, `Instagram`, `facebook`, `facebook:reel`, `facebook:ads` (đã liệt kê bằng `--list-extractors` ngày 2026-11-14). **Chưa cái nào được chạy thật cho việc này.** Instagram thường đòi đăng nhập; Facebook lúc được lúc không. Bước 1 thử thật từng nơi; nơi nào hỏng thì nơi đó báo "không đọc được, hãy tải file rồi nạp tay" (route nạp tay đã có), KHÔNG dùng cookie.
- Bài dán thường cũ -> điểm thấp (điểm chia cho tuổi bài) -> không bao giờ lọt top để phân tích. Vì vậy: (a) job riêng `analyse_trend` phân tích ngay bài đó; (b) đánh dấu `metrics.pinned = true` để phase 04 ưu tiên bài dán khi chọn đề xuất.
- Hàng đợi job chỉ mang `ref_id` kiểu số -> route đọc metadata ngay (vài giây, luồng phụ), upsert lấy `trend_item_id`, rồi xếp job với `ref_id = trend_item_id`.
- `trend_items.source` không có CHECK -> lưu được nguồn mới mà không cần migration. Bài dán dùng tên nền tảng: `tiktok`, `youtube`, `instagram`, `facebook`. Bài quét tự động của Instagram vẫn mang tên adapter (`ig_discovery`, `ig_hashtag`); phase 04 gom chúng về cùng nhóm nền tảng.
- Link Thư viện quảng cáo: quảng cáo không có lượt xem công khai -> bài có thể thiếu số liệu, điểm = 0. Vẫn nhận vì chủ đã chọn; chỉ dùng để phân tích cấu trúc.
- Bot Telegram trong nhóm: nếu bật "privacy mode" (chế độ riêng tư, mặc định của bot) thì bot KHÔNG thấy tin nhắn thường, chỉ thấy lệnh. Phải kiểm ở bước 2; phương án chắc chắn chạy là lệnh `/link <url>`.

## Requirements

- Form trên `/trends`: 1 ô `url` + nút "Thêm video".
- Telegram: trong nhóm đã cấp phép (`telegram.allowed_chat_ids`), người thuộc `approver_user_ids` gửi `/link <url>`; nếu bước 2 xác nhận bot thấy tin nhắn thường thì nhận cả tin nhắn chỉ chứa link trong chủ đề "Xu hướng". Bot trả lời 1 dòng: đã nhận + tên tác giả + số view, hoặc câu lỗi.
- Host được nhận (so khớp chính xác, chỉ `https`):

| Nền tảng | Host | `source` lưu |
|---|---|---|
| TikTok | `tiktok.com`, `www.`, `m.`, `vm.`, `vt.` | `tiktok` |
| YouTube | `youtube.com`, `www.`, `m.`, `youtu.be` | `youtube` |
| Instagram | `instagram.com`, `www.` | `instagram` |
| Facebook (Reels, video, Thư viện quảng cáo) | `facebook.com`, `www.`, `m.`, `web.`, `fb.watch` | `facebook` |

- Khác -> 400 `Chỉ nhận link video TikTok, YouTube, Instagram, Facebook.`
- Đọc metadata: `find_yt_dlp_command() + ["--no-playlist", "--skip-download", "-J", "--no-warnings", url]`, timeout 60 s, UTF-8.
- Kết quả là playlist (chủ dán link trang cá nhân/kênh) -> 400 `Đây là link tài khoản. Hãy thêm ở trang Watchlist.`
- Ánh xạ dùng tên trường chung của yt-dlp: `id`, `webpage_url`, `uploader`/`channel`, `description`/`title`, `timestamp` (thiếu thì dùng `upload_date`; thiếu cả hai thì dùng giờ hiện tại và ghi `metrics.date_unknown = true`), `view_count`, `like_count`, `comment_count`, `repost_count`, `duration`. Thêm `metrics.pinned = true`.
- Bài YouTube dán vào mà đã có từ lần quét (`(source, external_id)` trùng): upsert cập nhật số liệu và đặt `pinned`, không tạo bài thứ hai.
- Xếp job `analyse_trend` cho bài đó nếu chưa có `analysis_json`.
- Lỗi đọc -> không lưu gì; thông báo cố định theo nền tảng, kèm gợi ý nạp file tay.
- Không lọc `lookback_days` cho bài dán. Không tính vào trần 20 lượt/ngày của quét tài khoản TikTok. Trần riêng cho dán link: 20 link/ngày (bộ đếm `pasted_links:<ngày>` trong `settings`) để lỡ tay hoặc lỡ lộ quyền bot cũng không dồn yêu cầu.

## Architecture

```
trends/links.py                                           # file mới, không phình tiktok.py
  platform_of_url(url) -> "tiktok"|"youtube"|"instagram"|"facebook"|None    # thuần
  parse_single_video(data, source) -> TrendItem           # thuần, ném ValueError nếu thiếu id
  fetch_single_video(url) -> TrendItem                    # run_yt_dlp_json (phase 01) + parse; lỗi -> RuntimeError câu tiếng Việt
  add_pasted_link(paths, url) -> tuple[int, TrendItem]    # trần ngày + fetch + upsert + enqueue; dùng chung cho web và Telegram

api/routes_trends.py
  POST /trends/add-link   (Form url) -> asyncio.to_thread(add_pasted_link) -> 303 /trends?msg=link_added
  def run_analyse_trend_job(paths, trend_item_id) -> str:
      analyse_trend_item(paths, trend_item_id); make_suggestions(paths)

app.py
  job_registry.register("analyse_trend", lambda ref_id: run_analyse_trend_job(paths, int(ref_id or 0)))

tg/handlers.py
  lệnh "link": kiểm chat + người gửi như các lệnh đổi trạng thái sẵn có -> add_pasted_link -> trả lời 1 dòng
```

`make_suggestions` vẫn tự giữ trần đề xuất/ngày; `fetch_reference_video` vẫn tự giữ trần file/ngày (hết suất thì bài dán được phân tích theo số liệu + caption).

`trends.html`: thêm 1 thẻ `<section class="card">` nhỏ dưới phần lọc nguồn, chú thích: `Dán link video TikTok, YouTube, Instagram hoặc Facebook. Video sẽ được phân tích (khoảng 20 phút nếu tải được file) và được ưu tiên khi tạo đề xuất.` Bài dán hiện nhãn "tự chọn". Nút lọc nguồn hiện đang dựng từ danh sách adapter -> bài `instagram`/`facebook` chỉ thấy ở "Tất cả nguồn"; đổi nút lọc sang danh sách nhóm nền tảng của phase 04 (làm ở phase 04).

## Related code files

Tạo:
- `src/videocreator/trends/links.py`
- `tests/test_trends_links.py`
- `tests/samples/pasted_<platform>.json` (JSON thật ghi ở bước 1, mỗi nền tảng đọc được 1 file; bỏ khoá `formats`, `thumbnails` cho gọn, ghi rõ ở đầu test)
- `plans/261114-tiktok-trend-scanning/reports/03-probe-single-video.md`

Sửa:
- `src/videocreator/api/routes_trends.py` (route + hàm job)
- `src/videocreator/app.py` (1 lệnh `register`)
- `src/videocreator/tg/handlers.py` (lệnh `link`, thêm vào danh sách lệnh và trợ giúp)
- `src/videocreator/web/templates/trends.html`
- `tests/test_trends_live.py`

Không sửa: `analyse.py`, `download.py`. (`suggest.py` sửa ở phase 04.)

## Implementation Steps

1. **Thử thật trước khi viết mã**, mỗi nền tảng 1–2 link công khai do chủ đưa (TikTok thường + link rút gọn `vm.tiktok.com`, YouTube Shorts, Instagram Reel, Facebook Reel, 1 link Thư viện quảng cáo). Với mỗi link: đọc metadata (`-J`) rồi thử TẢI bằng `_default_yt_dlp_download`. Ghi bảng kết quả (đọc được? tải được? có tiếng? trường nào có) vào `reports/03-probe-single-video.md`, lưu JSON làm mẫu test. Nền tảng nào đọc không được: vẫn nhận link nhưng trả câu `Không đọc được video <nền tảng> này nếu không đăng nhập. Hãy tải file về rồi nạp ở cột "Nạp file tham khảo".` Không thêm cookie, không thêm phụ thuộc.
2. **Thử thật Telegram**: gửi 1 tin nhắn thường chứa link và 1 lệnh `/link <url>` trong chủ đề "Xu hướng"; ghi bot nhận được cái nào. Thử thao tác Chia sẻ từ app TikTok trên điện thoại vào nhóm, ghi lại định dạng tin nhắn (thường kèm chữ mô tả trước link -> phải tách link bằng biểu thức tìm `https://...` đầu tiên).
3. Viết `trends/links.py`.
4. Thêm route `POST /trends/add-link`, hàm `run_analyse_trend_job`, đăng ký job trong `app.py`.
5. Thêm lệnh Telegram `link`.
6. Sửa `trends.html`.
7. Test local (không mạng, không mock):
   - `parse_single_video` trên từng mẫu thật: đủ trường, số liệu khớp file, có `pinned`.
   - `platform_of_url`: nhận đủ các host trong bảng; từ chối `http://`, `https://tiktok.com.evil.io/...`, `https://evil.io/?u=tiktok.com`, chuỗi bắt đầu bằng `-`, `file:///...`.
   - Tách link từ tin nhắn chia sẻ thật ghi ở bước 2.
   - Route với URL sai host -> 400, `trend_items` không thêm dòng, không job nào được xếp.
   - Upsert 2 lần cùng mẫu -> 1 dòng; bài quét trước đó rồi dán lại -> vẫn 1 dòng, có `pinned`.
   - Trần 20 link/ngày trên SQLite thật.
   - Xử lý lệnh Telegram từ người không thuộc `approver_user_ids` -> bị từ chối, không có gì được lưu (theo cách `tests/test_tg_flows.py` đang dựng tin nhắn).
8. Test live (cổng `VIDEOCREATOR_LIVE_TIKTOK=1`): `fetch_single_video(<link TikTok trong mẫu>)` trả item có `external_id` đúng id trong link.
9. Chạy thật trên máy chủ: dán 1 link trên web và gửi 1 link từ điện thoại qua Telegram; cả hai hiện ở `/trends`, job `analyse_trend` chạy xong, cột "Phân tích cấu trúc" có nội dung.

## Todo list

- [ ] Thử thật 5 loại link (đọc + tải), ghi báo cáo
- [ ] Thử thật Telegram (tin thường, lệnh, chia sẻ từ app)
- [ ] `trends/links.py`
- [ ] Route + job `analyse_trend`
- [ ] Lệnh Telegram `link`
- [ ] Form + chú thích + nhãn "tự chọn" trên `/trends`
- [ ] Test local + live
- [ ] Dán 1 link trên web + 1 link qua Telegram, xem phân tích

## Success Criteria

- Từ điện thoại: đang xem video TikTok -> Chia sẻ -> Telegram -> trong vài giây bot trả lời đã nhận; bài hiện ở `/trends`; job phân tích hoàn tất.
- Dán lại cùng link không tạo bài trùng.
- Link ngoài danh sách bị từ chối mà không có yêu cầu mạng nào.
- Với mỗi nền tảng, báo cáo ghi rõ: đọc được / không đọc được nếu không đăng nhập. Nền tảng không đọc được có câu hướng dẫn nạp tay, không gãy.

## Risk Assessment

- Instagram/Facebook không đọc được nếu không đăng nhập (khả năng cao với Instagram) -> nền tảng đó chỉ còn đường nạp file tay. Báo chủ đúng kết quả thử, không tìm đường vòng.
- Bot không thấy tin nhắn thường trong nhóm -> chỉ còn `/link <url>`; chia sẻ từ app phải dán thêm chữ `/link` phía trước, kém tiện. Cách gỡ: chủ tắt privacy mode của bot trong BotFather (việc của chủ, 1 lần), rồi thêm lại bot vào nhóm.
- Chủ dán nhiều link liên tiếp -> mỗi link 1 job phân tích ~20 phút + 1 lượt gọi AI; trần 20 link/ngày và trần file/ngày chặn bớt, ngân sách AI chung chặn phần còn lại.
- Route chờ tối đa 60 s nếu nền tảng treo -> chạy ở luồng phụ, không khoá máy chủ.
- Ước lượng 6–8 giờ (tăng từ 3–4 giờ do thêm 3 nền tảng và Telegram); bước 1 và 2 quyết định phạm vi thật.

## Security Considerations

- Chống SSRF (ép máy chủ gọi địa chỉ lạ): so khớp host chính xác theo bảng, chỉ `https`; yt-dlp nhận URL qua danh sách tham số, không qua shell; sau khi đọc, `extractor_key` phải thuộc nhóm của nền tảng đã nhận diện, không thì từ chối.
- Telegram: chỉ nhận từ chat trong `allowed_chat_ids` và người trong `approver_user_ids`, cùng lớp kiểm tra với các lệnh đổi trạng thái sẵn có.
- Thông báo lỗi là câu cố định, không nhúng stderr.
- Caption bài dán là dữ liệu ngoài, đi qua cùng lớp `<untrusted_caption>` sẵn có.
- Không cookie, không đăng nhập, không proxy (`BR-REF-04`).

## Next steps

- Phase 04: chia suất tải / phân tích / đề xuất đều giữa các nền tảng và ưu tiên bài dán.
