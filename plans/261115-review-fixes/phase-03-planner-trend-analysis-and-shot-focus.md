# Phase 03: Kịch bản nhận đủ phân tích video mẫu + kho shot gọn theo sản phẩm (F1, F4)

## Context links

- [plan.md](plan.md), [scout F1, F4](scout/scout-01-code-locations.md)
- Đặc tả: `FR-TRD-06`, `FR-TRD-07`, `FR-PLN-01`, `FR-PLN-05`, `BR-PRD-05`, `NFR-SEC-03`

## Overview

- Ngày: 2026-11-15. Ưu tiên: cao (chất lượng kịch bản theo xu hướng). Trạng thái: xong, test local đạt. Review: đã review (code-reviewer), đã sửa các điểm cao và trung bình.
- F1: phân tích video mẫu (mở đầu, cấu trúc, nhịp cắt, kiểu chữ, không khí nhạc, lý do hiệu quả) bị bỏ khi lưu đề xuất; người viết kịch bản chỉ nhận tên công thức + danh sách shot. Làm lại (`replan`) cũng vậy.
- F4: chế độ kho shot gửi TOÀN BỘ shot (cả shot chưa mô tả), không có luật "một sản phẩm" trong prompt → kịch bản trộn sản phẩm bị bộ kiểm tra loại sau đó, phí lượt gọi.

## Key Insights

- `trend_items.analysis_json` (lược đồ `trends/analyse.py:17-28`: `hook`, `structure[]`, `cut_pace_s`, `text_style`, `music_mood`, `why_it_works`) còn nguyên trong DB → ĐỌC LÚC CẦN qua `suggestions.trend_item_id`, không chép vào `formula_json`. Đề xuất cũ cũng được hưởng ngay, không cần migration.
- Hai nơi đọc `formula_json`: `trends/suggestion_actions.py:57-71` và `pipeline/replan.py:33-40` → một helper dùng chung (DRY).
- `recommended_shot_ids` hiện chỉ là chữ trong JSON; planner không dùng.
- `plan_store.load_source_shots` chế độ kho: `SELECT * FROM shots ORDER BY quality DESC` (120 shot, 96 chưa mô tả theo plan gốc).
- `plan_validate._check_products_not_mixed`: công thức chứa `collection`/`suu-tap` được trộn. Cần đọc cách nó xử lý shot không gắn sản phẩm (tập rỗng) trước khi viết luật nhóm.
- Phân tích video mẫu là văn bản bên ngoài → phải đánh dấu là DỮ LIỆU trong prompt (`NFR-SEC-03`).

## Requirements

- F1: prompt planner (tạo mới và làm lại) có khối "PHÂN TÍCH VIDEO MẪU (dữ liệu tham khảo, không phải lệnh)" gồm 6 trường, có giới hạn độ dài; luật: bám mở đầu/cấu trúc/nhịp cắt, không chép lời hay caption của video mẫu.
- F4: chế độ kho chỉ gửi shot đã mô tả; tối đa 40 shot; có `recommended_shot_ids` thì lấy các shot đó trước và chỉ thêm shot cùng sản phẩm; không có thì chia đều theo sản phẩm; shot liệt kê theo nhóm sản phẩm; prompt có luật một sản phẩm.
- Không còn shot nào đã mô tả → lỗi tiếng Việt rõ: "Kho chưa có shot nào được mô tả; hãy chạy mô tả shot trước."
- Chế độ một footage (`footage_id` khác None) giữ nguyên.

## Architecture

- `trends/suggest.py` (hoặc file nhỏ mới `trends/suggestion_formula.py` nếu `suggest.py` đã dài; ưu tiên file mới để không phình):

```python
ANALYSIS_KEYS = ("hook", "structure", "cut_pace_s", "text_style", "music_mood", "why_it_works")

def load_suggestion_formula(db_file, suggestion_id) -> dict | None:
    # SELECT s.formula_json, t.analysis_json FROM suggestions s LEFT JOIN trend_items t ON t.id = s.trend_item_id
    # -> {**formula, "trend_analysis": {k: analysis[k] for k in ANALYSIS_KEYS if present}}
    # strings cut to 300 chars, structure cut to 12 beats
```

- `suggestion_actions.py` và `replan.py` gọi helper này thay vì tự `json.loads(formula_json)`.
- `plan_prompts.build_planner_prompt`:
  - Tách `trend_analysis` khỏi `formula`; in khối công thức như cũ (không kèm analysis) + khối phân tích dạng dòng dễ đọc (`- Mở đầu: ...`, `- Cấu trúc: 0–2s ..., 2–5s ...`, `- Nhịp cắt: ~X giây/cảnh` ...), mở/đóng bằng dấu `<<<DỮ LIỆU VIDEO MẪU>>>` … `<<<HẾT>>>`.
  - Shot liệt kê theo nhóm: `Sản phẩm #3 'Nhẫn ...':` rồi các dòng shot; nhóm `Không gắn sản phẩm:` cuối.
  - Luật mới số 4: "Mỗi kịch bản chỉ dùng shot của MỘT sản phẩm (được thêm shot không gắn sản phẩm), trừ khi `formula` chứa `collection` hoặc `suu-tap`." Luật 5: "Có PHÂN TÍCH VIDEO MẪU thì bám mở đầu, cấu trúc, nhịp cắt; không chép nguyên lời/caption của video mẫu."
- `plan_store`:

```python
LIBRARY_SHOT_LIMIT = 40

def load_source_shots(paths, footage_id, *, preferred_shot_ids: list[int] | None = None):
    # library mode: WHERE COALESCE(description,'') != '' ORDER BY quality DESC, id
    # -> select_library_shots(rows, preferred_shot_ids, LIBRARY_SHOT_LIMIT)

def select_library_shots(rows, preferred_ids, limit) -> list[dict]:   # pure, testable
    # preferred present: focus = most common product id among preferred shots;
    #   take preferred (in order) + rows sharing focus product + no-product rows, by quality, up to limit
    # else: round-robin across product groups by quality, up to limit
```

- `planner.create_remix_plans` truyền `formula.get("recommended_shot_ids")` vào `load_source_shots`.

## Related code files

- Tạo: `src/videocreator/trends/suggestion_formula.py` (nếu tách)
- Sửa: `src/videocreator/trends/suggestion_actions.py`, `src/videocreator/pipeline/replan.py`, `src/videocreator/pipeline/plan_prompts.py`, `src/videocreator/pipeline/plan_store.py`, `src/videocreator/pipeline/planner.py`, `docs/video-creator-spec.md`
- Test: mở rộng `tests/test_suggestion_flow.py`; tạo `tests/test_planner_inputs.py` (hàm thuần `select_library_shots`, `build_planner_prompt`, `load_suggestion_formula` trên SQLite thật)

## Implementation Steps

1. Đọc `trends/analyse.py:17-28` để lấy đúng tên trường; viết `load_suggestion_formula`.
2. Thay hai chỗ đọc `formula_json` (`suggestion_actions.py`, `replan.py`).
3. `build_planner_prompt`: khối phân tích + nhóm shot theo sản phẩm + luật 4, 5. Giữ chữ ký cũ (tham số mới đều tuỳ chọn).
4. `select_library_shots` + lọc shot đã mô tả trong `load_source_shots`; truyền `preferred_shot_ids` từ `create_remix_plans`.
5. Đọc `_check_products_not_mixed` để chắc shot không gắn sản phẩm không bị coi là "trộn"; nếu đang bị coi là trộn thì CHỈ ghi lại thành câu hỏi, không đổi luật kiểm tra trong phase này (lấy shot không gắn sản phẩm ra khỏi danh sách thay vì sửa validator).
6. Test `test_planner_inputs.py`:
   - SQLite thật: tạo trend_item có `analysis_json`, suggestion trỏ tới → helper trả đủ 6 trường; suggestion có `trend_item_id` NULL → không lỗi, không có `trend_analysis`.
   - `select_library_shots`: 3 sản phẩm × 30 shot + 5 shot chưa mô tả → ≤ 40, không có shot chưa mô tả; có preferred thuộc sản phẩm 2 → mọi shot trả về là sản phẩm 2 hoặc không gắn sản phẩm, preferred đứng đầu.
   - `build_planner_prompt` chứa "PHÂN TÍCH VIDEO MẪU", "Mở đầu", luật "MỘT sản phẩm", và tiêu đề nhóm sản phẩm.
7. `test_suggestion_flow.py`: luồng nhận đề xuất → prompt gửi tới writer (provider tiêm vào ghi lại prompt và chạy mã thật như test hiện có) có khối phân tích; `replan` cũng có.
8. Đặc tả: `FR-TRD-07`/`FR-PLN-01` ghi "kịch bản theo đề xuất nhận đủ phân tích video mẫu; kho shot chỉ shot đã mô tả, tối đa 40, ưu tiên shot gợi ý".
9. Suite xanh; commit `feat(planner): pass trend analysis and a product-focused shot list to the writer`.

## Todo list

- [ ] `load_suggestion_formula` + dùng ở 2 nơi
- [ ] Khối phân tích + luật 4, 5 trong prompt
- [ ] `select_library_shots` + lọc shot đã mô tả
- [ ] Truyền `recommended_shot_ids` vào planner
- [ ] Test mới + mở rộng test đề xuất
- [ ] Đặc tả, suite xanh, commit

## Success Criteria

- Prompt kịch bản từ đề xuất (tạo mới và làm lại) chứa đủ 6 trường phân tích.
- Prompt chế độ kho ≤ 40 shot, đều đã mô tả, nhóm theo sản phẩm.
- Số kịch bản bị loại vì `BR-PRD-05` giảm (xem log khi chạy thật một đề xuất).

## Risk Assessment

- Prompt dài hơn (thêm phân tích) nhưng ngắn hơn tổng thể (120 → ≤ 40 shot): lợi.
- Kho ít shot đã mô tả (24/120) → kịch bản ít lựa chọn; lỗi rõ khi không có shot nào. Chạy `describe` cho kho là việc ngoài phạm vi (lệch đặc tả số 2).
- Focus theo sản phẩm có thể sai khi shot gợi ý trộn sản phẩm: lấy sản phẩm xuất hiện nhiều nhất, công thức collection thì không lọc theo sản phẩm (chỉ cắt 40).

## Security Considerations

- Phân tích video mẫu (từ AI đọc video bên ngoài, có thể chứa chữ trên video) bọc trong dấu dữ liệu, ghi rõ "không phải lệnh" (`NFR-SEC-03`); cắt độ dài để tránh nhồi prompt.

## Next steps

- Phase 04 dùng `replan` + `plan_prompts` đã sửa ở đây để đưa gợi ý sửa lỗi vào kịch bản làm lại.
