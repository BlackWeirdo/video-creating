# Plan: Sửa 10 lỗi từ đợt rà mã (review fixes)

Ngày: 2026-11-15. Trạng thái: đã viết mã cả 6 phase, suite `-m "not live"` xanh (184 test); phase 06 chờ test live với token Meta Page. Chưa commit. Gốc repo: `c:\Project Video Creator\`. Mã nguồn: `src/videocreator/`.
Nguồn: [scout vị trí mã](scout/scout-01-code-locations.md), [research Meta Reels + số liệu](research/researcher-01-meta-reels-and-metrics.md), [research chấm điểm video](research/researcher-02-ai-video-scoring.md), [đặc tả](../../docs/video-creator-spec.md), [plan gốc](../261112-video-creator-app/plan.md), [CLAUDE.md](../../CLAUDE.md).

## Mục tiêu

Sửa 10 lỗi review: tiền AI không bị vượt ngầm, việc của người dùng không bị phân tích xu hướng chặn, kịch bản nhận đủ phân tích video mẫu và đúng một sản phẩm, chấm điểm nhìn đủ hình, giữ được tiếng gốc, Facebook đăng Reels không trùng, số liệu lỗi được lấy lại.

## Nguyên tắc chung

- Cây làm việc đang có thay đổi CHƯA commit (auto trend analysis, refactor). Không revert; đọc file hiện tại trước khi sửa.
- Migration kế tiếp: `012`. Chỉ phase 02 thêm migration.
- Test thật: SQLite thật, FFmpeg thật trên `tests/samples/`, provider tiêm vào chạy mã thật; không mock. Test live đánh dấu `live`, thiếu token thì skip.
- Chạy toàn bộ: `.venv/Scripts/python.exe -m pytest -m "not live"` (~4 phút, hiện 158 test đạt). Mỗi phase kết thúc bằng suite xanh + 1 commit (conventional commits, tiếng Anh).

## Phases (theo thứ tự làm)

| # | Phase | Lỗi | Ước lượng | Cần tài khoản thật | Trạng thái | Tiến độ |
|---|---|---|---|---|---|---|
| 01 | [An toàn dữ liệu và chi phí](phase-01-safety-and-cost-guards.md) | F8, F9, F7, F10 | 1 ngày | Không | Xong (test local) | 100% |
| 02 | [Ưu tiên hàng đợi + đề xuất theo lô](phase-02-job-priority-and-trend-batch.md) | F3 | 0.75 ngày | Không | Xong (test local) | 100% |
| 03 | [Kịch bản nhận đủ phân tích mẫu + kho shot gọn theo sản phẩm](phase-03-planner-trend-analysis-and-shot-focus.md) | F1, F4 | 0.75 ngày | Không | Xong (test local) | 100% |
| 04 | [Chấm điểm bằng nhiều khung hình](phase-04-quality-scoring-with-frames.md) | F2 | 1 ngày | Không (live tuỳ chọn) | Xong (test local) | 100% |
| 05 | [Giữ tiếng gốc của footage](phase-05-keep-original-footage-audio.md) | F5 | 0.75 ngày | Không | Xong (test local) | 100% |
| 06 | [Facebook Reels + khôi phục bài đang đăng](phase-06-facebook-reels-and-publish-recovery.md) | F6 | 1–1.25 ngày | Có: token Meta Page (S2/S3) cho test live | Mã xong, chờ test live | 90% |

Tổng: ~5–5.5 ngày làm việc, chưa có đệm.

## Phụ thuộc

- 01, 02, 05, 06 độc lập với nhau.
- 04 cần 03 (gợi ý sửa lỗi đi qua `replan` và `plan_prompts.py` mà 03 sửa).
- 06: viết mã và test local được ngay; đăng thật chờ S2/S3 (token Meta Page). Không có token thì test live tự skip.

## Ngoài phạm vi (các lệch đặc tả từ review, xử lý riêng)

1. Định tuyến mặc định `vision/writer = claude_api` qua cổng bên thứ ba (lệch `BR-COST-01` ưu tiên gói thuê bao).
2. Mô tả shot (`describe`) không tự xếp hàng sau tách shot (`FR-FTG-06`).
3. Bộ kiểm tra sự thật lỗi bị coi là "sạch" thay vì chặn.
4. Danh sách người duyệt rỗng = ai trong nhóm cũng duyệt được.
5. Chính sách `ask` (hỏi trước khi dùng API) chưa có nút trên Telegram (`FR-AI-05`).
6. Việc không gấp chưa dời vào giờ thấp điểm (`FR-AI-06`).
7. Các lệch còn lại trong báo cáo review (ngoài phần khôi phục bài `publishing` đã gộp vào phase 06).

## Câu hỏi cần chủ dự án quyết (kèm khuyến nghị)

1. Tiếng gốc footage: mặc định tắt hay bật? Khuyến nghị: TẮT (giữ hành vi cũ), bật trong Settings; âm lượng 0.3 khi có lồng tiếng/nhạc.
2. Model chưa có giá trong `[prices]`: chặn gọi API (khuyến nghị, đúng `BR-COST-02` "chặn trước khi gọi") hay tính giá mặc định cao? Cần chủ dự án cung cấp giá `gemini-3.6-flash` để thêm vào mặc định.
3. Chấm điểm bằng Claude xem ảnh (gói thuê bao, không tốn tiền) hay Gemini xem cả video (trả phí, thấy chuyển động + tiếng)? Khuyến nghị: Claude + 8–12 khung hình; tự dùng video đầy đủ khi `vision` định tuyến sang Gemini.
4. Giữ bản điểm cao nhất cần thêm chuyển trạng thái `superseded → pending_approval` (sửa đặc tả §6). Đồng ý? Khuyến nghị: đồng ý, chỉ cho actor `auto_quality`.
5. `trends.auto_analyse_top_n` mặc định 3 mỗi nguồn (5 nguồn ≈ 15 video/lần quét). Đồng ý?
6. Ngày tính hạn mức đổi sang giờ VN: số liệu `ai_usage` của đúng ngày chuyển đổi bị lệch một lần. Chấp nhận?
7. Facebook Reels: dạng link bài (permalink) và việc gửi lại `finish` cho video đã đăng chưa kiểm chứng; cần test live khi có token.
