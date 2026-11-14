# Phase 09: Engine MoneyPrinterTurbo: lồng tiếng, phụ đề theo giọng, nhạc, chuyển cảnh, chạy lô

(Tên file giữ nguyên để không gãy link. Nội dung viết lại 2026-11-13 theo yêu cầu tích hợp https://github.com/harry0703/MoneyPrinterTurbo.)

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 05](phase-05-ffmpeg-render-core.md) (cắt shot, bản master, preflight), [phase 04](phase-04-ai-provider-remix-plan.md) (kịch bản, luật sản phẩm); kết quả S8, S12 của [phase 01](phase-01-verification-spikes.md)
- Docs phải đọc trước khi viết: README và `config.example.toml` của MoneyPrinterTurbo (bản ghim), trang `/docs` (OpenAPI) của API server đang chạy; [research 02 mục 3, 4](research/researcher-02-video-pipeline-and-packaging.md)

## Overview

- Ngày: 2026-11-13
- Mô tả: chạy MoneyPrinterTurbo (MPT) như một dịch vụ phụ trên máy chủ và dùng nó làm engine lắp ráp cho chế độ Nhanh: lồng tiếng nhiều nhà cung cấp, phụ đề khớp giọng, nhạc nền, chuyển cảnh, nhiều tỉ lệ khung, chạy lô. App vẫn tự chọn shot và cắt shot để giữ độ chính xác sản phẩm.
- Ưu tiên: P1 (ứng viên cắt ĐẦU TIÊN nếu đợt 1 trượt; phase 05 đã đủ ra video có phụ đề + nhạc)
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- MPT (MIT, Python 3.11+, có REST API, CLI, chạy Windows) làm sẵn gần hết phần âm thanh và lắp ráp mà phase này trước đây định tự viết (TTS, mốc phụ đề, trộn nhạc, chuyển cảnh). Dùng nó thay vì viết lại (DRY). Thứ bị bỏ so với bản cũ: tự cắt theo nhịp nhạc bằng librosa (MPT không có; cắt theo nhịp thuộc chế độ Studio ở phase 17).
- Phân vai để giữ độ chính xác sản phẩm: APP chọn shot, cắt đúng mốc thời gian, xử lý footage ngang, viết lời từ `facts_json`. MPT chỉ nhận các đoạn đã cắt làm "tư liệu local" theo đúng thứ tự + lời có sẵn, rồi lồng tiếng, phụ đề, nhạc, ghép. Đầu ra của MPT vẫn qua `export.normalize()` và `preflight.check()` của phase 05.
- Những tính năng MPT phải TẮT hoặc không dùng: tự viết kịch bản bằng LLM của MPT (lời phải từ phase 04), tư liệu stock (Pexels/Pixabay/Coverr) và AI text-to-video cho cảnh sản phẩm, đổi tốc độ phát, crop-to-fill (dùng letterbox/giữ nguyên vì app đã đưa về 9:16), nhạc mặc định trong `resource/songs` (README của MPT ghi nhạc lấy từ YouTube, không rõ quyền: xoá khỏi bản cài, chỉ dùng nhạc người dùng nạp), tính năng đăng bài của MPT (đăng bài chỉ qua API chính thức, phase 07/11).
- CHƯA xác nhận, do S12 trả lời: API có nhận danh sách tư liệu local theo thứ tự và giữ đúng độ dài từng đoạn không; có tắt được crop/tốc độ/chuyển cảnh trên từng đoạn không; giọng tiếng Việt của từng nhà cung cấp; tên endpoint. Không viết adapter trước khi S12 có kết quả.
- Phụ đề: chế độ `edge` (mốc từ TTS) cho video lồng tiếng; chế độ `whisper` (faster-whisper, model ~1.6–3 GB, chạy CPU chậm) cho footage có tiếng nói thật của thợ. Whisper chỉ bật khi người dùng chọn.
- Edge TTS miễn phí và có giọng Việt nhưng điều khoản dùng thương mại không rõ (research 02 đã loại vì lý do này). Mặc định dùng nhà cung cấp trả phí người dùng đã nghe và chấp nhận ở S8; Edge TTS chỉ là lựa chọn người dùng tự bật sau khi đọc cảnh báo.
- Nhân bản giọng (VoxCPM, ElevenLabs): chỉ với giọng của người đã đồng ý bằng văn bản (ví dụ chủ thương hiệu). Tắt mặc định.

## Requirements

- MPT chạy như tiến trình con do app quản lý: bản ghim (tag/commit ghi trong `config.toml`), venv riêng `tools/mpt`, API chỉ nghe `127.0.0.1`, app khởi động/dừng/kiểm tra sức khoẻ; lỗi MPT không làm sập app.
- Cấu hình MPT (`config.toml` của nó) do app SINH RA từ Settings + secrets của app; người dùng không sửa tay 2 nơi.
- `videos.engine` (cột đã có từ phase 02, giá trị thứ ba `studio` thuộc phase 17): ở chế độ Nhanh chọn `ffmpeg` hoặc `mpt` theo video. Mặc định `mpt` khi video có lồng tiếng, `ffmpeg` (phase 05) khi không lời. Engine `mpt` hỏng thì tự lùi về `ffmpeg` kèm ghi chú trên màn hình duyệt.
- Luồng engine `mpt`: phase 05 cắt các đoạn `seg_NN.mp4` -> gửi MPT: lời theo từng đoạn (script có sẵn), danh sách đoạn theo thứ tự, giọng + ngôn ngữ, kiểu phụ đề, nhạc đã chọn, 9:16 -> chờ task -> lấy file -> normalize -> preflight -> `pending_approval`.
- Giọng đọc: trang Settings liệt kê nhà cung cấp và giọng mà MPT hỗ trợ, có nút nghe thử; chọn giọng mặc định riêng cho tiếng Việt và tiếng Anh; ghi đè được theo video.
- Kiểu phụ đề (font Be Vietnam Pro, màu, viền, vị trí trong vùng an toàn) cấu hình 1 lần, áp cho cả 2 engine.
- Chuyển cảnh: chỉ loại cắt thẳng và mờ dần ngắn; không hiệu ứng làm biến dạng hình trên shot `has_product = 1`.
- Chạy lô: nút "Dựng tất cả kịch bản đã lập" và lịch dựng ban đêm (giờ cấu hình) đẩy nhiều video vào hàng; tuần tự 1 video một lúc (PC không GPU).
- Thêm tỉ lệ khung (cắt được): xuất thêm 1:1 hoặc 16:9 từ cùng kịch bản khi người dùng tick; bản 9:16 vẫn là master cho 4 nền tảng.
- SFX: người dùng tự nạp; chèn tại điểm cắt bằng bước trộn nhỏ của app sau MPT (MPT không có SFX theo điểm cắt). Cắt được.
- Chi phí TTS ghi vào `ai_usage`, chịu trần ngân sách ngày.

## Architecture

```
engines/mpt_service.py   # start/stop/health của tiến trình MPT; sinh config MPT từ Settings + secrets
engines/mpt_client.py    # gọi REST theo OpenAPI thật đọc ở bước 1: tạo task, hỏi trạng thái, tải kết quả, liệt kê giọng
engines/mpt_engine.py    # assemble(video_id): segments + lời + giọng + nhạc -> file mp4; ánh xạ lỗi; lùi về ffmpeg
pipeline/render.py       # chọn engine theo videos.engine; sau engine luôn normalize + preflight
pipeline/sfx.py          # (cắt được) chèn SFX tại điểm cắt
api/routes_voices.py + web/templates/voices.html   # chọn giọng, nghe thử
```

Bản cài MPT nằm ở `tools/mpt/` (source ghim + venv riêng), không import vào app. `resource/songs` của MPT bị xoá khi cài.

## Related code files

Tạo: `src/videocreator/engines/mpt_service.py`, `engines/mpt_client.py`, `engines/mpt_engine.py`, `pipeline/sfx.py`, `api/routes_voices.py`, `web/templates/voices.html`, `installer/install_mpt.cmd`, `tests/test_mpt_config.py`, `tests/test_mpt_engine_local.py`, `tests/test_mpt_voice_live.py`, `reports/09-mpt-integration.md`.
Sửa: `pipeline/render.py`, `app.py` (lifespan quản lý MPT), `config.py` (`[mpt]`, `[voice]`), `web/templates/video_plan.html`, `web/templates/assets.html` (nạp SFX), `scheduler.py` (lịch dựng lô).

## Implementation Steps

1. Đọc kết quả S12 và OpenAPI của bản MPT ghim; ghi vào `reports/09-mpt-integration.md`: endpoint dùng, tham số tắt crop/tốc độ/stock, cách truyền tư liệu local theo thứ tự, danh sách nhà cung cấp giọng có tiếng Việt.
2. `installer/install_mpt.cmd`: tải bản ghim, tạo venv `tools/mpt`, xoá nhạc mặc định. `mpt_service.py`: sinh config, khởi động, health check.
3. `mpt_client.py` + `mpt_engine.py`; nối vào `render.py` với lùi về `ffmpeg`.
4. Trang giọng đọc + nghe thử; giọng mặc định theo ngôn ngữ.
5. Phụ đề: đồng bộ kiểu giữa 2 engine; tuỳ chọn whisper.
6. Chạy lô + lịch dựng ban đêm.
7. (Cắt được) SFX tại điểm cắt; thêm tỉ lệ 1:1 / 16:9.
8. Test `-m local` (MPT thật chạy trên máy, clip mẫu thật, giọng dùng nhà cung cấp không tốn tiền hoặc bỏ lồng tiếng): config sinh ra không chứa nguồn stock và không có đường dẫn nhạc mặc định; dựng 3 đoạn theo thứ tự -> thứ tự và độ dài từng đoạn trong đầu ra khớp (so khung đầu mỗi đoạn với nguồn), không crop, không đổi tốc độ; MPT bị tắt giữa chừng -> video lùi về engine `ffmpeg`.
9. Test `-m live`: lồng 1 câu tiếng Việt và 1 câu tiếng Anh bằng nhà cung cấp đã chọn -> video có tiếng, phụ đề khớp, `ai_usage` có chi phí.
10. Checklist tay (người dùng nghe và xem): giọng rõ, nhạc lùi dưới giọng, phụ đề đúng dấu và nằm trong vùng an toàn, chi tiết sản phẩm không khác bản engine `ffmpeg`.

## Todo list

- [ ] Đọc OpenAPI + kết quả S12, viết báo cáo tích hợp
- [ ] Cài MPT bản ghim + quản lý tiến trình + sinh config
- [ ] Client + engine + lùi về ffmpeg
- [ ] Chọn giọng, nghe thử
- [ ] Phụ đề đồng bộ kiểu; tuỳ chọn whisper
- [ ] Chạy lô + lịch ban đêm
- [ ] SFX, thêm tỉ lệ khung (cắt được)
- [ ] Test local + live + người dùng nghe duyệt

## Success Criteria

- Cùng 1 kịch bản dựng 3 kiểu (không lời bằng `ffmpeg`; tiếng Việt và tiếng Anh bằng `mpt`) đều ra bản master hợp lệ qua preflight; người dùng chấp nhận bản tiếng Việt.
- So khung hình: shot sản phẩm trong bản `mpt` không bị crop, đổi tốc độ hay đổi màu so với nguồn.
- Bấm "Dựng tất cả" với 5 kịch bản: sáng hôm sau có 5 video trong hàng chờ duyệt.
- Tắt MPT: app vẫn chạy, video vẫn dựng được bằng `ffmpeg`.

## Risk Assessment

- S12 không đạt (API không giữ thứ tự/độ dài, hoặc ép crop/chuyển cảnh): KHÔNG dùng MPT làm engine lắp ráp. Lùi: chỉ gọi phần TTS + mốc phụ đề của MPT (nếu tách gọi được), hoặc quay về thiết kế cũ tự viết: `pipeline/tts.py` (1 hàm `synthesize(text, lang)`), `pipeline/audio.py` (trộn `sidechaincompress` + `loudnorm`), phụ đề theo độ dài từng dòng lời. Ước lượng không đổi.
- MPT nén lại hình thêm 1 lần -> mất chi tiết chạm khắc. Giảm thiểu: đoạn đầu vào CRF 14, đặt chất lượng xuất của MPT cao nhất, so khung hình ở test; nếu vẫn mất chi tiết thì MPT chỉ làm âm thanh + phụ đề, hình do `ffmpeg` ghép.
- Thêm 1 tiến trình + 1 venv nặng (MoviePy, faster-whisper) vào bộ cài; cập nhật MPT có thể đổi API -> ghim phiên bản, nâng cấp là thao tác có chủ ý.
- Dự án MPT đổi nhanh, README nhiều quảng cáo nhà tài trợ: chỉ dùng tính năng đã tự kiểm chứng ở S12.
- Phase này trượt không chặn phase nào khác.

## Security Considerations

- API của MPT chỉ nghe `127.0.0.1`; không mở WebUI Streamlit của MPT ra mạng.
- Key nhà cung cấp giọng nằm trong secrets của app; file config sinh cho MPT đặt trong thư mục dữ liệu, quyền hạn chế, không vào log, xoá khi app thoát nếu được.
- Không bật tính năng đăng bài, tải stock hay AI video của MPT; test khẳng định config sinh ra không có các mục đó.
- Nhân bản giọng chỉ với sự đồng ý của chủ giọng; giấy phép nhạc/SFX là trách nhiệm người nạp file.

## Next steps

- Phase 14 xét dùng nguồn stock của MPT làm cảnh phụ KHÔNG chứa sản phẩm (có gắn nhãn) và các nhà cung cấp AI video của MPT.
- Phase 16 dùng chạy lô cho nút "Tạo 3 bản" trên Telegram.
