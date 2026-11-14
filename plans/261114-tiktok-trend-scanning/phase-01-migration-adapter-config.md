# Phase 01: Migration 010 + adapter TikTok + đăng ký + config

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: không. Chặn phase 02, 03, 04.
- Docs: [scout 01](scout/scout-01-trend-pipeline-touchpoints.md), [spike](reports/01-spike-ytdlp-tiktok-real-run.md), mẫu thật `reports/spike-tiktok-user-flat-sample.json`
- Mã mẫu để bắt chước: `src/videocreator/trends/youtube.py` (lớp + bộ đếm ngày), `src/videocreator/trends/download.py` (gọi yt-dlp)

## Overview

- Ngày: 2026-11-14
- Mô tả: cho bảng `watch_items` nhận nguồn `tiktok`; viết adapter đọc danh sách video mới của 1 tài khoản bằng yt-dlp; đăng ký vào `build_trend_sources`; thêm 3 khoá config; test không mock.
- Ưu tiên: P1 (chặn mọi phase sau)
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- `migrate()` (`db.py:43-57`) đánh số theo **vị trí file sau khi sắp tên**, không theo số trong tên. File mới phải sắp thứ 10: `010_watch_items_tiktok.sql`.
- `executescript` tự commit từng lệnh nếu script không có `BEGIN`. Dựng lại bảng phải bọc `BEGIN; ... COMMIT;` để hoặc xong hết hoặc không đổi gì. Lỗi giữa chừng: `get_conn` rollback, `user_version` vẫn 9, lần khởi động sau chạy lại.
- Không bảng/index/trigger nào khác tham chiếu `watch_items` (đã grep 001–009: chỉ có ở `002_trends.sql:3`). Mã đọc bảng: chỉ `scan.py`, `routes_trends.py`.
- `find_yt_dlp_command()` luôn trả về lệnh (cuối cùng là `python -m yt_dlp`), nên "thiếu yt-dlp" phải kiểm bằng `importlib.util.find_spec("yt_dlp")` / file exe, không chạy tiến trình con: `status()` được gọi mỗi lần mở `/watchlist` và `/trends`, phải rẻ và không gọi mạng.
- `scan.py:141` dừng nguồn khi chuỗi lỗi chứa `429`, `613`, `quota`, `giới hạn`. Thông báo lỗi cấp tài khoản KHÔNG được chứa mấy chuỗi này và KHÔNG nhúng stderr thô của yt-dlp (id video có thể chứa `429`); stderr chỉ ghi log.
- `run_scan_and_suggest_job` chỉ trả số đếm, bỏ `scan_res["errors"]` -> chủ không thấy lỗi nguồn. Thêm lỗi vào chuỗi trả về (lưu vào `jobs.log_tail`, 2000 ký tự).
- Mẫu thật có 3 bài, mốc 2026-11-13T02:30Z, 11-11T22:35Z, 11-11T15:00Z -> đủ để test bộ lọc `lookback_days` với `now_dt` cố định, không cần bịa số.
- Spike CHƯA thử: bị chặn, tài khoản không tồn tại / riêng tư / rỗng. Phải thử thật ở bước 2 rồi mới viết mẫu nhận diện.

## Requirements

- Migration 010 giữ nguyên `id, source, kind, value, enabled, created_at` và `UNIQUE (source, kind, value)`.
- `TikTokTrendSource`: `name = "tiktok"`, `kinds = ("account",)`, `status()`, `fetch(watch)`.
- Ánh xạ sang `TrendItem` theo spike: `external_id = id`; `url = url`; `author = channel or uploader`; `caption = (description or title)[:1000]`; `published_at = fromtimestamp(timestamp, UTC)`; `metrics = {views, likes, comments, shares (= repost_count), saves (= save_count), duration_s}`; `video_url = url`.
- Bỏ phần tử `None`, thiếu `id`/`timestamp`/`url`, hoặc cũ hơn `trends.lookback_days`.
- Danh sách rỗng (exit 0, 0 bài) = không lỗi, trả `[]`, ghi log info.
- Config `[trends]` (không đụng `[tiktok]` của phần đăng bài):

```python
class TrendsConfig(BaseModel):
    ...
    tiktok_max_videos_per_account: int = 15
    tiktok_pause_seconds: int = 5
    tiktok_max_listings_per_day: int = 20
```

- Bộ đếm ngày: khoá `settings` = `tiktok_listings:<YYYY-MM-DD UTC>`, tăng TRƯỚC khi gọi (tính cả lần lỗi), giống `yt_quota:<day>`.

## Architecture

```
trends/tiktok.py
  normalise_tiktok_handle(value) -> "@handle"        # thuần, ném ValueError (câu tiếng Việt)
  parse_user_listing(data, *, now_dt, lookback_days) -> list[TrendItem]   # thuần
  classify_ytdlp_failure(stderr) -> "blocked" | "account"                 # thuần; không khớp mẫu nào -> "blocked"
  get_tiktok_listings_used(db_file, day_str=None) / add_tiktok_listings_used(db_file, day_str=None)
  run_yt_dlp_json(args, timeout_s=60) -> tuple[int, dict | None, str]     # (exit code, json, stderr)
  class TikTokTrendSource: status(), fetch()
```

Tách hàm thuần để test bằng dữ liệu thật đã ghi mà không cần mạng và không cần mock.

`normalise_tiktok_handle`: nhận `handle`, `@handle`, `https://www.tiktok.com/@handle` (kèm `/`, `?lang=..`, `/video/<id>`); trả `@` + chữ thường. Hợp lệ: `^[a-z0-9_.]{2,24}$`, không kết thúc bằng `.`. Khác -> `ValueError("Tài khoản TikTok không hợp lệ. Nhập dạng @tenkenh hoặc https://www.tiktok.com/@tenkenh")`. Link rút gọn `vm.tiktok.com` bị từ chối (không gọi mạng để giải).

`fetch` (thứ tự):

```python
ok, reason = self.status()
if not ok: raise RuntimeError(reason)
handle = normalise_tiktok_handle(watch.value)          # ValueError -> RuntimeError cấp tài khoản
# pause: nếu self._last_call có và chưa đủ cfg.trends.tiktok_pause_seconds thì time.sleep phần còn thiếu
add_tiktok_listings_used(db_file)
rc, data, stderr = run_yt_dlp_json([
    "--flat-playlist", "--playlist-end", str(n), "-J", "--no-warnings",
    f"https://www.tiktok.com/{handle}"])
# TimeoutExpired, rc != 0, data None -> classify_ytdlp_failure(stderr)
```

Thông báo (cố định, không nhúng stderr):
- blocked / timeout / lỗi lạ: `TikTok từ chối hoặc yt-dlp không đọc được (giới hạn truy cập): dừng nguồn tiktok tới lần quét sau. Nếu lặp lại nhiều ngày, yt-dlp có thể cần nâng phiên bản.`
- account: `Không đọc được tài khoản TikTok {handle}: không tồn tại, riêng tư hoặc đã đổi tên.`

`status()`:
- thiếu yt-dlp -> `(False, "chưa bật: thiếu yt-dlp")`
- bộ đếm >= trần -> `(False, "chưa bật: đã đủ {used}/{cap} lượt đọc TikTok hôm nay")`
- còn lại `(True, None)`

Migration `src/videocreator/migrations/010_watch_items_tiktok.sql`:

```sql
-- Migration 010: allow 'tiktok' and 'facebook' as watch_items sources.
-- ('facebook' has no adapter yet; allowing it now avoids a second table rebuild, see phase 05.)
-- SQLite cannot alter a CHECK constraint, so the table is rebuilt inside one transaction.
BEGIN;
DROP TABLE IF EXISTS watch_items_new;
CREATE TABLE watch_items_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL CHECK (source IN ('youtube', 'ig_discovery', 'ad_library', 'ig_hashtag', 'tiktok', 'facebook')),
    kind TEXT NOT NULL CHECK (kind IN ('account', 'hashtag', 'keyword', 'page')),
    value TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (source, kind, value)
);
INSERT INTO watch_items_new (id, source, kind, value, enabled, created_at)
SELECT id, source, kind, value, enabled, created_at FROM watch_items;
DROP TABLE watch_items;
ALTER TABLE watch_items_new RENAME TO watch_items;
COMMIT;
```

Ghi chú: bộ đếm AUTOINCREMENT của bảng mới = id lớn nhất đang có (id đã xoá ở cuối có thể được dùng lại). Không bảng nào tham chiếu id này nên vô hại; không thêm lệnh sửa `sqlite_sequence`.

## Related code files

Tạo:
- `src/videocreator/migrations/010_watch_items_tiktok.sql`
- `src/videocreator/trends/tiktok.py`
- `tests/samples/tiktok_user_flat.json` (chép nguyên `reports/spike-tiktok-user-flat-sample.json`, không sửa nội dung)
- `tests/samples/tiktok_ytdlp_errors/*.txt` (stderr thật ghi ở bước 2)
- `tests/test_trends_tiktok.py`
- `plans/261114-tiktok-trend-scanning/reports/02-probe-error-wording.md`

Sửa:
- `src/videocreator/trends/scan.py` (import + 1 dòng `"tiktok": TikTokTrendSource(paths, sec)`)
- `src/videocreator/config.py` (`TrendsConfig`, 3 trường)
- `src/videocreator/api/routes_trends.py` (`run_scan_and_suggest_job`: nối `errors` vào chuỗi trả về)
- `tests/test_trends_live.py` (thêm 1 test, không sửa test YouTube)

Không sửa: `base.py`, `rank.py`, `download.py`, `analyse.py`, `suggest.py`, `posting/*`, `tests/test_tiktok_live.py`.

## Implementation Steps

1. Đọc lại các file sẽ sửa (quy tắc "đọc trước rồi mới sửa").
2. **Thử thật để lấy câu chữ lỗi** (4 yêu cầu, cách nhau >= 5 s), lưu nguyên stderr vào `tests/samples/tiktok_ytdlp_errors/` và tóm tắt vào `reports/02-probe-error-wording.md`:
   - tài khoản không tồn tại (handle ngẫu nhiên dài);
   - tài khoản riêng tư (nếu chủ biết 1 cái; không có thì ghi "chưa thử");
   - tài khoản công khai chưa đăng bài nào (nếu có);
   - `https://www.tiktok.com/tag/silverjewelry` (đã biết: `No working app info is available`, dùng làm mẫu nhóm "blocked").
   KHÔNG cố tạo tình huống bị chặn bằng cách gọi dồn. Mẫu "blocked" ban đầu: `403`, `429`, `captcha`, `No working app info`, cộng mọi thứ không khớp nhóm "account".
3. Viết migration 010 đúng SQL ở trên.
4. Thêm 3 trường vào `TrendsConfig`.
5. Viết `trends/tiktok.py` theo mục Architecture. Tiến trình con: `capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, check=False`, truyền danh sách tham số (không `shell=True`).
6. Đăng ký trong `build_trend_sources`.
7. `run_scan_and_suggest_job`: nếu `scan_res["errors"]` khác rỗng thì thêm `, errors={...}` vào chuỗi trả về. Kiểm tra trang nào hiện `jobs.log_tail`; nếu không trang nào hiện thì ghi vào "Next steps", không làm trang mới.
8. Test `tests/test_trends_tiktok.py` (`@pytest.mark.local`, không mạng, không mock):
   - **Parser trên mẫu thật**: `now_dt = 2026-11-14T10:00Z`, `lookback_days=30` -> 3 item; item đầu `external_id == "7707477921664912653"`, `author == "Tiffany&Co."`, `metrics == {"views": 144800, "likes": 1257, "comments": 11, "shares": 19, "saves": 91, "duration_s": 34}`, `published_at` có tzinfo UTC; `score_trend_item` > 0 và bài 144800 view xếp trên bài 2103 view. `lookback_days=2` -> đúng 1 item; `lookback_days=1` -> 0 item.
   - **Phần tử hỏng**: `{"entries": [null]}` (dạng thật yt-dlp trả khi lỗi) -> `[]`; bản sao 1 bản ghi thật bỏ khoá `timestamp` -> bị loại (dẫn xuất từ dữ liệu thật, không bịa số).
   - **Chuẩn hoá handle**: `tiffanyandco`, `@TiffanyAndCo`, `https://www.tiktok.com/@tiffanyandco?lang=en`, `.../@tiffanyandco/video/7707477921664912653` -> `@tiffanyandco`; `#silver`, `silver ring`, `https://youtube.com/@x`, `-J`, chuỗi rỗng -> `ValueError`.
   - **Phân loại lỗi**: từng file stderr thật ở bước 2 -> đúng nhóm; chuỗi lạ -> `blocked`.
   - **Migration giữ dữ liệu**: chép 001–009 sang thư mục tạm, `migrate(db, migrations_dir=tmp)` -> `user_version == 9`; chèn 3 dòng `watch_items` (1 dòng `enabled=0`, `created_at` cụ thể) + xoá 1 dòng để id không liên tục; chèn thử `tiktok` -> `sqlite3.IntegrityError`; `migrate(db)` -> `user_version == 10`; so từng cột của từng dòng bằng trước; chèn `tiktok` được; chèn trùng `(source, kind, value)` vẫn lỗi; chèn `source='x'` vẫn lỗi; `migrate(db)` lần nữa không đổi gì.
   - **Trần ngày**: gọi `add_tiktok_listings_used` 20 lần trên SQLite thật -> `status()` trả `False` + lý do có `20/20`; khoá ngày khác không bị tính.
   - **Quét không gãy khi TikTok tắt**: thêm 1 mục `tiktok` + 1 mục `youtube` (thiếu key), đẩy bộ đếm tới trần, `scan_all(paths)` không ném lỗi, `errors["tiktok"]` chứa `chưa bật`, `errors["youtube"]` vẫn có; không có yêu cầu mạng (vì `status()` chặn trước).
   - **Config**: `load_settings` trên file config cũ không có 3 khoá mới -> ra mặc định 15/5/20; `save_settings` rồi `load_settings` giữ giá trị đã đổi.
9. Test live trong `tests/test_trends_live.py`: `@pytest.mark.live`, bỏ qua trừ khi `VIDEOCREATOR_LIVE_TIKTOK=1`; `TikTokTrendSource(paths).fetch(WatchItem(1, "tiktok", "account", "@tiffanyandco"))` -> >= 1 item đủ `external_id`, `url`, `published_at`, `metrics["views"]` là số; bộ đếm ngày tăng đúng 1.
10. Chạy `.venv/Scripts/python.exe -m pytest tests/test_trends_tiktok.py tests/test_rank.py tests/test_db.py tests/test_transfer.py`.

## Todo list

- [ ] Thử thật, ghi câu chữ lỗi (bước 2)
- [ ] Migration 010
- [ ] 3 khoá config
- [ ] `trends/tiktok.py`
- [ ] Đăng ký nguồn + lỗi trong kết quả job
- [ ] Chép mẫu vào `tests/samples/`
- [ ] Test local (8 nhóm)
- [ ] Test live có cổng biến môi trường
- [ ] 4 file test liên quan xanh

## Success Criteria

- DB phiên bản 9 có dữ liệu lên 10 không mất dòng nào; chạy `migrate` lần hai không đổi gì.
- Test parser khớp đúng số liệu trong mẫu thật.
- `VIDEOCREATOR_LIVE_TIKTOK=1` -> test live trả >= 1 bài thật.
- `tests/test_rank.py`, `test_db.py`, `test_transfer.py` vẫn xanh, không sửa nội dung các test đó.

## Risk Assessment

- Migration hỏng trên DB thật -> đã bọc giao dịch; vẫn bắt buộc sao lưu trước (phase 06 bước 4) và chạy thử trên bản sao.
- Câu chữ lỗi tài khoản không lấy được ở bước 2 -> mọi lỗi thành "dừng nguồn"; hệ quả: 1 handle gõ sai đứng trước trong danh sách làm các tài khoản TikTok sau nó không được quét, cho tới khi chủ sửa/tắt mục đó. Chấp nhận được, ghi rõ trong hướng dẫn.
- yt-dlp đổi tên trường (`repost_count`...) -> parser dùng `.get`, thiếu thì 0; test live phát hiện.
- Nghỉ 5 s chỉ nhớ trong 1 lần quét (thuộc tính của đối tượng); hai lần "Quét ngay" liên tiếp không có nghỉ giữa chúng, chỉ có trần 20/ngày chặn. Không làm thêm (YAGNI).
- Ước lượng 5–6 giờ; dễ trượt ở bước 2 (không tìm được tài khoản riêng tư để thử) và test migration.

## Security Considerations

- Handle qua regex chặt, URL do app tự ghép `https://www.tiktok.com/@...` -> không chèn được tham số dòng lệnh (`-...`) hay host khác.
- Không cookie, không đăng nhập, không proxy, không `--impersonate`, không thêm `curl_cffi` (`BR-REF-04`).
- Caption là dữ liệu ngoài: đã được `analyse.py` bọc `<untrusted_caption>`; Jinja tự escape khi hiển thị. Không đổi.
- Chỉ lưu metadata công khai + link. File mẫu test không chứa IP (`__x_forwarded_for_ip` là `null`), URL ảnh bìa có chữ ký đã hết hạn.

## Next steps

- Phase 02: chặn đầu vào sai ở `/watchlist/add` và thêm lựa chọn TikTok trên giao diện.
