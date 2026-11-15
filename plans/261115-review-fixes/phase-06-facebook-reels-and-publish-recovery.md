# Phase 06: Facebook Reels + khôi phục bài đang đăng (F6)

## Context links

- [plan.md](plan.md), [scout F6](scout/scout-01-code-locations.md), [research 01 §1–3](research/researcher-01-meta-reels-and-metrics.md)
- Đặc tả: `FR-PST-07`, `FR-PST-08`, `FR-PST-09`, `FR-PST-12`, §6 (khởi động lại: bài `publishing` có mã container thì hỏi nền tảng), `NFR-REL-01` (không đăng trùng)
- Phụ thuộc ngoài: token Meta Page (spike S2/S3 chưa làm) cho phần test live.

## Overview

- Ngày: 2026-11-15. Ưu tiên: cao về rủi ro (đăng trùng), nhưng chưa đăng thật nên làm cuối. Trạng thái: mã xong, test local đạt (máy chủ HTTP giả lập theo tài liệu Meta); chờ test live với token Page. Review: đã review, đã sửa.
- Facebook đang đăng bằng `POST /{page_id}/videos` (video thường, không phải Reels); hết thời gian chờ 120 s → `TransientPostError` → thử lại → có thể đăng 2 lần.
- `recover_interrupted_jobs` bỏ quên bài `publishing` đã có mã container (kẹt mãi). Instagram/Threads khi thử lại mà container đã `PUBLISHED` vẫn gọi publish lần nữa.

## Key Insights

- Reels 3 bước (research 01): `POST /{page_id}/video_reels upload_phase=start` → `video_id`; `POST https://rupload.facebook.com/video-upload/{video_id}` header `file_url` (URL R2 public), `offset: 0`, `file_size`; `POST /{page_id}/video_reels upload_phase=finish video_state=PUBLISHED description=...`. Trạng thái: `GET /{video_id}?fields=status` → `video_status`, `uploading_phase`, `processing_phase`, `publishing_phase.publish_status`.
- Không có khoá chống trùng của Meta → tự làm: lưu `video_id` vào `posts.remote_container_id` NGAY sau `start`; lần sau hỏi trạng thái trước, không gọi `start` lại.
- Instagram (`instagram.py:58-77`) và Threads (`threads.py:54-98`) đã lưu container; nhưng khi container `PUBLISHED` vẫn gọi `media_publish`/`threads_publish` → cần nhánh "đã đăng rồi, tìm mã bài".
- Bài trễ > 6 giờ bị đánh `missed` (`publish.py:69,108`). Bài đã có container nghĩa là đã bắt đầu đăng trước hạn → không được coi là lỡ lịch.
- Kiểu link bài Reel và việc gửi lại `finish` cho video đã đăng CHƯA kiểm chứng (research 01 câu 1, 2).
- Không gọi được Meta trong test local (không mock) → logic quyết định viết thành hàm thuần; HTTP thật chỉ chạy ở `tests/test_meta_live.py`.

## Requirements

- Facebook đăng dạng Reel qua 3 bước, `external_post_id = video_id`.
- `video_id` được lưu trước khi tải lên; mọi lần thử lại đọc trạng thái trước: đã đăng → trả `posted`; tải lên xong chưa `finish` → chỉ gọi `finish`; tải lên lỗi/hết hạn → xoá mã, bắt đầu lại; đang xử lý → `TransientPostError` (thử lại theo `FR-PST-08`).
- Instagram/Threads: container `PUBLISHED` → không publish lại; tìm mã bài trong danh sách bài gần nhất (khớp caption, thời điểm sau lúc tạo container); không tìm được → chuyển `needs_user_action` với tin "Có thể đã đăng, kiểm tra rồi bấm Đã đăng".
- Khởi động lại: bài `publishing` có container → về `scheduled` (giữ container) và được xử lý ngay ở vòng đăng kế tiếp, không bị đánh `missed`.

## Architecture

- `posting/facebook.py`:

```python
RUPLOAD_BASE = "https://rupload.facebook.com/video-upload"

def reel_next_step(status: dict) -> Literal["done", "finish", "upload", "restart", "wait"]:
    # pure: publishing_phase.publish_status == "published" -> done
    #       video_status in ("error","expired","upload_failed") -> restart
    #       uploading_phase.status == "completed"/"complete" and publish not started -> finish
    #       uploading_phase not_started -> upload ; else -> wait

def publish(...):
    video_id = post.remote_container_id or self._start(page_id, token, post_id)   # persists id
    step = reel_next_step(self._status(video_id, token))
    if step == "restart": clear id; video_id = self._start(...); step = "upload"
    if step == "upload":  self._upload(video_id, token, video_url, video_path.stat().st_size); step = "finish"
    if step == "finish":  self._finish(page_id, token, video_id, caption)   # RequestError -> Transient; next retry re-reads status
    if step == "wait":    raise TransientPostError("reel still processing")
    return PostResult("posted", external_post_id=video_id, permalink=self._permalink(video_id, token))
```

  - `_permalink`: thử `GET /{video_id}?fields=permalink_url`; lỗi/ thiếu → `https://www.facebook.com/reel/{video_id}` (cần kiểm chứng live).
  - Dùng `GRAPH_BASE_URL`, `classify_meta_error`, `graph_request` sẵn có (DRY). Kiểm tra phiên bản Graph trong `GRAPH_BASE_URL` có hỗ trợ `video_reels`.
- `posting/meta_published.py` (mới, nhỏ, dùng chung IG + Threads): `find_recent_post(items, caption, not_before_iso) -> dict | None` (hàm thuần) + hai hàm gọi `GET /{ig_id}/media?fields=id,caption,timestamp,permalink&limit=10` và `GET /{user_id}/threads?fields=id,text,timestamp,permalink&limit=10`.
- `instagram.py`/`threads.py`: nếu trạng thái container là `PUBLISHED` → `find_recent_post`; thấy → `posted`; không → `PostResult(status="needs_user_action", ...)`.
- `job_store.recover_interrupted_jobs`: thêm `UPDATE posts SET status='scheduled' WHERE status='publishing' AND remote_container_id <> ''` (giữ container). Ghi log số bài.
- `posting/publish.py`: bỏ qua kiểm tra `missed` khi `remote_container_id` khác rỗng.
- `publish_outcomes.notify_published` nhánh `needs_user_action`: chữ khác cho Meta ("Có thể đã đăng …") so với TikTok (hộp nháp + caption từ phase 01).

## Related code files

- Tạo: `src/videocreator/posting/meta_published.py`
- Sửa: `src/videocreator/posting/facebook.py`, `src/videocreator/posting/instagram.py`, `src/videocreator/posting/threads.py`, `src/videocreator/job_store.py`, `src/videocreator/posting/publish.py`, `src/videocreator/posting/publish_outcomes.py`, `docs/video-creator-spec.md` (`FR-PST-07` thêm Facebook Reels; §6 cách khôi phục)
- Test: mở rộng `tests/test_posting_service.py`, `tests/test_jobs.py`; mở rộng live `tests/test_meta_live.py` (skip khi thiếu token)

## Implementation Steps

1. `reel_next_step` + test thuần với các dạng `status` lấy NGUYÊN VĂN từ tài liệu Meta (ghi nguồn trong test; thay bằng phản hồi thật ghi lại sau lần chạy live đầu tiên).
2. `_start` (lưu `remote_container_id` trong cùng hàm, như `instagram._create_container`), `_status`, `_upload`, `_finish`, `_permalink`; viết lại `publish` theo sơ đồ.
3. `find_recent_post` + test thuần (khớp caption sau khi `strip`, bỏ bài cũ hơn `not_before`).
4. Nhánh `PUBLISHED` trong Instagram/Threads.
5. `recover_interrupted_jobs` + `publish.py` bỏ qua `missed`. Test SQLite thật (`test_jobs.py`): bài `publishing` có container → `scheduled`, container giữ nguyên; không container → `scheduled` như cũ. Test `publish.py`: bài trễ 7 giờ có container không bị đánh `missed` (dùng `now_dt` cố định, poster tiêm vào là lớp thật trả `PostResult` — như các test posting hiện có).
6. Live (`test_meta_live.py`, đánh dấu `live`, skip nếu thiếu `META_PAGE_TOKEN`/ page id): đăng 1 Reel thật từ clip mẫu qua URL R2 thật; gọi `publish` lần hai với cùng post → không tạo Reel thứ hai (đếm `GET /{page_id}/video_reels`); in permalink để người kiểm tra mở. Ghi kết quả vào `plans/261115-review-fixes/reports/`.
7. Đặc tả cập nhật.
8. Suite xanh; commit `feat(facebook): publish as reels with status-first retry and recover in-flight posts`.

## Todo list

- [ ] `reel_next_step` + test thuần
- [ ] Facebook Reels 3 bước, lưu `video_id` sau `start`
- [ ] IG/Threads: container `PUBLISHED` → tìm bài, không publish lại
- [ ] Khôi phục bài `publishing` có container + bỏ qua `missed`
- [ ] Test SQLite thật cho khôi phục
- [ ] Test live (chờ token S2/S3)
- [ ] Đặc tả, suite xanh, commit

## Success Criteria

- Local: suite xanh; bài có container sau khởi động lại được xử lý, không kẹt, không bị đánh lỡ lịch.
- Live (khi có token): một Reel thật; gọi lại `publish` không tạo bài trùng; permalink mở được.

## Risk Assessment

- Hành vi Meta chưa kiểm chứng (permalink, gửi lại `finish`, R2 với user agent `facebookexternalhit`): chỉ chốt sau test live; trước đó trạng thái phase là "viết mã xong, chờ live".
- Lấy số liệu Reel qua `GET /{video_id}?fields=views,...` có thể khác video thường → phase 01 (F7) đã làm lỗi được thử lại thay vì ghi rỗng; tên chỉ số Reels để việc sau (research 01 §4, YAGNI).
- Giới hạn 30 Reel/24 giờ mỗi Page: lượng đăng hiện tại thấp hơn nhiều → không làm bộ đếm (YAGNI), ghi chú trong đặc tả.
- Video không đạt chuẩn Reels (3–90 s, 9:16, 24–60 fps, AAC 48 kHz) đã được preflight `facebook` chặn; kiểm tra `platform_limits["facebook"]` khớp (min 3 s, max 90 s).

## Security Considerations

- Token Page chỉ đọc từ kho bí mật, gửi qua header `Authorization`; không ghi vào log/ tin lỗi (`NFR-SEC-01`). Lỗi trả về từ Meta có thể chứa URL — lọc như `classify_meta_error` đang làm.
- URL R2 public chỉ tồn tại tới khi dọn theo `FR-PST-05`.

## Next steps

- Cần S2/S3 (token Page + quyền `pages_manage_posts`, `pages_read_engagement`) để chạy bước 6.
- Sau live: cập nhật permalink và test bằng phản hồi thật.
