# Phase 02: Ưu tiên hàng đợi + đề xuất theo lô (F3)

## Context links

- [plan.md](plan.md), [scout F3](scout/scout-01-code-locations.md)
- Đặc tả: `FR-TRD-05..07`, `FR-TG-12`, `NFR-PERF-03` (bấm tạo video → dưới 5 phút), `NFR-MNT-03` (migration đánh số)

## Overview

- Ngày: 2026-11-15. Ưu tiên: cao (người dùng bấm "Tạo video" trên Telegram có thể chờ hàng giờ). Trạng thái: xong, test local đạt. Review: đã review (code-reviewer), đã sửa các điểm cao và trung bình.
- Hàng đợi một worker lấy việc theo `id ASC`. Mỗi lần quét xếp 10 việc `analyse_trend` mỗi nguồn (rea-video tối đa 30 phút/việc) → việc `plan`/`render` của người dùng xếp sau. Ngoài ra đề xuất được sinh sau MỖI video phân tích xong → 3 đề xuất/ngày rơi vào video xong sớm nhất, không phải video tốt nhất.

## Key Insights

- `jobs` không có cột ưu tiên (`migrations/001_core.sql:120-130`); `job_store.claim_next_queued_job` `ORDER BY id ASC`; `jobs.enqueue_job(db_file, kind, ref_id)` là nơi duy nhất INSERT.
- Kind người dùng chờ: `plan`, `render`, `replan`, `studio`. Nền: `analyse_trend`, `scan_trends`/`trend_scan`, `describe`, `broll_suggest`, `analyse`. Đọc `job_handlers.py` (uncommitted) để lấy đúng danh sách kind hiện có.
- `links.run_analyse_trend_job` gọi `make_suggestions` sau mỗi item; `scan_job.py` gọi ngay sau khi xếp hàng (thường chưa có gì phân tích).
- `select_suggestion_candidates` đã ưu tiên `pinned` (link dán tay) rồi theo `score` → khi gọi một lần cuối lô, 3 đề xuất tự rơi vào video tốt nhất.
- Một worker không ngắt được việc đang chạy: nếu rea-video đang chạy 30 phút thì việc người dùng vẫn chờ việc đó xong. Giảm `auto_analyse_top_n` giảm số lần gặp cảnh này.

## Requirements

- Việc người dùng chờ luôn được lấy trước việc nền đang xếp hàng.
- Link dán tay (pinned) được phân tích trước video quét tự động, và có đề xuất ngay khi phân tích xong.
- Video quét tự động: sinh đề xuất MỘT lần khi không còn việc `analyse_trend` nào `queued`/`running`/`waiting_quota` (ngoài việc hiện tại), kể cả khi việc cuối cùng của lô bị lỗi.
- `trends.auto_analyse_top_n` mặc định 3.
- Việc cũ trong DB (trước migration) vẫn chạy được (ưu tiên 0).

## Architecture

- Migration `src/videocreator/migrations/012_job_priority.sql`:

```sql
ALTER TABLE jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(status, priority DESC, id);
```

- `jobs.py`:

```python
PRIORITY_USER = 10      # someone is waiting: plan, render, replan, studio
PRIORITY_PINNED = 5     # trend video the owner pasted by hand
PRIORITY_BACKGROUND = 0
USER_FACING_KINDS = frozenset({"plan", "render", "replan", "studio"})

def enqueue_job(db_file, kind, ref_id=None, *, priority: int | None = None) -> int:
    prio = priority if priority is not None else (PRIORITY_USER if kind in USER_FACING_KINDS else PRIORITY_BACKGROUND)
```

- `claim_next_queued_job`: `ORDER BY priority DESC, id ASC`.
- `analyse_queue.enqueue_trend_analysis(paths, trend_item_id)`: đọc `json_extract(metrics_json,'$.pinned')`; pinned → `priority=PRIORITY_PINNED`.
- `links.run_analyse_trend_job` nhận thêm `job_id` (handler có sẵn id việc; kiểm tra chữ ký trong `job_handlers.py`) rồi gọi helper mới:

```python
def maybe_make_suggestions(paths, trend_item_id, *, pinned: bool, job_id: int | None) -> list[int]:
    if pinned:
        return make_suggestions(paths, trend_item_ids=[trend_item_id], max_suggestions=1)
    if other_analyse_jobs_active(paths, exclude_job_id=job_id):
        return []          # batch still running; the last job of the batch does it
    return make_suggestions(paths)
```

  - Gọi ở nhánh thành công VÀ ở nhánh `except Exception` (trước `raise`, bọc try riêng để lỗi đề xuất không che lỗi gốc). Không gọi ở nhánh `QuotaWaitRequested` (việc sẽ chạy lại).
- `suggest.make_suggestions(..., trend_item_ids: list[int] | None = None)`: lọc ứng viên theo danh sách; vẫn tôn trọng 3/ngày.
- `scan_job.py`: chỉ gọi `make_suggestions` khi `enqueue_top_trends` không xếp được việc nào (có thể còn item đã phân tích chưa có đề xuất).

## Related code files

- Tạo: `src/videocreator/migrations/012_job_priority.sql`
- Sửa: `src/videocreator/jobs.py`, `src/videocreator/job_store.py`, `src/videocreator/job_handlers.py` (uncommitted), `src/videocreator/trends/analyse_queue.py` (uncommitted), `src/videocreator/trends/links.py` (uncommitted), `src/videocreator/trends/scan_job.py` (uncommitted), `src/videocreator/trends/suggest.py`, `src/videocreator/config.py` (`auto_analyse_top_n = 3`), `src/videocreator/web/templates/settings.html` (nếu có ô nhập số này, cập nhật chữ gợi ý), `docs/video-creator-spec.md`
- Test: mở rộng `tests/test_jobs.py`, `tests/test_trend_auto_analysis.py`, `tests/test_db.py` (migration 012 áp được trên DB cũ)

## Implementation Steps

1. Viết migration 012; chạy `db.migrate` trên DB tạm có sẵn dòng `jobs` cũ → cột `priority = 0`.
2. `enqueue_job` thêm `priority`; hằng số và `USER_FACING_KINDS` như trên. Rà mọi chỗ gọi `enqueue_job` (grep) để chắc không chỗ nào truyền tham số vị trí thứ 4.
3. `claim_next_queued_job` đổi ORDER BY.
4. `enqueue_trend_analysis` gán `PRIORITY_PINNED` cho pinned.
5. `make_suggestions(trend_item_ids=...)`, `maybe_make_suggestions`, `other_analyse_jobs_active` (SQL: `kind='analyse_trend' AND status IN ('queued','running','waiting_quota') AND id != ?`).
6. Sửa `run_analyse_trend_job` và `scan_job.py` như Architecture.
7. `auto_analyse_top_n = 3`; sửa comment.
8. Test `test_jobs.py`: xếp 3 việc `analyse_trend` rồi 1 việc `render` → `claim_next_queued_job` trả `render`; hai việc cùng ưu tiên → id nhỏ trước; pinned (5) trước việc nền (0), sau `render` (10).
9. Test `test_trend_auto_analysis.py` (dùng `tests/_trend_helpers.py` sẵn có, writer provider tiêm vào chạy mã thật như test hiện tại): 3 item nền, gọi helper sau item 1 và 2 khi còn việc khác → không đề xuất; sau item cuối → gọi một lần. Item cuối lỗi → vẫn gọi. Item pinned → đề xuất ngay, tối đa 1.
10. Đặc tả: ghi luật ưu tiên hàng đợi (mục §6 hoặc `FR-TRD-07`) và "đề xuất sinh một lần cuối lô; link dán tay sinh ngay".
11. Suite xanh; commit `feat(jobs): prioritise user-facing jobs and batch trend suggestions`.

## Todo list

- [ ] Migration 012 + test migrate trên DB cũ
- [ ] `enqueue_job(priority=)` + ORDER BY mới
- [ ] Pinned = ưu tiên 5
- [ ] `make_suggestions(trend_item_ids=)` + `maybe_make_suggestions`
- [ ] Sửa `run_analyse_trend_job`, `scan_job`
- [ ] `auto_analyse_top_n = 3`
- [ ] Test ưu tiên + test đề xuất theo lô
- [ ] Đặc tả, suite xanh, commit

## Success Criteria

- Có 10 việc `analyse_trend` đang xếp hàng, bấm "Tạo 1 video" → việc `plan` chạy ngay sau việc đang chạy hiện tại.
- Một lần quét chỉ sinh đề xuất một lần, cho video điểm cao nhất; link dán tay có đề xuất ngay.

## Risk Assessment

- Việc nền có thể bị đói nếu người dùng liên tục tạo video: chấp nhận (người dùng là ưu tiên; việc nền không gấp).
- Việc đang chạy 30 phút vẫn chặn: giảm `top_n`; tách worker thứ hai là ngoài phạm vi (YAGNI).
- `job_handlers.py`, `links.py`, `scan_job.py` đang có thay đổi chưa commit: đọc bản hiện tại, sửa tối thiểu, không revert.

## Security Considerations

- Không thay đổi quyền; migration chỉ thêm cột. Ghi audit như cũ.

## Next steps

- Độc lập. Sau khi chạy thật một ngày, xem `jobs` để chỉnh `top_n` nếu cần.
