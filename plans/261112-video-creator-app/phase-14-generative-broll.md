# Phase 14: B-roll generative + provider thứ hai

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 05](phase-05-ffmpeg-render-core.md), [phase 04](phase-04-ai-provider-remix-plan.md) (budget)
- Docs: [brainstorm mục 3.5](../reports/brainstorm-2026-11-12-video-creator.md)

## Overview

- Ngày: 2026-11-12
- Thứ tự thực hiện: tuần 4, sau phase 17.
- Mô tả: sinh clip phụ (B-roll) bằng AI, đưa vào kho như 1 loại shot, planner được phép chèn tối đa 1–2 cảnh phụ mỗi video. Thêm provider thứ hai sau khi cái đầu chạy ổn.
- Ưu tiên: P3
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Cận cảnh sản phẩm LUÔN là footage thật (AI làm sai hoa văn, đá, độ bóng -> sai lệch sản phẩm khi bán hàng). Ràng buộc này phải nằm trong code, không chỉ trong prompt.
- Giá ~1–3 USD/clip 8 giây (brainstorm, chưa xác nhận) = lớn hơn cả ngân sách remix 1 ngày -> trần riêng cho generative.
- Model/API Veo và Sora hiện hành, giá, định dạng đầu ra: CHƯA research. Bước đầu của phase là tra docs chính thức.
- B-roll sinh 1 lần, dùng lại nhiều video -> lưu vào kho, không sinh theo từng video.
- Nhiều lựa chọn model (chốt 2026-11-12, brainstorm mục 3.5.1): Veo 3 trực tiếp (mặc định), Sora 2 trực tiếp, và 1 adapter cổng model (fal.ai hoặc Replicate, người dùng đã chấp nhận) cho Kling, Runway, Luma, Seedance, Hailuo. Thêm model qua cổng = thêm 1 mục trong `config.toml` (`[videogen.models.<tên>]`: endpoint, giá/giây, có hỗ trợ ảnh đầu vào không), không thêm code.
- Chọn fal.ai hay Replicate: quyết ở bước 1 theo model có sẵn, giá, và hỗ trợ ảnh -> video 9:16. Chỉ làm 1 cổng.
- Nguồn cảnh phụ qua MoneyPrinterTurbo (đã tích hợp ở phase 09), xét ở bước 1: (a) stock Pexels/Pixabay/Coverr: miễn phí, dùng cho cảnh không khí (xưởng, thiên nhiên), nhãn `stock_broll`, cùng luật với `ai_broll` (không bao giờ là cảnh sản phẩm, tối đa 2 cảnh phụ mỗi video, hiện nhãn khi duyệt), đọc điều khoản dùng cho quảng cáo của từng kho; (b) các nhà cung cấp AI video MPT hỗ trợ sẵn (MiniMax, Seedance, WaveSpeed...): nếu đủ dùng thì thay cho adapter cổng model riêng, bớt 1 adapter.
- Ưu tiên gói thuê bao (chốt 2026-11-13): nguồn mặc định là TRẠM VIỆC TAY của [phase 18](phase-18-subscription-first-routing.md): app soạn prompt, người dùng tạo clip trong app thuê bao (Muse/Meta AI, Gemini với Veo, Flow), gửi lại file; không tốn API. Muse Video chưa có API nên Muse chỉ đi đường này. Veo/cổng model qua API chỉ bật khi người dùng muốn tự động hoàn toàn và chấp nhận trả theo clip.
- Người dùng xác nhận (2026-11-13): các model tạo video qua API (Kling, Seedance, Runway, Luma, Hailuo, Veo...) PHẢI có trong phần mềm, dùng khi cần; không phải mục cắt được. Mỗi lần tạo clip, người dùng chọn nguồn: việc tay (gói thuê bao, không tốn API) hoặc 1 model API cụ thể (hiện giá ước tính trước khi bấm). Kling và Seedance là 2 model bắt buộc chạy được qua adapter cổng model (hoặc qua nhà cung cấp của MPT nếu bước 1 cho thấy đủ).
- Thứ tự làm: trạm việc tay (đã có từ phase 18) -> adapter cổng model với Kling + Seedance -> Veo API -> stock qua MPT -> Sora trực tiếp. Chỉ Sora trực tiếp và stock là cắt được. Sora là thứ cắt đầu tiên (đã có qua cổng nếu cổng cung cấp).

## Requirements

- Interface (chỉ tạo ở phase này):

```python
class VideoGenProvider(Protocol):
    name: str
    def generate_clip(self, prompt: str, seconds: int, image: Path | None = None) -> Path: ...  # mp4
```

- UI "Tạo B-roll": nhập prompt (hoặc chọn mẫu: bàn thợ bạc, khói, ánh sáng, bối cảnh thiên nhiên), tuỳ chọn ảnh sản phẩm thật làm khung đầu, chọn provider -> job `generate` -> xem -> Giữ / Xoá.
- Clip giữ lại: 1 dòng `assets` kind `broll` + 1 dòng `shots` với `has_product = 0`, tag `ai_broll`.
- Planner: tối đa 2 shot `ai_broll` mỗi video; không bao giờ là shot đầu (hook) trừ khi người dùng sửa tay; shot `has_product = 1` chỉ lấy từ footage thật (kiểm tra ở bước validate).
- Trần `budget.generative_daily_usd` (mặc định 15 USD, chốt 2026-11-12) tách khỏi trần AI thường; UI hiện giá ước tính trước khi bấm.
- Gắn nhãn nội dung AI khi đăng nếu nền tảng yêu cầu (chính sách từng nền tảng: chưa xác nhận, tra ở bước 1).

## Architecture

```
ai/videogen_base.py   # Protocol
ai/veo.py             # provider 1 (qua google-genai, dùng chung key Gemini): submit -> poll operation -> tải mp4
ai/gateway.py         # provider 2: cổng model (fal.ai hoặc Replicate); 1 adapter, model lấy từ config
ai/sora.py            # provider 3 (trực tiếp, làm sau cùng)
pipeline/broll.py     # job generate: budget.check -> generate_clip -> chuẩn hoá 1080x1920/30fps -> lưu assets + shots
api/routes_broll.py
```

`shots.footage_id` cho phép NULL khi shot đến từ `assets` (migration nhỏ: thêm `shots.asset_id`); render lấy đường dẫn nguồn từ footage hoặc asset.

## Related code files

Tạo: `src/videocreator/ai/videogen_base.py`, `ai/veo.py`, `ai/sora.py` (tuỳ chọn), `pipeline/broll.py`, `api/routes_broll.py`, `migrations/006_shot_asset.sql`, `web/templates/broll.html`, `tests/test_broll_rules.py`, `tests/test_videogen_live.py`.
Sửa: `ai/budget.py` (trần riêng), `pipeline/planner.py` (luật B-roll), `pipeline/render.py` (nguồn shot từ asset), `config.py`.

## Implementation Steps

0. Trạm việc tay theo thiết kế ở [phase 18](phase-18-subscription-first-routing.md) mục Requirements: `manual/tickets.py`, `api/routes_manual.py`, `web/templates/manual.html`, bảng `manual_tickets` trong migration `006_shot_asset.sql`, tin phiếu trong topic "Việc tay", nhận file trả lời (kiểm tra đuôi, ffprobe, dung lượng), nhập thành asset `broll` + shot `ai_broll`, nhắc sau 48 giờ. Test `-m local`: nhận 1 file video mẫu thật -> thành shot `ai_broll`, phiếu đóng; file sai định dạng bị từ chối. Làm trước mọi nguồn API vì đây là nguồn mặc định.
1. Tra docs chính thức: model ID video-gen hiện hành, giá, độ dài, tỉ lệ 9:16, image-to-video, chính sách gắn nhãn AI. Ghi vào `reports/`.
2. `videogen_base.py`, `veo.py`.
3. Trần ngân sách riêng + hiển thị giá ước tính.
4. `broll.py` + migration + UI.
5. Luật planner + render từ asset.
6. Test `-m local`: validate từ chối kịch bản có 3 shot `ai_broll` hoặc B-roll ở vị trí hook; render thật 1 kịch bản trộn shot footage + 1 clip B-roll (dùng 1 clip B-roll thật đã sinh ở bước 7, lưu vào `tests/samples/`).
7. Test `-m live` (TỐN TIỀN THẬT, ~1–3 USD/lần; chỉ chạy khi người dùng đồng ý): sinh 1 clip 5–8 giây, ffprobe hợp lệ, `ai_usage` ghi đúng chi phí.
8. `ai/gateway.py`: lặp bước 2 + 7 với 1 model qua cổng (ưu tiên model làm ảnh -> video tốt). UI chọn model hiện giá ước tính theo `giá/giây x số giây`.
9. So sánh trên ảnh trang sức bạc thật: cùng 1 ảnh + 1 prompt qua Veo và 2 model của cổng; người dùng xem và chọn mặc định. Ghi kết quả vào `reports/`.
10. `ai/sora.py`: lặp bước 2 + 7 (cắt nếu thiếu thời gian).

## Todo list

- [ ] Trạm việc tay (phiếu, Telegram, nhập kho)
- [ ] Tra docs video-gen + chính sách nhãn AI
- [ ] Interface + provider 1
- [ ] Trần ngân sách generative
- [ ] Job generate + UI B-roll
- [ ] Luật planner + render từ asset
- [ ] Test local + live (có phí)
- [ ] Adapter cổng model + chọn model trong UI (bắt buộc: Kling, Seedance)
- [ ] So sánh model trên ảnh trang sức thật, chọn mặc định
- [ ] Sora trực tiếp (cắt được)

## Success Criteria

- Sinh 1 clip B-roll từ UI, giữ lại, thấy nó trong kho shot; kịch bản mới dùng nó ở vị trí phụ; video render mượt ở điểm nối.
- Không cách nào (trừ sửa tay) khiến shot AI thay cho cận cảnh sản phẩm.
- Vượt trần generative -> bị chặn trước khi gọi API.
- 1 phiếu việc tay đi trọn vòng: nhận phiếu trên Telegram -> tạo clip trong app thuê bao -> trả lời bằng file -> clip có trong kho cảnh phụ với nhãn AI.
- Trong UI tạo cảnh phụ chọn được ít nhất: Việc tay, Kling, Seedance, Veo; đổi model không sửa code; mỗi model API đã sinh thật 1 clip 9:16 trong test live.

## Risk Assessment

- Chất lượng/khớp phong cách với footage thật kém -> người duyệt loại; tốn tiền vô ích. Giảm thiểu: xem trước rồi mới Giữ; bắt đầu bằng 5 clip thử.
- API video-gen đổi nhanh, có thể cần allowlist/tier trả phí: nếu provider 1 không truy cập được, đổi thứ tự (Sora trước).
- Image-to-video từ ảnh sản phẩm có thể làm biến dạng sản phẩm: mặc định tắt, ghi cảnh báo.
- Cắt đầu tiên trong phase: Sora trực tiếp; sau đó là bước so sánh model.
- Cổng model là bên thứ ba: thêm 1 nơi giữ key và 1 điểm có thể ngừng dịch vụ; Veo trực tiếp vẫn chạy độc lập.

## Security Considerations

- Ảnh sản phẩm gửi lên provider: dùng key trả phí, đọc điều khoản dữ liệu ở bước 1.
- Prompt người dùng nhập tự do: provider tự lọc nội dung; lỗi bị từ chối hiển thị nguyên văn, không retry.
- Minh bạch: tuân thủ yêu cầu gắn nhãn nội dung AI của nền tảng khi đăng.

## Next steps

- Phase 15 (độc lập).
- Ngoài phạm vi plan: template Remotion cố định (chỉ xét nếu phụ đề FFmpeg không đủ đẹp).
