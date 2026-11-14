# Phase 06: Chạy thật, ma trận xung đột, tài liệu

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 01](phase-01-migration-adapter-config.md), [phase 02](phase-02-watchlist-validation-ui.md), [phase 03](phase-03-pasted-link-intake.md), [phase 04](phase-04-fair-share-across-platforms.md). KHÔNG chờ [phase 05](phase-05-meta-sources-activation.md): phần Instagram/Facebook/quảng cáo kiểm bổ sung khi chủ có token Meta
- Docs: [đặc tả](../../docs/video-creator-spec.md) (`FR-TRD-01..09`, `BR-REF-01..04`, mục 13, 14, 15), [plan app](../261112-video-creator-app/plan.md) dòng phase 12

## Overview

- Ngày: 2026-11-14
- Mô tả: chứng minh bằng chạy thật rằng nguồn TikTok hoạt động và không làm hỏng phần nào khác; sao lưu + nâng DB thật; cập nhật đặc tả và plan app.
- Ưu tiên: P1
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- DB thật đang ở phiên bản 9, có dữ liệu thật (1 mục theo dõi, 15 bài, 5 đề xuất). Migration 010 chạy ngay lần khởi động đầu với mã mới (`app.py:197`).
- Thư mục dữ liệu KHÔNG nằm trong repo. Lấy đường dẫn: `.venv/Scripts/python.exe -c "from videocreator.paths import get_paths; p=get_paths(); print(p.db_file, p.backups_dir)"` (chạy với cùng biến `VIDEOCREATOR_DATA` như máy chủ, nếu có).
- Một lần quét đầy đủ có TikTok lâu hơn rõ rệt: thêm tới 3 bài phân tích, mỗi bài ~20 phút rea-video trên CPU. Lần quét kiểm chứng có thể mất 1.5–2 giờ; phần lớn phase này là chờ.
- Tồn bài chưa phân tích: 3 tài khoản x tối đa 15 bài = 45 bài; mỗi lần quét phân tích 3 bài TikTok -> chi phí AI/máy đều đặn nhiều ngày, kể cả khi không có bài mới.

## Requirements

### Ma trận xung đột và hồi quy

| Phần sẵn có | Rủi ro khi thêm TikTok | Phép kiểm chứng minh không hỏng |
|---|---|---|
| Chuỗi migration | 010 dựng lại bảng trên dữ liệu thật; đánh số theo vị trí file | Test "migration giữ dữ liệu" (phase 01); chạy `migrate` trên BẢN SAO DB thật rồi so `SELECT * FROM watch_items` trước/sau; `PRAGMA user_version` = 10; `PRAGMA integrity_check` = ok |
| Nguồn YouTube / IG / Ad Library | Đổi `build_trend_sources`, đổi route thêm watchlist | `tests/test_rank.py` xanh không sửa; cùng 1 lần quét thật có cả bài YouTube mới/cập nhật lẫn TikTok |
| Lỗi 1 nguồn không chặn nguồn khác (`FR-TRD-03`) | TikTok bị chặn làm gãy cả lần quét | Test "quét không gãy khi TikTok tắt"; trong chạy thật thêm 1 handle không tồn tại, lần quét vẫn xong và YouTube vẫn có kết quả |
| Chấm điểm (`FR-TRD-04`) | Khoá metrics lệch -> điểm 0 | Test parser khẳng định điểm > 0 và đúng thứ tự; `rank.py` không sửa (`git diff` rỗng với file này) |
| Trần tải tham khảo 5/ngày dùng chung | Một nền tảng lấy hết suất | Phase 04 xoay vòng theo nền tảng. Sau lần quét: `SELECT COUNT(*) FROM reference_videos WHERE downloaded_at LIKE '<hôm nay>%'` <= `download_top_n`; mỗi nền tảng có bài đều được >= 1 suất trước khi nền tảng nào được suất thứ 2 |
| rea-video ~20 phút/video CPU | Job quét dài thêm tới ~60 phút, chiếm hàng đợi (dựng video khác phải chờ) | Ghi giờ bắt đầu/kết thúc job `scan_trends` trước và sau khi có TikTok; kiểm 1 job `render` xếp sau vẫn chạy xong; không job nào quá `REA_DECOMPOSE_TIMEOUT_S` (1800 s) |
| Hạn mức / ngân sách AI | +3 lượt `vision`/`writer` mỗi lần quét; đang có 9 job kẹt `waiting_quota` | TRƯỚC khi bật: đếm `SELECT status, COUNT(*) FROM jobs GROUP BY status`, tìm nguyên nhân 9 job kẹt; SAU: số job `waiting_quota` không tăng do quét; so tổng `ai_usage` của ngày với `budget.daily_usd`. Nếu quota đang cạn: bắt đầu với 1 tài khoản |
| Trần đề xuất/ngày (`FR-TRD-07`) | Trần đổi từ số 3 viết cứng sang `trends.max_suggestions_per_day` (mặc định 5); TikTok điểm cao lấn nền tảng khác | `SELECT COUNT(*) FROM suggestions WHERE created_at >= <hôm nay>` <= trần; đề xuất trong ngày thuộc >= 2 nền tảng khi >= 2 nền tảng có bài đã phân tích; bài tự chọn (`pinned`) có đề xuất |
| Lệnh Telegram sẵn có (`/scan`, `/trends`, nút duyệt) | Thêm lệnh `/link` làm lệch bộ xử lý lệnh | `tests/test_tg_flows.py`, `test_tg_messages.py` xanh; gửi thử `/scan` và bấm 1 nút duyệt sau khi thêm `/link` |
| Chọn bài để phân tích / đề xuất khi chỉ có 1 nền tảng | Xoay vòng làm trống suất | Test phase 04 "chỉ có 2 nhóm"; chạy thật khi mới chỉ có YouTube + TikTok: đủ suất, không trống |
| Thẻ Telegram | Thẻ giả định link YouTube | `tests/test_tg_messages.py`, `test_tg_flows.py`, `test_suggestion_flow.py` xanh; 1 thẻ TikTok thật tới chủ đề "Xu hướng", link mở được, nút bấm hoạt động |
| Xuất/nhập cấu hình (`.vcx`) | 3 khoá config mới; gói cũ chứa DB phiên bản 9 | `tests/test_transfer.py` xanh; test config cũ thiếu khoá -> mặc định (phase 01). Nhập gói cũ: `import_config_bundle` tự gọi `migrate` (`transfer.py:153`) |
| Mã ĐĂNG bài TikTok, `[tiktok] mode`, `tests/test_tiktok_live.py` | Trùng tên, lẫn config | `git diff --stat` không có file nào trong `posting/`, không đổi `TikTokConfig`; `config.toml` sau khi lưu vẫn có `[tiktok] mode` như cũ; `test_tiktok_live.py` không sửa, kết quả như trước |
| Bộ cài / yt-dlp ghim `2026.10.26` | Thêm phụ thuộc mới làm lệch bộ cài | `git diff pyproject.toml uv.lock` rỗng (không thêm `curl_cffi`, không đổi bản ghim) |
| Sao lưu đêm (02:30) | Không đổi | Sau 1 đêm có file `backup_<ngày>_app.db` mới, mở được, `user_version` = 10 |

### Kiểm chứng chạy thật (trên máy chủ đang chạy)

- 2–3 tài khoản thương hiệu trang sức thật do chủ chọn.
- 1 link dán trên web + 1 link gửi từ điện thoại qua Telegram (phase 03).
- "Quét ngay" -> bài TikTok có điểm trên `/trends?source=tiktok`.
- 1 video TikTok tải qua bộ tải sẵn có -> rea-video phân tích xong.
- 1 thẻ đề xuất tới chủ đề Telegram "Xu hướng".
- YouTube vẫn quét được trong cùng lần chạy.

### Tài liệu

- `docs/video-creator-spec.md`:
  - `FR-TRD-01`: thêm ghi chú TikTok chỉ nhận tài khoản.
  - `FR-TRD-02`: thêm vào danh sách nguồn: `TikTok (chỉ theo dõi tài khoản qua yt-dlp, không đăng nhập; không quét hashtag/từ khoá)`.
  - `FR-TRD-10`: dán link video TikTok / YouTube / Instagram / Facebook trên `/trends` hoặc gửi `/link` qua Telegram; bài tự chọn được ưu tiên phân tích và đề xuất.
  - `FR-TRD-04`, `FR-TRD-06`, `FR-TRD-07`: ghi cách xoay vòng theo nền tảng và trần đề xuất/ngày theo config (phase 04).
  - Ghi rõ: không quét tab "Đề xuất" của TikTok bằng tài khoản đăng nhập (lý do ở plan.md).
  - Bảng dịch vụ ngoài (mục 14): dòng yt-dlp đổi thành `Tải video tham khảo; đọc số liệu công khai tài khoản TikTok`; thêm ghi chú `TikTok không có API chính thức cho mục đích này`.
  - Mục 13: `FR-TRD-01..04 | 12` thêm `+ plan 261114`.
  - Giả định 5 (mục 15): mở rộng "tải video tham khảo" thành "tải video tham khảo và đọc số liệu công khai TikTok bằng công cụ tự động (trái điều khoản TikTok, lượng thấp, không đăng nhập)".
  - Rủi ro (mục 16): thêm dòng `yt-dlp hỏng khi TikTok đổi trang | Nguồn TikTok ngừng ra bài | Nâng bản ghim theo quy trình`.
- `plans/261112-video-creator-app/plan.md` dòng phase 12: thêm `TikTok (theo dõi tài khoản + dán link) xem plan 261114`, cập nhật % theo kết quả thật.
- `plan.md` của kế hoạch này: cập nhật trạng thái/tiến độ từng phase.

## Architecture

Không có mã mới. Thứ tự an toàn khi lên máy chủ thật:

```
dừng máy chủ -> sao lưu app.db -> thử migration trên bản sao -> khởi động mã mới
-> kiểm user_version=10 + dữ liệu cũ -> thêm tài khoản -> Quét ngay -> đối chiếu ma trận
```

Sao lưu (chạy được cả khi máy chủ còn mở, vì dùng API backup của SQLite; KHÔNG chép tay file `.db` khi đang chạy vì còn file `-wal`):

```
.venv/Scripts/python.exe -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" "<data_dir>/app.db" "<data_dir>/backups/pre-010_app.db"
```

Thử trên bản sao: chép `pre-010_app.db` sang thư mục tạm, gọi `migrate(<bản sao>)`, so `watch_items` trước/sau, `PRAGMA integrity_check`.

## Related code files

Sửa (chỉ tài liệu):
- `docs/video-creator-spec.md`
- `plans/261112-video-creator-app/plan.md`
- `plans/261114-tiktok-trend-scanning/plan.md`

Tạo:
- `plans/261114-tiktok-trend-scanning/reports/04-verification-results.md` (số liệu thật: giờ chạy, số bài, suất tải, lượt AI, ảnh/chữ thẻ Telegram, kết quả bộ test)

Không sửa mã trong phase này. Phát hiện lỗi -> quay lại phase tương ứng.

## Implementation Steps

1. Chạy toàn bộ test: `.venv/Scripts/python.exe -m pytest` (~7 phút). Ghi số pass/skip; so với lần chạy trước khi làm tính năng (lấy mốc bằng `git stash` hoặc số đã ghi trong báo cáo bàn giao). Không được có test nào từ pass thành fail/skip.
2. Chạy test live TikTok một lần: đặt `VIDEOCREATOR_LIVE_TIKTOK=1`, `-m pytest tests/test_trends_live.py`.
3. Ghi trạng thái trước: số job theo `status`, số `trend_items` theo nguồn, số `suggestions`, số `reference_videos` hôm nay, nội dung `watch_items`.
4. Dừng máy chủ. Sao lưu `app.db` (lệnh trên) + chép `config.toml`. Thử migration trên bản sao; đạt mới đi tiếp.
5. Khởi động máy chủ với mã mới. Kiểm: `user_version` = 10; `watch_items` y nguyên; `/watchlist` có dòng nguồn `tiktok` "Đang bật"; `/trends` có nút lọc `tiktok`.
6. Thêm 2–3 tài khoản trang sức thật qua giao diện (thử 1 lần dạng link, 1 lần dạng `@handle`). Thử thêm sai (`tiktok` + hashtag) để thấy khung lỗi.
7. Bấm "Quét ngay". Theo dõi job tới khi xong; ghi thời lượng.
8. Đối chiếu:
   - `/trends?source=tiktok`: có bài, có điểm, số view/like/comment khớp khi mở bài gốc (lệch nhỏ do thời gian là bình thường), tiếng Việt/emoji trong caption không vỡ chữ;
   - `reference_videos` có >= 1 dòng của bài TikTok, file `media/reference/ref_<id>.mp4` phát được, CÓ tiếng (TikTok đôi khi trả luồng không tiếng ở 1080p: nếu thiếu tiếng thì ghi nhận, không sửa `download.py` trong kế hoạch này);
   - bài đó có `analysis_json` (hook, nhịp cắt...), thư mục `media/reference/rea_<id>/` có `VIDEO.md`;
   - Telegram chủ đề "Xu hướng" có thẻ đề xuất; phải có ít nhất 1 thẻ từ TikTok (phase 04 chia suất theo nền tảng) và 1 thẻ từ bài tự chọn;
   - bài YouTube có `fetched_at` của lần quét này.
9. Thử lỗi cấp tài khoản: thêm 1 handle không tồn tại, quét lại -> lần quét xong, `jobs.log_tail` có câu lỗi tài khoản, các tài khoản khác vẫn có bài. Xoá mục thử.
10. Thử rollback: tắt hết mục `tiktok`, quét lại -> bộ đếm `tiktok_listings:<ngày>` trong `settings` không tăng. Bật lại.
11. Điền từng dòng ma trận vào `reports/04-verification-results.md` (đạt / không đạt + số liệu).
12. Cập nhật đặc tả, plan app, `plan.md` này. Trả lời các câu hỏi chưa giải quyết bằng số liệu vừa đo.

### Rollback

- Mức 1 (đủ cho mọi trường hợp thường gặp): tắt các mục `tiktok` trong Watchlist. Không còn yêu cầu nào tới TikTok. Bài TikTok đã lưu vẫn còn và vẫn được phân tích dần (3 bài/lần quét); muốn dừng cả phần đó: `DELETE FROM trend_items WHERE source = 'tiktok' AND analysis_json IS NULL;` (dòng `reference_videos` liên quan tự xoá theo, đề xuất không bị xoá).
- Mức 2: quay mã về bản trước. DB phiên bản 10 vẫn dùng được với mã cũ: `migrate` thấy phiên bản >= số file nên bỏ qua; bảng `watch_items` cùng cột, chỉ CHECK rộng hơn; mục `tiktok` còn bật sẽ báo `Nguồn 'tiktok' không tồn tại` và bị bỏ qua, không gãy.
- KHÔNG khôi phục bản sao lưu phiên bản 9 trừ khi dữ liệu hỏng: làm vậy mất mọi thứ ghi sau lúc sao lưu.

### Khi yt-dlp hỏng với TikTok

Chủ thấy: `/trends` không có bài TikTok mới; kết quả job quét ghi `giới hạn truy cập ... yt-dlp có thể cần nâng phiên bản`; YouTube và phần còn lại vẫn chạy. Lỗi 1 ngày có thể là TikTok chặn tạm; lặp lại 2–3 ngày liên tiếp thì nâng bản:

1. Xem bản mới nhất và ghi chú sửa TikTok tại trang phát hành yt-dlp.
2. Đổi dòng ghim trong `pyproject.toml` (`yt-dlp==<bản mới>`), cập nhật `uv.lock` + venv bằng `uv lock` và `uv sync` (`uv.exe` nằm ở `%LOCALAPPDATA%\Microsoft\WinGet\Packagesstral-sh.uv_*\`).
3. Chạy `VIDEOCREATOR_LIVE_TIKTOK=1 ... pytest tests/test_trends_live.py` và test parser.
4. Tải thử 1 video YouTube tham khảo (đường tải chung dùng cùng yt-dlp) để chắc bản mới không làm hỏng YouTube.
5. Chạy toàn bộ test, khởi động lại máy chủ, dựng lại bộ cài nếu đang phát hành cho máy khác.
6. Bản mới vẫn hỏng: tắt các mục `tiktok`, chờ bản sau. Không dùng cookie, proxy hay công cụ khác.

## Todo list

- [ ] Toàn bộ test xanh, không hồi quy
- [ ] Test live TikTok đạt
- [ ] Sao lưu + thử migration trên bản sao
- [ ] Khởi động mã mới, DB = 10, dữ liệu cũ nguyên vẹn
- [ ] Thêm 2–3 tài khoản thật, Quét ngay
- [ ] Bài TikTok có điểm trên `/trends`
- [ ] 1 video TikTok tải + rea-video xong
- [ ] Thẻ đề xuất tới Telegram
- [ ] YouTube vẫn quét trong cùng lần
- [ ] Thử lỗi tài khoản + thử rollback
- [ ] Điền ma trận vào báo cáo
- [ ] Cập nhật đặc tả + plan app + plan này

## Success Criteria

- Mọi dòng ma trận có kết quả "đạt" kèm số liệu, hoặc "không đạt" kèm việc cần làm; không dòng nào bỏ trống.
- Bộ test đầy đủ: số test pass >= mốc trước + số test mới; 0 fail.
- Chuỗi thật chạy trọn: tài khoản -> bài có điểm -> file tham khảo -> phân tích -> thẻ Telegram.
- Đặc tả ghi đúng giới hạn: TikTok = theo dõi tài khoản + dán link.

## Risk Assessment

- TikTok chặn IP máy chủ ngay trong lúc kiểm chứng -> dừng, không thử lại trong ngày; ghi câu chữ lỗi thật vào mẫu test (bổ sung cho phase 01 bước 2).
- Tải video TikTok thất bại (chưa từng thử) -> bài lùi về phân tích theo số liệu + caption đúng `BR-REF-04`; tiêu chí "rea-video phân tích 1 video TikTok" ghi "không đạt", tính năng vẫn dùng được ở mức thấp hơn. Báo chủ, không tìm đường vòng.
- Quota AI cạn giữa chừng -> job vào `waiting_quota`; không phải lỗi của tính năng nhưng che mất kết quả. Vì vậy bước 3 phải xử lý 9 job kẹt trước.
- Lần quét dài ~2 giờ chiếm hàng đợi -> làm vào lúc không có việc dựng gấp.
- Ước lượng 4–6 giờ, trong đó 2–3 giờ là chờ máy; có thể kéo sang ngày thứ hai nếu phải chờ thẻ TikTok (trần 3 đề xuất/ngày).

## Security Considerations

- Bản sao lưu `pre-010_app.db` chứa dữ liệu thật: để trong `<data_dir>/backups/`, không chép vào repo, không commit.
- Báo cáo kiểm chứng không ghi token, chat id, hay đường dẫn chứa tên người dùng Windows.
- Vị thế điều khoản ghi thẳng trong đặc tả: thu thập tự động trái điều khoản TikTok; app giữ lượng thấp (<= 20 yêu cầu/ngày), chỉ số liệu công khai, không đăng nhập/cookie/proxy/vượt chặn, dùng nội bộ, không đăng lại nội dung (`BR-REF-02`, `BR-REF-03`). Rủi ro thực tế: IP bị giới hạn tạm. Không có tài khoản TikTok nào của chủ tham gia vào việc quét, nên tài khoản đăng bài không bị liên đới qua đường này.

## Next steps

- Chạy 1–2 tuần, ghi tần suất lỗi thật của yt-dlp và phân bổ suất tải/đề xuất giữa các nguồn.
- Khi chủ có token Meta: làm phase 05, rồi chạy lại các dòng ma trận về phân suất với >= 3 nền tảng.
- Không mở rộng sang hashtag/từ khoá cho tới khi có đường chính thức.
