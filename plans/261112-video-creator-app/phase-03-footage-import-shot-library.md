# Phase 03: Nhập footage + kho shot

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 02](phase-02-project-skeleton.md); kết quả S1, S7 của [phase 01](phase-01-verification-spikes.md)
- Docs: [research 02 mục 1](research/researcher-02-video-pipeline-and-packaging.md)

## Overview

- Ngày: 2026-11-12
- Mô tả: nhập file video -> job tách shot -> lưu mốc thời gian + thumbnail vào `shots` -> trang kho shot xem được. Mô tả nội dung shot (AI) thêm ở phase 04.
- Ưu tiên: P0
- Trạng thái triển khai: hoàn thành (2026-11-13)
- Trạng thái review: đã kiểm thử (`pytest -m local`: 17/17 passed)

## Key Insights

- Độ chính xác sản phẩm (yêu cầu người dùng 2026-11-12), phần của phase này:
  - Bảng `products` (id, tên, chất liệu, `facts_json`: kích thước, đá, kỹ thuật chế tác, giá nếu muốn công bố) do NGƯỜI DÙNG nhập tay trong UI. Đây là nguồn sự thật duy nhất cho lời thoại và caption.
  - Khi nhập footage, người dùng chọn sản phẩm xuất hiện trong footage (`footage.product_ids_json`); shot thừa kế từ footage, sửa được từng shot. AI không được tự gán sản phẩm, chỉ gợi ý.
  - Lưu `footage.width/height/orientation` và cảnh báo khi footage quay ngang (cắt 9:16 sẽ mất phần hình) hoặc độ phân giải dưới 1080 ở cạnh ngắn.

- rea-video chỉ được ghi nhận chạy trên macOS/Ubuntu. Nhánh dùng tuỳ kết quả S1; code chỉ cài MỘT nhánh, không giữ cả hai.
- rea-video kéo onnxruntime/opencv -> cài vào venv riêng, gọi qua subprocess bằng đường dẫn tuyệt đối. Không import vào app (tránh xung đột dependency, dễ đóng gói).
- Footage copy vào `media/footage/` (để upload qua trình duyệt và máy chủ headless dùng chung 1 đường). Tốn đĩa: chấp nhận, ghi rõ trong UI.
- Trùng file phát hiện bằng sha256.

## Requirements

- Trang Sản phẩm: thêm/sửa/xoá sản phẩm và `facts_json` (form đơn giản: tên, chất liệu, đá, kích thước, kỹ thuật, giá, ghi chú).
- Khi nhập footage: bắt buộc chọn >= 1 sản phẩm (hoặc đánh dấu "không có sản phẩm", ví dụ cảnh xưởng); sửa được theo từng shot trong kho shot.
- Cảnh báo khi footage quay ngang hoặc cạnh ngắn dưới 1080; với footage ngang cho chọn vùng crop 9:16 (lưu `footage.crop_json`) hoặc để mặc định "nguyên khung trên nền mờ".
- Nhập qua UI: chọn file (upload multipart) hoặc dán đường dẫn thư mục trên máy chủ.
- Sau nhập: `footage.status = imported` -> job `analyse` -> `analysing` -> `analysed`/`failed`.
- Mỗi shot: `start_s`, `end_s`, thumbnail (frame giữa). Bỏ shot < 0.7 giây.
- Trang kho shot: lưới thumbnail, lọc theo footage, bấm xem lại đoạn shot.
- Hiện tiến độ job và lỗi (đuôi stderr) trong UI.

## Architecture

```
pipeline/probe.py     # ffprobe -> duration, width, height, fps
pipeline/shots.py     # detect_shots(path) -> list[ShotSpan(start_s, end_s)]
pipeline/thumbs.py    # ffmpeg -ss mid -frames:v 1 -> jpg
api/routes_footage.py # POST /footage, GET /footage, GET /shots, GET /media/...
```

- Nhánh A (S1 đạt): `shots.py` chạy `rea-video decompose <file> -o <work> --no-packaging --no-asr`, đọc `breakdown.json`, ánh xạ sang `ShotSpan`.
- Nhánh B (S1 không đạt): `scenedetect` (PySceneDetect, `ContentDetector`) trong chính venv app.
- Handler job `analyse`: probe -> detect -> thumbs -> insert `shots` trong 1 transaction -> `footage.status = analysed`.
- Phát lại shot trong UI: thẻ `<video>` với `#t=start,end` trỏ tới route phục vụ file footage (hỗ trợ Range).

## Related code files

Tạo: `src/videocreator/api/routes_products.py`, `web/templates/products.html`, `tests/test_products.py`, `src/videocreator/pipeline/probe.py`, `pipeline/shots.py`, `pipeline/thumbs.py`, `api/routes_footage.py`, `web/templates/footage.html`, `web/templates/shots.html`, `tests/test_shots.py`, `tests/samples/*.mp4` (clip thật do người dùng cấp).
Sửa: `app.py` (đăng ký router + handler job), `paths.py` (đường dẫn rea-video venv nếu nhánh A).

## Implementation Steps

1. Đọc `reports/01-verification-results.md`, chọn nhánh A hoặc B.
2. `probe.py` (ffprobe JSON).
3. `shots.py` theo nhánh đã chọn; subprocess có timeout, bắt stderr vào `jobs.log_tail`.
4. `thumbs.py`.
5. Route nhập footage (upload + đường dẫn), tính sha256 theo luồng, từ chối trùng.
6. Handler job `analyse` + đăng ký vào worker.
7. Template danh sách footage (trạng thái, nút phân tích lại) và kho shot.
8. Test `-m local`: chạy phân tích thật trên `tests/samples/`, khẳng định có >= 1 shot, các shot không chồng nhau, nằm trong thời lượng, thumbnail tồn tại; nhập trùng bị từ chối.

## Todo list

- [x] Chọn nhánh theo S1 (Nhánh A: `rea-video` chạy qua `.venv-rea` subprocess)
- [x] probe (`pipeline/probe.py`)
- [x] detect_shots (`pipeline/shots.py`, lọc `< 0.7s`, chia đoạn `> 8.0s` thành 3–5s)
- [x] thumbnails (`pipeline/thumbs.py`)
- [x] Trang Sản phẩm + gắn sản phẩm cho footage/shot (`routes_products.py`, `products.html`)
- [x] Cảnh báo hướng quay/độ phân giải + chọn vùng crop cho footage ngang (`blur_pad` / `crop`)
- [x] Route nhập + chống trùng (`sha256`)
- [x] Job analyse (`run_analyse_footage`)
- [x] UI footage + kho shot (`footage.html`, `shots.html`)
- [x] Test local trên clip thật (`test_products.py`, `test_shots.py`)

## Success Criteria

- Nhập 1 footage thật 30–60 giây -> trong < 5 phút thấy các shot có thumbnail trong kho, bấm xem được từng shot.
- Tắt app giữa lúc phân tích, mở lại: job tự chạy lại và hoàn tất.
- `pytest -m local` xanh.

## Risk Assessment

- Footage quay liền 1 mạch, không có điểm cắt -> chỉ ra 1 shot dài. Giảm thiểu: shot dài hơn 8 giây bị chia đều thành đoạn 3–5 giây.
- File điện thoại HEVC/10-bit/xoay dọc: probe đọc `rotation`; render ở phase 05 sẽ re-encode nên không cần chuyển mã lúc nhập.
- Đường dẫn có dấu tiếng Việt làm hỏng CLI: copy vào `media/footage/<id>.mp4` (tên ASCII) trước khi xử lý.

## Security Considerations

- Chỉ nhận đuôi video cho phép; tên file lưu do app đặt (theo id), không dùng tên gốc trong đường dẫn.
- Route phục vụ media chỉ đọc trong `media/`, chặn path traversal.

## Next steps

- Phase 04 thêm mô tả + tag cho shot và lập kịch bản remix.
