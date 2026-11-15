# Phase 01: An toàn dữ liệu và chi phí (F8, F9, F7, F10)

## Context links

- [plan.md](plan.md), [scout F7–F10](scout/scout-01-code-locations.md), [research 01 §4–5](research/researcher-01-meta-reels-and-metrics.md)
- Đặc tả: `FR-FTG-02`, `BR-COST-02`, `BR-COST-04`, `FR-RPT-01`, `FR-RPT-02`, `FR-TRD-07`, `FR-PST-10`, `FR-TG-19`

## Overview

- Ngày: 2026-11-15. Ưu tiên: cao (tiền và khoá DB). Trạng thái: xong, test local đạt. Review: đã review (code-reviewer), đã sửa các điểm cao và trung bình.
- Bốn sửa nhỏ, độc lập, mỗi sửa một commit:
  - F8: nạp footage nhiều GB giữ khoá ghi SQLite suốt lúc chép file.
  - F9: model thiếu giá tính 0 USD (không giới hạn); ngày hạn mức theo UTC (đổi ngày lúc 07:00 giờ VN).
  - F7: lấy số liệu lỗi vẫn ghi một dòng rỗng, không bao giờ lấy lại.
  - F10: tin Telegram "hộp nháp TikTok" thiếu caption để dán.

## Key Insights

- F8: `footage_import.py:77-114` chép `shutil.copy2` bên trong `with get_conn(...)` sau INSERT; `busy_timeout` 5 giây (`db.py:21`) nên việc khác ghi DB lỗi "database is locked". Cột `sha256` UNIQUE đã chặn trùng khi chạy đua.
- F9: `budget.estimate_token_cost` trả 0.0 khi thiếu giá; giá được tính SAU lượt gọi; `check_budget` gọi TRƯỚC lượt gọi trong `ai/claude.py:71,122`, `ai/gemini.py:52,101,118`, `ai/muse_api.py:64` → thêm kiểm tra giá vào `check_budget` là đủ, không cần sửa nơi gọi khác. Chỉ áp cho đường `api`; CLI thuê bao không gọi `check_budget` theo model.
- F9: chỗ dùng ngày UTC: `budget.today_utc_str`, `reports.py:68`, `routes_dashboard.py:72`, `tg/status_messages.py:88`, `trends/links._today_key`, `trends/download.py:73`, `trends/suggest.py:103`. `trends/youtube.py:23,36` là hạn mức YouTube (reset theo giờ Pacific) → GIỮ NGUYÊN. Đã có `tzdata` trong `pyproject.toml`, `ZoneInfo` dùng ở nhiều nơi.
- F7: `collect_due_metrics` đã `continue` khi reader ném lỗi → chỉ cần reader ném lỗi thay vì trả `empty_metrics()`. Lần chạy kế tiếp sẽ thử lại cho tới hết cửa sổ 24 giờ (`due_checkpoints`). TikTok `fetch_metrics` trả `empty_metrics()` là "nền tảng không có dữ liệu" thật → giữ, vẫn ghi dòng NULL. Báo cáo tuần chỉ lấy `views IS NOT NULL`, dòng thiếu cũng được coi "không có dữ liệu" → không cần sửa báo cáo.
- F10: API hộp nháp TikTok không nhận caption (research 01 §5) → người dùng phải dán tay; `posting/captions.format_platform_caption(video_row, "tiktok")` đã có.

## Requirements

- F8: chép file xong rồi mới mở transaction; transaction chỉ gồm INSERT + đổi tên + UPDATE + audit. Lỗi giữa chừng không để lại file tạm hay dòng `path='pending'`.
- F9a: lượt gọi API với model không có trong `settings.prices` bị chặn TRƯỚC khi gọi, lỗi rõ: "Model `<x>` chưa có giá trong [prices]; thêm giá trong Settings rồi thử lại."
- F9b: một hàm duy nhất cho "ngày hôm nay" theo `schedule.timezone`, dùng cho hạn mức, báo cáo ngày, dashboard, `/status`, giới hạn link dán, giới hạn tải video tham khảo, 3 đề xuất/ngày.
- F7: lỗi mạng/HTTP/quyền → không ghi; nền tảng không có số liệu → ghi NULL như cũ.
- F10: tin hộp nháp có caption TikTok nguyên văn, tách dòng để dễ chép.

## Architecture

- `timeutil.py` thêm:
  - `local_day(tz_name: str, now_dt: datetime | None = None) -> str` → `"YYYY-MM-DD"` theo múi giờ.
  - `local_day_start_utc_iso(tz_name: str, now_dt: datetime | None = None) -> str` → 00:00 giờ địa phương đổi ra UTC ISO (`...Z`), để so với cột `created_at`/`downloaded_at` lưu UTC.
- `ai/budget.py`: `today_utc_str()` thay bằng `budget_day(settings, now_dt=None)` = `local_day(settings.schedule.timezone, now_dt)`. `check_budget(..., model: str | None = None)`: nếu `model` có và không có trong `settings.prices` → raise `BudgetExceeded(<thông báo F9a>)` (tái dùng luồng lỗi/cảnh báo hiện có). `check_budget` tự tính `day` từ `settings` khi không truyền. `record_usage` và `get_daily_api_spend` đã có tham số `day`: mọi nơi gọi trong `ai/` (đều đã có `settings`) truyền `day=budget_day(settings)`; nơi nào thiếu `day` thì `grep` và sửa, không đoán múi giờ cứng trong `budget.py`.
- Lỗi metrics: thêm `class MetricsFetchError(Exception)` trong `posting/base.py`. Reader Facebook/Instagram/Threads: lỗi mạng, HTTP != 200, thiếu token → `raise MetricsFetchError(...)`. `collect_due_metrics` bắt `MetricsFetchError` (log info, không warning dày) và `continue`.
- Nạp footage (luồng mới):

```
sha256 + dedupe check (như cũ) -> probe
tmp = media/footage/.incoming/<uuid4>.part ; copy2(source, tmp)      # ngoài transaction
with get_conn:
    INSERT footage(path='pending', ...) -> id
    os.replace(tmp, media/footage/<id>.mp4)                          # cùng ổ, tức thì
    UPDATE footage SET path=...; record_audit(...)
except: tmp.unlink(missing_ok=True); raise
```

  - Tiêm `copy_file: Callable[[Path, Path], Any] = shutil.copy2` làm tham số từ khoá của `import_footage_file` (chỉ để test chèn mã thật chạy trong lúc chép).
  - Dọn `.incoming/*.part` cũ hơn 24 giờ ở đầu `import_footage_file` (máy tắt giữa lúc chép).

## Related code files

- Sửa: `src/videocreator/pipeline/footage_import.py`, `src/videocreator/timeutil.py`, `src/videocreator/ai/budget.py`, `src/videocreator/ai/claude.py` (uncommitted, đọc kỹ), `src/videocreator/ai/gemini.py`, `src/videocreator/ai/muse_api.py`, `src/videocreator/reports.py`, `src/videocreator/api/routes_dashboard.py`, `src/videocreator/tg/status_messages.py`, `src/videocreator/trends/links.py`, `src/videocreator/trends/download.py`, `src/videocreator/trends/suggest.py`, `src/videocreator/posting/base.py`, `src/videocreator/posting/facebook.py`, `src/videocreator/posting/instagram.py`, `src/videocreator/posting/threads.py`, `src/videocreator/posting/metrics.py`, `src/videocreator/posting/publish_outcomes.py`, `docs/video-creator-spec.md`
- Tạo: không. Xoá: không.
- Test: mở rộng `tests/test_shots.py` (nạp footage), `tests/test_budget.py`, `tests/test_metrics.py`, `tests/test_reports.py`, `tests/test_tg_messages.py` hoặc `tests/test_posting_service.py` (tin hộp nháp).

## Implementation Steps

1. F8 – `footage_import.py`: chuyển chép file ra trước `with get_conn`, theo sơ đồ trên; `try/except BaseException` xoá file tạm rồi raise lại; thêm `copy_file` tham số; dọn `.part` cũ.
2. F8 – test (`test_shots.py`): (a) nạp clip mẫu thật → file ở `footage/<id>.mp4`, `.incoming/` rỗng; (b) `copy_file` tiêm vào: hàm chép thật (`shutil.copy2`) và TRONG lúc đó mở kết nối SQLite thứ hai với `busy_timeout=0` ghi một dòng `settings` → phải thành công (chứng minh không giữ khoá); (c) nạp trùng sha256 → lỗi trùng, không còn file tạm.
3. F9b – `timeutil.local_day`, `local_day_start_utc_iso` (dùng `ZoneInfo`). Test với `now_dt` cố định: 2026-11-15T18:30Z → `"2026-11-16"` cho `Asia/Ho_Chi_Minh`; đầu ngày = `2026-11-15T17:00:00Z`.
4. F9b – thay mọi chỗ ở Key Insights (trừ `youtube.py`). `links._today_key` cần tz: đọc `load_settings(paths.config_file).schedule.timezone` ở `add_pasted_link` rồi truyền xuống. `suggest.py:103`: thay `strftime('%Y-%m-%dT00:00:00Z','now')` bằng tham số `local_day_start_utc_iso(tz)`.
5. F9a – `check_budget(..., model=...)`; ba provider API truyền `model=self.model` ở mọi lần gọi `check_budget`. Không đổi `estimate_token_cost` (đã chặn trước nên không còn đường tới 0.0 ngầm; giữ trả 0.0 cho an toàn).
6. F9 – test (`test_budget.py`): model không có giá → `BudgetExceeded` với thông báo nêu tên model, không ghi `ai_usage`; model có giá → qua; `budget_day` với giờ 06:00 VN và 08:00 VN cùng ngày cho cùng một `day`.
7. F7 – `MetricsFetchError` + sửa 3 reader Meta; `collect_due_metrics` bắt riêng. Test (`test_metrics.py`): reader tiêm vào là lớp thật ném `MetricsFetchError` → 0 dòng; lần chạy sau (reader trả dict thật) trong cửa sổ → ghi 1 dòng; quá cửa sổ → không ghi; TikTok trả `empty_metrics()` → ghi dòng NULL.
8. F10 – `notify_published` nhánh `needs_user_action`: đọc dòng video, nối `"\n\nCaption để dán:\n" + format_platform_caption(video_row, "tiktok")`. Test: tạo video + post thật trong SQLite, gọi hàm dựng văn bản (tách hàm thuần `inbox_message_text(video_row, post_row)` để test không cần gửi Telegram) → chứa caption.
9. Cập nhật đặc tả: `BR-COST-02` thêm "model chưa có giá thì chặn"; ghi "ngày" = ngày theo `schedule.timezone`; `FR-PST-10` thêm "tin kèm caption để dán".
10. Chạy suite; 4 commit: `fix(footage): copy file outside the db write transaction`, `fix(budget): block unpriced models and use local day`, `fix(metrics): retry failed fetches until window end`, `feat(tiktok): include caption in inbox draft message`.

## Todo list

- [ ] F8 chép ngoài transaction + dọn `.part`
- [ ] F8 test khoá DB bằng kết nối thứ hai
- [ ] F9 `local_day` + `local_day_start_utc_iso` + test
- [ ] F9 thay 7 chỗ ngày UTC (bỏ qua youtube)
- [ ] F9 chặn model thiếu giá + test
- [ ] F7 `MetricsFetchError` + test thử lại
- [ ] F10 caption trong tin hộp nháp + test
- [ ] Sửa đặc tả, suite xanh, commit

## Success Criteria

- Trong lúc chép footage, ghi DB từ kết nối khác không bị khoá (test 2b đạt).
- Gọi API với model thiếu giá bị chặn trước khi gọi, có thông báo tiếng Việt rõ.
- Hạn mức/ báo cáo/ giới hạn ngày đổi lúc 00:00 giờ VN.
- Lỗi lấy số liệu không tạo dòng; lần sau trong cửa sổ lấy được.
- Tin hộp nháp TikTok có caption.
- Suite `-m "not live"` xanh.

## Risk Assessment

- `os.replace` khác ổ đĩa sẽ chậm/ lỗi: `.incoming/` nằm trong `media/footage/` nên luôn cùng ổ.
- Chặn model thiếu giá có thể làm dừng việc đang chạy nếu config người dùng thiếu giá (vd `gemini-3.6-flash` chỉ có trong `config.toml` của chủ máy, không có trong mặc định) → ghi chú trong tin cảnh báo + câu hỏi cho chủ dự án.
- Đổi ngày sang giờ VN: dòng `ai_usage` ngày chuyển bị lệch một lần (chấp nhận).

## Security Considerations

- Thông báo lỗi chỉ nêu tên model, không lộ key/ URL cổng.
- File tạm do app đặt tên (uuid), nằm trong thư mục media (`NFR-SEC-05`).
- Caption gửi Telegram là nội dung app sinh, gửi vào nhóm đã cho phép.

## Next steps

- Độc lập với các phase khác. Sau phase này nên thêm giá thật cho `gemini-3.6-flash` vào `_default_prices` khi chủ dự án xác nhận.
