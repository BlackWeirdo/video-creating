# Giai đoạn 17 và S11: Studio (agent + Remotion)

Cập nhật: 2026-11-14. Thay bản ngày 2026-11-13, vốn là thiết kế dự kiến chưa từng chạy.

## 1. Kết quả S11

Máy chủ: Windows 10, i7-9750H, 8 GB RAM, Node.js 24.22.1, Remotion 4.0.484.

| Hạng mục | Kết quả |
|---|---|
| Dựng video dọc 1080x1920 từ footage thật bằng Remotion | **Đạt.** [spikes/s11_remotion](../../../spikes/s11_remotion): 3 shot, 8 giây, phụ đề Be Vietnam Pro đúng dấu. `npm install` 29 giây (214 MB), trình duyệt headless 113 MB tải một lần, mỗi lần dựng 78 giây với 2 luồng |
| Thành phần `ClipCard` của video-shotcraft | **Không dùng được cho hình sản phẩm.** Nó là thẻ hình vuông với `objectFit: cover` (cắt footage 9:16 thành vuông) và vòng lặp mờ chồng bằng `opacity`; cả hai trái `BR-PRD-02`, `BR-PRD-03`. App dùng thành phần toàn khung riêng (`ProductShot`) |
| Agent `claude -p` viết cảnh, app kiểm tra và dựng | **Đạt.** `tests/test_studio_live.py`: 1 phút 56 giây cho video 9 giây, model `sonnet`, gói thuê bao. Chi phí ước tính nếu tính theo giá API: 0,18 USD. Agent dùng đúng `ProductShot`, lấy shot trong khoảng cho phép, chỉ làm mờ dần chữ |
| Phân tích video tham khảo bằng skill rea-video (`VIDEO.md`) | **Chưa làm**: chưa có file video xu hướng. `rea-video decompose` đã chạy được trên footage (S1) |
| Người dùng chấm chất lượng | **Chưa làm.** Bản dựng thử: `spikes/out/s11_studio_live/v1.mp4` |
| Giấy phép Remotion cho công ty | **Chưa kiểm.** Remotion miễn phí cho cá nhân và nhóm nhỏ, công ty có thể phải mua; người dùng cần đọc https://github.com/remotion-dev/remotion/blob/main/LICENSE.md |

Kết luận: phần dựng đạt, nên Studio làm theo hướng đầy đủ (không phải nhánh lùi "dựng bằng FFmpeg"). Phần "giữ cấu trúc video tham khảo" còn chờ kiểm chứng với video xu hướng thật.

## 2. Thiết kế đã hiện thực (viết lại lần hai ngày 2026-11-14)

Một phiên Studio là một việc `studio` trong hàng đợi của app (`studio/agent.py: run_studio_job`), chạy lần lượt như mọi việc khác. Tắt app giữa chừng thì việc được chạy lại khi mở app; phiên nào ghi "đang chạy" mà không còn việc nào đứng sau thì bị đánh `failed` lúc khởi động để không chặn Studio.

Nội dung và cách trình bày tách làm hai file:

- `plan.json` (kịch bản): danh sách cảnh, mỗi cảnh là một đoạn liên tục của một shot kèm phụ đề. Agent viết, app kiểm tra (`studio/plan.py`): shot có trong kho, khoảng thời gian nằm trong shot, độ dài tối thiểu, phụ đề không nhắc sản phẩm khác (`BR-PRD-05`), rồi chạy vai `checker` để đánh dấu câu nêu thông số không có trong dữ liệu sản phẩm (`BR-PRD-06`). App sinh `src/plan.ts` từ kịch bản đã kiểm.
- `src/Scene.tsx` (trình bày): agent viết, chỉ được lấy file, mốc thời gian và chữ từ `PLAN` của `./plan`. Bộ quét loại mã ghi cứng tên file hoặc mốc thời gian, thẻ video ngoài `ProductShot`, import lạ, và các vi phạm `BR-PRD-02`.

Các bước:

1. **Kịch bản** (`planning`): agent `claude -p` (chỉ có `Read, Write, Edit, Glob, Grep` trong thư mục phiên, không shell, không web, không MCP) viết `plan.json`. Sai thì trả agent sửa một lần.
2. **Điểm dừng xác nhận** (`awaiting_confirm`, `FR-STD-05`): trang Studio hiện bảng cảnh → shot → đoạn lấy → phụ đề. Người dùng bấm "Kịch bản ổn, dựng video" hoặc gõ prompt sửa (kịch bản được viết lại rồi dừng lần nữa). Có ô "Chạy thẳng".
3. **Dựng** (`rendering`): agent viết `Scene.tsx`; app quét, chạy `remotion render`; lỗi quét hoặc lỗi dựng trả agent sửa đúng một lần (`FR-STD-07`).
4. **Âm thanh** (`studio/audio.py`, `FR-STD-06`): giọng đọc tổng hợp riêng từng cảnh qua MoneyPrinterTurbo (như chế độ Nhanh) và đặt đúng đầu cảnh; lời đọc dài hơn cảnh thì bị bắt ngay ở bước kịch bản và trả agent rút lời. Tuỳ chọn âm thanh ở mỗi điểm cắt và nhạc nền từ kho file người dùng đã nạp. MPT không chạy thì video chỉ có phụ đề, có ghi chú cho người duyệt.
5. **Xuất**: cùng hàm chuẩn hoá bản master, ảnh bìa, kiểm tra định dạng như mọi engine (`BR-FMT-02`); video sang `pending_approval` kèm ghi chú "có hiệu ứng chuyển động trên footage" (`BR-PRD-09`) và báo Telegram.
6. **Sửa bằng prompt** (`FR-STD-08`): trên phiên đã có bản dựng, agent được sửa cả kịch bản lẫn trình bày trong cùng phiên agent (`--resume`); mỗi lượt lưu `out/v<N>.mp4`, `v<N>.Scene.tsx`, `v<N>.plan.json`.
7. **Mẫu** (`FR-STD-09`): "Lưu làm mẫu" giữ `Scene.tsx`. "Dựng từ mẫu" nhận shot và phụ đề mới, app tự viết `plan.json` rồi quét, dựng Remotion và xuất như trên, không gọi agent.

Hết hạn mức gói thuê bao giữa chừng: việc chuyển `waiting_quota` và tự chạy tiếp, phiên giữ nguyên bước đang làm.

Bản sao skill trong `vendor/skills/`: `rea-video` (SKILL.md + references) và `video-shotcraft` (SKILL.md, references, `assets/lib`). Đã bỏ `publish-upload-post.md` vì đó là đăng bài qua dịch vụ trung gian, ngoài phạm vi (đặc tả mục 1.3).

Chạy thật ngày 2026-11-14 (`tests/test_studio_live.py`, agent `claude -p` model `sonnet`, giọng Hoài My qua MoneyPrinterTurbo, Remotion): cả ba lượt mất 6 phút 28 giây.

- Lượt kịch bản: agent viết 4 cảnh (9 giây); bộ kiểm bắt lời đọc dài hơn cảnh và agent rút lời một lần; dừng ở bước chờ xác nhận.
- Lượt dựng sau khi xác nhận: phiên bản 1, 9,0 giây, có giọng đọc từng cảnh.
- Lượt sửa "đổi phụ đề cảnh cuối": phiên bản 2 trên cùng phiên agent, agent tự kéo cảnh cuối từ 2,0 lên 2,8 giây cho vừa lời mới; bản 1 còn nguyên.
- Chi phí ước tính nếu tính theo giá API: khoảng 0,12 USD cho cả phiên (thực tế dùng gói thuê bao).
- Kết quả để xem và chấm: `spikes/out/s11_studio_live_v2/` (`master.mp4` là bản 2 đã chuẩn hoá, có tiếng).

Chưa chạy thật: nhạc nền trong Studio (chưa có file nhạc người dùng nạp; phần ghép nhạc dùng chung với chế độ Nhanh), và dựng từ mẫu với agent thật (test local dựng từ mẫu bằng Remotion thật đã đạt).

## 3. Còn thiếu của giai đoạn 17

| Yêu cầu | Tình trạng |
|---|---|
| `FR-STD-01` chọn footage/shot, sản phẩm, thời lượng trong form | Form có prompt, giọng đọc, nhạc, âm thanh điểm cắt, chạy thẳng. Chưa có ô chọn shot/sản phẩm cho phiên mới (agent nhận tối đa 60 shot tốt nhất của cả kho); dựng từ mẫu thì chọn được shot |
| `FR-STD-03`, `04` phân tích video tham khảo và giữ đường kể chuyện | Chưa nối; cần video xu hướng để thử. Bảng xác nhận vì thế chưa có cột "shot tham khảo" |
| `FR-STD-06` cắt theo nhịp nhạc | Chưa có (app chưa có bộ dò nhịp). Giọng đọc, nhạc nền, âm thanh điểm cắt đã có |
| Caption bốn nền tảng cho video Studio | Chưa sinh; người duyệt tự nhập ở màn hình duyệt |
| `FR-STD-11` hiện ước tính trước khi chạy | Chưa có; chỉ ghi số lượt và chi phí ước tính sau khi chạy |
| `FR-STD-12` Workbench, "Sửa:" trên Telegram | Chưa có (mức "nên") |
| Trang Studio tự cập nhật trạng thái | Chưa có; phải tải lại trang để thấy phiên chuyển bước |
