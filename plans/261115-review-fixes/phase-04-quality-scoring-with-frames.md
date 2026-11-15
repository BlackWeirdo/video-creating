# Phase 04: Chấm điểm tự động bằng nhiều khung hình (F2)

## Context links

- [plan.md](plan.md), [scout F2](scout/scout-01-code-locations.md), [research 02](research/researcher-02-ai-video-scoring.md)
- Đặc tả: `FR-APR-05`, `FR-APR-06`, `FR-AI-07`, §6 (trạng thái video)
- Cần [phase 03](phase-03-planner-trend-analysis-and-shot-focus.md) xong trước.

## Overview

- Ngày: 2026-11-15. Ưu tiên: cao (chấm sai → tự làm lại 2 lần, tốn thời gian + lượt AI, có thể đưa bản kém hơn đi duyệt). Trạng thái: xong, test local đạt. Review: đã review (code-reviewer), đã sửa các điểm cao và trung bình.
- Hiện tại với Claude, mô hình chỉ thấy MỘT khung giữa video; điểm < 8 → lập kịch bản + dựng lại tối đa 2 lần; bản cuối được gửi duyệt dù kém hơn bản trước; lần làm lại không biết vì sao bị điểm thấp.

## Key Insights

- `quality_score.py:67-71` gọi `vis.describe_video(video, prompt, VideoQualityScore)` không truyền `thumbnails`; `ai/claude_cli._stage_thumbnails` và `ai/claude.py:141-146` khi không có ảnh thì lấy 1 khung giữa. Gemini (`ai/gemini.py`) tải cả video, bỏ qua ảnh.
- `pipeline/thumbs.extract_thumbnail(video, t, dest)` đã có, không cần thêm filter FFmpeg (whitelist `ffmpeg.py:13-36` không có `select`/`tile`/`drawtext`). Mỗi khung ~0.2 s.
- Research 02: khung 0.3 s, 1.3 s, 2.3 s cho mở đầu (tránh khung đen đầu) + 1 khung mỗi shot; 8–12 ảnh; thang có mốc neo cho từng tiêu chí; bằng chứng (thời điểm + thấy gì) trước điểm; điểm dao động ±1 → giữ bản TỐT NHẤT, đưa gợi ý sửa cụ thể vào lần làm lại.
- Khi `output_path` thiếu, mã hiện truyền `paths.media_dir` (thư mục!) cho provider → điểm vô nghĩa nhưng vẫn có thể kích hoạt làm lại.
- Trạng thái `superseded` là trạng thái cuối (`state.py:33`) → giữ bản tốt nhất cần một chuyển trạng thái mới (câu hỏi số 4 trong plan.md).
- `redo_video` tạo dòng mới với `supersedes_id`; `replan` (đã sửa ở phase 03) đọc được dòng cha.

## Requirements

- Gửi cho provider 8–12 khung: 0.3 / 1.3 / 2.3 s + điểm giữa mỗi shot theo `plan_json`, bỏ khung trùng cách nhau < 0.5 s, tối đa 12. Prompt liệt kê "Ảnh 1 = 0.3 s (mở đầu) …".
- Lược đồ mới: mỗi tiêu chí có `evidence` (thời điểm + thấy gì) rồi `score` 1–10; có `can_judge` + `cannot_judge_reason`. Điểm tổng tính trong mã = trung bình 4 tiêu chí (không lấy điểm tổng do mô hình tự cho).
- Thang neo trong prompt cho từng tiêu chí (mốc 2 / 5 / 8 / 10).
- KHÔNG tự làm lại khi không chấm được thật: file video thiếu, trích được < 3 khung, `can_judge = false`, hoặc provider lỗi. Khi đó gửi duyệt với ghi chú "Chưa chấm được: <lý do>", `quality_score` để NULL.
- Hết lượt làm lại: so điểm các bản trong chuỗi (`supersedes_id`), gửi duyệt bản điểm CAO NHẤT; các bản khác `superseded`.
- Lần làm lại nhận gợi ý: tiêu chí thấp nhất + bằng chứng (vd "Mở đầu 5/10: 0–2 s chưa thấy sản phẩm").

## Architecture

```python
class CriterionScore(BaseModel):
    evidence: str = Field(description="Thời điểm (giây) + điều thấy được trong ảnh")
    score: int = Field(ge=1, le=10)

class VideoQualityScore(BaseModel):
    can_judge: bool
    cannot_judge_reason: str = ""
    hook: CriterionScore
    product_clarity: CriterionScore
    text_safe_zone: CriterionScore
    pacing_sync: CriterionScore
    notes: str
```

- `pipeline/quality_frames.py` (mới, nhỏ): `frame_times(plan: dict, duration_s: float) -> list[float]` (hàm thuần) và `extract_score_frames(video, times, work_dir) -> list[Path]` (gọi `extract_thumbnail`).
- `quality_score.score_rendered_video`:

```
if not video_file.exists(): -> unjudged("không tìm thấy file video")
frames = extract_score_frames(...);  if len(frames) < 3: -> unjudged(...)
res = vis.describe_video(video_file, prompt, VideoQualityScore, thumbnails=frames)   # except Exception -> unjudged
if not res.can_judge: -> unjudged(res.cannot_judge_reason)
score = mean(4 criteria); hint = weakest criterion + evidence
save score + notes (notes = hint + model notes)
if score < min_score and retries left: redo_video(...)  # unchanged
else: best = best_in_chain(video_id); if best != video_id: promote(best), supersede(current)
```

- `state.py`: thêm `"superseded": {"pending_approval"}` — chỉ dùng trong `promote_best_attempt` với `expected_from="superseded"`, actor `auto_quality`, ghi audit `video.best_attempt_restored`.
- `replan.replan_video`: nếu `supersedes_id` có và dòng cha có `quality_notes` → truyền `fix_hint` vào `create_remix_plans` → `build_planner_prompt(fix_hint=...)` thêm khối "LẦN DỰNG TRƯỚC BỊ CHẤM THẤP VÌ: … Hãy sửa đúng điểm này."
- Prompt chấm điểm không nhét `plan_json[:1200]` nữa; thay bằng danh sách shot ngắn (thời điểm + lời) — đủ để mô hình so lời với hình.
- Provider Gemini nhận cả video (bỏ qua `thumbnails`) — không đổi.

## Related code files

- Tạo: `src/videocreator/pipeline/quality_frames.py`
- Sửa: `src/videocreator/pipeline/quality_score.py`, `src/videocreator/state.py`, `src/videocreator/pipeline/replan.py`, `src/videocreator/pipeline/planner.py`, `src/videocreator/pipeline/plan_prompts.py`, nơi gọi `score_rendered_video` (đọc `job_handlers.py`, kiểm tra nó gửi duyệt cho `active_video_id` được trả về), `docs/video-creator-spec.md` (`FR-APR-05`, §6)
- Kiểm tra (không chắc phải sửa): `src/videocreator/ai/claude_cli.py`, `src/videocreator/ai/claude.py` (thứ tự ảnh giữ đúng thứ tự truyền vào); mã dọn đĩa không xoá `output_path` của video `superseded` trong lúc chuỗi chấm điểm đang chạy; tin duyệt Telegram hiển thị được `quality_score = NULL`.
- Test: mở rộng `tests/test_render.py` (hoặc tạo `tests/test_quality_score.py`), `tests/test_state.py`

## Implementation Steps

1. `frame_times`: test thuần — plan 3 shot (4 s, 5 s, 6 s) → `[0.3, 1.3, 2.3, 6.5, 12.0]` (0–4 có giữa 2.0 trùng gần 2.3 → bỏ); tối đa 12; video < 2.3 s không vượt độ dài.
2. `extract_score_frames` với FFmpeg thật trên clip trong `tests/samples/` → đúng số file JPG.
3. Lược đồ + prompt neo (viết tiếng Việt, mỗi tiêu chí 4 mốc). Hàm thuần `overall_from(res)` và `weakest_hint(res)`.
4. Nhánh "không chấm được" + test: video không tồn tại → không gọi provider, không làm lại, trạng thái `pending_approval`, `quality_score` NULL, ghi chú có lý do.
5. `state.py` thêm chuyển trạng thái; `best_in_chain` (đi theo `supersedes_id`, lấy bản có `quality_score` cao nhất và file còn tồn tại); `promote_best_attempt`. Test SQLite thật: chuỗi 3 bản điểm 7.5 → 6.0 → 7.0, hết lượt → bản 7.5 về `pending_approval`, hai bản kia `superseded`, có audit.
6. Provider tiêm vào cho test: lớp thật hiện thực `AIProvider.describe_video` trả `VideoQualityScore` cố định theo số lần gọi (giống cách các test hiện tại tiêm provider) — chạy toàn bộ mã thật của `score_rendered_video`, `redo_video`, SQLite.
7. `replan`: đọc dòng cha, truyền `fix_hint`; test prompt writer chứa gợi ý.
8. (Tuỳ chọn, `live`) `tests/test_cli_live.py`: chấm video mẫu thật bằng `claude_cli` với khung hình; skip khi không có CLI.
9. Đặc tả: `FR-APR-05` ghi "chấm bằng nhiều khung hình hoặc cả video; không chấm được thì không tự làm lại; hết lượt thì gửi bản điểm cao nhất"; §6 thêm `superseded → pending_approval` (chỉ chấm điểm tự động).
10. Suite xanh; commit `feat(quality): score from multiple frames, keep best attempt and pass fix hint to redo`.

## Todo list

- [ ] `quality_frames.py` + test thuần + test FFmpeg thật
- [ ] Lược đồ có bằng chứng + thang neo + điểm tổng trong mã
- [ ] Nhánh "không chấm được" (không làm lại)
- [ ] Giữ bản tốt nhất + chuyển trạng thái mới + test chuỗi
- [ ] Gợi ý sửa lỗi vào `replan`/prompt
- [ ] Kiểm tra dọn đĩa + tin duyệt với điểm NULL
- [ ] Đặc tả, suite xanh, commit

## Success Criteria

- Với `claude_cli`/`claude_api`, provider nhận 8–12 ảnh có nhãn thời điểm.
- Không bao giờ tự làm lại khi không chấm được.
- Bản gửi duyệt là bản điểm cao nhất của chuỗi.
- Prompt lần làm lại chứa tiêu chí yếu nhất + bằng chứng.

## Risk Assessment

- Chấm điểm bằng LLM vẫn dao động ±1; chưa có bộ 10–20 video chấm tay để hiệu chỉnh (research 02). Giảm rủi ro: giữ bản tốt nhất, giới hạn 2 lần. Đề xuất chủ dự án chấm tay 10 video để so sau khi chạy thật.
- 12 ảnh × ~1.6k token/ảnh qua `claude_api` tốn tiền nếu routing API (lệch đặc tả số 1); qua `claude_cli` thì không tốn tiền.
- Chuyển trạng thái mới mở cửa hồi sinh video `superseded`: giới hạn trong một hàm, `expected_from` kiểm tra có điều kiện, có audit.

## Security Considerations

- Ảnh chỉ đặt trong thư mục tạm riêng của CLI (`FR-AI-03`), xoá sau khi chấm.
- Bằng chứng/ghi chú do AI viết hiển thị trên UI/Telegram phải được thoát ký tự như văn bản ngoài.

## Next steps

- Sau khi chạy thật một tuần: xem phân bố điểm, cân nhắc ngưỡng theo từng tiêu chí (chưa làm, YAGNI).
