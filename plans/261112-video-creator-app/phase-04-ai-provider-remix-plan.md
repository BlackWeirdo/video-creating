# Phase 04: AI provider + kịch bản remix + trần ngân sách

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 03](phase-03-footage-import-shot-library.md); kết quả S7 của [phase 01](phase-01-verification-spikes.md)
- Docs: [research 02 mục 2](research/researcher-02-video-pipeline-and-packaging.md)

## Overview

- Ngày: 2026-11-12
- Mô tả: interface `AIProvider` + adapter Gemini và Claude (chọn trong Settings); mô tả/tag shot; sinh N kịch bản remix khác nhau cho 1 footage, lưu vào `videos` (status `planned`); đếm chi phí và chặn khi vượt trần ngày.
- Ưu tiên: P0
- Trạng thái triển khai: hoàn thành (2026-11-13)
- Trạng thái review: đã kiểm thử (`pytest -m local`)

## Key Insights

- Model ID và giá chưa xác nhận -> đọc từ `config.toml` (điền theo S7), không hard-code.
- Structured output chưa xác nhận -> luôn validate bằng Pydantic; sai schema thì gọi lại 1 lần rồi fail job.
- Mô tả shot: gửi 1 lần cả footage kèm danh sách mốc shot rẻ hơn gửi từng shot (1 phút ~ 8k token ở độ phân giải thấp). Nếu S7 chọn nhánh lùi: gửi thumbnail.
- LLM chỉ được chọn `shot_id` có thật; mọi id lạ bị loại khi validate (chống bịa).
- Cận cảnh sản phẩm luôn là footage thật; kịch bản không được yêu cầu cảnh không có trong kho.
- Độ chính xác sản phẩm (yêu cầu người dùng 2026-11-12), phần của phase này:
  - Hình: AI chỉ CHỌN và SẮP XẾP shot (trả `shot_id` + mốc thời gian). AI không tạo, không sửa điểm ảnh nào của sản phẩm.
  - Lời: prompt writer chỉ được dùng thông tin sản phẩm từ `products.facts_json` của các sản phẩm gắn với shot đã chọn; cấm tự thêm chất liệu, tuổi bạc, loại đá, giá, công dụng. Không có sự thật thì viết cảm xúc/quy trình, không viết thông số.
  - Khớp hình và lời: mỗi kịch bản khai `product_ids`; validate từ chối kịch bản mà dòng lời nhắc sản phẩm A đặt trên shot chỉ có sản phẩm B, hoặc trộn shot của nhiều sản phẩm khi `formula` không phải dạng bộ sưu tập.
  - Kiểm tra sau khi viết: 1 lời gọi rẻ (vai trò `checker` trong `[ai.routes]`; với provider API dùng model rẻ: `claude-haiku-5-5` hoặc model flash của Gemini) đối chiếu lời + 4 caption với `facts_json`, trả danh sách câu không có căn cứ; có câu nào thì đánh dấu đỏ trên màn hình duyệt và trong tin Telegram. Không tự sửa, người duyệt quyết.
  - Công thức học từ xu hướng (phase 13) chỉ mang cấu trúc (hook, nhịp, thứ tự cảnh), không mang hình hay lời của video gốc.
- Nhiều lựa chọn model (chốt 2026-11-12, brainstorm mục 3.5.1): cấu hình theo VAI TRÒ trong `[ai.routes]`: `vision` (mô tả shot), `writer` (kịch bản, caption), `checker` (đối chiếu lời). Mỗi vai trò là 1 danh sách provider theo thứ tự ưu tiên; ở phase này danh sách chỉ có provider API (`gemini_api`, `claude_api`), phase 18 thêm provider CLI lên đầu. Đây là cách cấu hình DUY NHẤT (không có khoá `ai.vision`/`ai.writer` riêng).
- Claude API chỉ nhận ảnh (JPEG/PNG/GIF/WebP, tối đa 600 ảnh/request), không nhận file video (đã kiểm tra docs vision 2026-11-12). `describe_video` của adapter Claude gửi thumbnail từng shot (đã có từ phase 03) thay cho file video; không có âm thanh.
- Model Claude: mặc định `claude-opus-5-5` (4/20 USD mỗi triệu token vào/ra); lựa chọn rẻ hơn `claude-sonnet-5-5` (2/10), `claude-haiku-5-5` (0.10/0.50). ID và giá để trong `config.toml`.
- Trước khi viết `ai/claude.py`: nạp skill `claude-api` và đọc `python/claude-api/README.md`; không đoán cách gọi SDK. Dùng SDK `anthropic` chính thức, structured outputs (`client.messages.parse` / `output_config.format`), không prefill, không `temperature`, không ép `tool_choice`; kiểm tra `stop_reason` (có thể là `refusal`) trước khi đọc nội dung.
- GPT: cùng interface, CHỈ thêm `ai/openai.py` khi người dùng yêu cầu (YAGNI).
- Ưu tiên gói thuê bao (chốt 2026-11-13): phase này chỉ làm interface + 2 adapter API (`gemini_api`, `claude_api`) + budget. [Phase 18](phase-18-subscription-first-routing.md), làm ngay sau, thêm adapter CLI chạy bằng gói thuê bao và bộ định tuyến đặt CLI lên trước; từ đó API chỉ là dự phòng. Viết `get_provider(role)` sao cho phase 18 thay ruột được mà nơi gọi không đổi.

## Requirements

- Interface đúng 2 hàm, không hơn:

```python
class AIProvider(Protocol):
    name: str
    def describe_video(self, video: Path, prompt: str, schema: type[BaseModel]) -> BaseModel: ...
    def generate_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel: ...
```

- Kịch bản (`videos.plan_json`):

```json
{"formula": "hook-first", "title": "...", "voice_lang": "none|vi|en",
 "shots": [{"shot_id": 12, "start_s": 0.4, "duration_s": 2.5, "text": "dòng phụ đề/lời"}],
 "caption_lang": "vi|en",
 "captions": {"facebook": {"text": "...", "hashtags": ["..."]}, "instagram": {...}, "threads": {...}, "tiktok": {...}}}
```

- UI: nút "Tạo N kịch bản" trên footage, chọn ngôn ngữ lời (không/Việt/Anh), ngôn ngữ caption (Việt/Anh, mặc định theo ngôn ngữ lời) và thời lượng mục tiêu (15–30 giây); xem và sửa text/caption trước khi render.
- Caption riêng từng nền tảng (chốt 2026-11-12): 1 lời gọi writer trả về cả 4 caption cùng lúc (không gọi 4 lần). Quy tắc độ dài/hashtag từng nền tảng để trong prompt, giới hạn ký tự chính thức tra ở bước đọc docs của phase 07 và 11; validate cắt theo giới hạn.
- Đa dạng: mỗi kịch bản 1 `formula` khác nhau (ví dụ hook-first, quy trình chế tác, cận chi tiết); loại bản có tập shot trùng > 70% (Jaccard) với bản đã có của cùng footage.
- Ngân sách: trước MỖI lần gọi AI, kiểm tra tổng `ai_usage.cost_usd` hôm nay < `budget.daily_usd` (mặc định 5 USD, chốt 2026-11-12). Vượt -> `BudgetExceeded`, job `failed` với lý do rõ.

## Architecture

```
ai/base.py      # Protocol + BudgetExceeded
ai/gemini.py    # google-genai: Files API upload, poll PROCESSING, generate_content, đọc usage_metadata
ai/claude.py    # anthropic SDK: describe_video = thumbnail từng shot dạng image block; generate_json = structured output; đọc usage
ai/budget.py    # check() trước gọi, record() sau gọi; giá lấy từ config [prices.<model>]
ai/__init__.py  # get_provider(role) với role = "vision" | "writer", theo config [ai]
pipeline/describe.py  # job describe: footage -> description/tags/has_product/quality cho từng shot
pipeline/planner.py   # job plan: shots -> N plan, validate, dedupe, insert videos
api/routes_videos.py  # POST /footage/{id}/plans, GET/PUT /videos/{id}
```

Luồng: `analyse` xong -> tự enqueue `describe` -> người dùng bấm tạo kịch bản -> job `plan` -> N dòng `videos` trạng thái `planned`.

## Related code files

Tạo: các file trên; `web/templates/video_plan.html`; `tests/test_budget.py` (local), `tests/test_gemini_live.py`, `tests/test_planner_live.py` (live).
Sửa: `app.py` (router, handler), `config.py` (model, giá, trần), `web/templates/footage.html` (nút tạo kịch bản).

## Implementation Steps

1. `uv add google-genai`. `ai/base.py`, `ai/budget.py` (cost = units x giá trong config).
2. `ai/gemini.py`: 2 hàm interface; bọc mọi lời gọi bằng `budget.check()`/`record()`; retry 2 lần cho lỗi 429/5xx.
2b. `uv add anthropic`. `ai/claude.py` theo skill `claude-api`: 2 hàm interface, cùng lớp bọc budget/retry. Settings: trang định tuyến tối thiểu (thứ tự provider cho từng vai trò, model của từng provider), kèm ô nhập key.
3. `pipeline/describe.py`: dùng `get_provider("vision")`; `pipeline/planner.py` dùng `get_provider("writer")`. Prompt describe trả mảng {idx, description, tags, has_product, quality 1–5}; cập nhật `shots`.
4. `pipeline/planner.py`: prompt gồm danh sách shot (id, thời lượng, mô tả), formula, thời lượng mục tiêu, ngôn ngữ; validate: shot_id tồn tại, `start_s + duration_s` nằm trong shot, tổng thời lượng trong khoảng; dedupe.
5. Route + template xem/sửa kịch bản.
6. Hiện chi phí hôm nay / trần trên trang chủ.
7. Test: `-m local` cho budget (ghi usage thật vào SQLite, vượt trần thì raise); `-m live` gọi Gemini thật trên clip mẫu: describe trả đủ số shot, plan chỉ chứa shot_id hợp lệ, `ai_usage` có dòng mới với cost > 0.

## Todo list

- [x] Interface + budget (`ai/base.py`, `ai/budget.py`)
- [x] Adapter Gemini (`ai/gemini.py`)
- [x] Adapter Claude + 2 ô chọn vision/writer trong Settings (`ai/claude.py`, `settings.html`)
- [x] Job describe (`pipeline/describe.py`)
- [x] Job plan + validate + dedupe (`pipeline/planner.py`, Jaccard <= 70%)
- [x] Luật sản phẩm: lời chỉ từ `facts_json`, khớp hình và lời (`BR-PRD-05`), bước đối chiếu câu không căn cứ (`BR-PRD-06`)
- [x] 4 caption riêng từng nền tảng trong 1 lời gọi (`BR-CAP-01`)
- [x] UI tạo/sửa kịch bản (`routes_videos.py`, `video_plan.html`)
- [x] Hiện chi phí ngày (`app.py`, `index.html`)
- [x] Test local + live (`test_budget.py`, `test_router.py`, `test_cli_live.py`)

## Success Criteria

- Từ 1 footage thật: bấm 1 nút ra >= 3 kịch bản khác formula, không trùng tập shot, đọc thấy hợp lý.
- Đặt `budget.daily_usd = 0.01` -> lần gọi kế tiếp bị chặn với thông báo rõ, không gọi API.
- `ai_usage` khớp với số token provider trả về.
- Đổi provider đứng đầu của vai trò `writer` giữa Gemini và Claude trong Settings, không sửa code: cả hai đều ra kịch bản hợp lệ (test `-m live` chạy cho từng provider có key).
- Đặt Claude đứng đầu vai trò `vision`: describe chạy được bằng thumbnail, trả đủ số shot.

## Risk Assessment

- Kịch bản na ná nhau khi footage ít shot (< 6): báo người dùng "footage quá ít shot cho N bản" thay vì ép ra bản trùng.
- Giá trong config sai -> trần ngân sách lệch. Giảm thiểu: lưu cả token thô để tính lại; đối chiếu hoá đơn Google sau tuần 1.
- Test live tốn tiền thật (vài cent mỗi lần): chỉ chạy khi gọi `-m live`.

## Security Considerations

- API key đọc từ secrets store, không vào log/prompt.
- Footage gửi lên Gemini: dùng key trả phí (free tier có thể dùng dữ liệu để cải thiện sản phẩm). Ghi chú trong Settings.
- Text do LLM sinh được escape khi render HTML.

## Next steps

- Phase 05 render `videos.planned` thành file mp4.
