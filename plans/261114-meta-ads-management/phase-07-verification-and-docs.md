# Phase 07: Chạy thật, ma trận xung đột, tài liệu

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: phase 01–06 (06 tuỳ chọn)
- Docs: [đặc tả](../../docs/video-creator-spec.md), [plan app](../261112-video-creator-app/plan.md)

## Overview

- Ngày: 2026-11-14
- Mô tả: chạy trọn chuỗi trên tài khoản thật với một campaign ngân sách nhỏ do chủ duyệt; kiểm không làm hỏng phần còn lại; cập nhật đặc tả.
- Ưu tiên: P1
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Đánh giá hiệu quả cần campaign chạy vài ngày có chi tiêu thật; phase này kéo dài theo lịch, không theo giờ công.
- Mọi lần khởi động lại máy chủ cắt job đang chạy: làm lúc hàng đợi trống.

## Requirements

### Ma trận xung đột

| Phần sẵn có | Rủi ro | Phép kiểm |
|---|---|---|
| Migration | trùng số với plan TikTok | dùng số kế tiếp lúc làm; `test_db.py` xanh; nâng bản sao DB thật trước |
| Đăng bài Meta (`posting/`, Graph v22.0) | phiên bản Graph khác, token khác | `posting/` không đổi (`git diff --stat`); test đăng bài xanh |
| Hàng đợi job (một luồng) | job quảng cáo chiếm hàng đợi | đo thời gian `ads_sync`/`ads_evaluate`; job dựng xếp sau vẫn chạy |
| Hạn mức AI gói thuê bao | thêm lượt gọi `writer` | đếm `ai_usage` theo ngày trước/sau; quét đánh giá gom 1 lượt AI cho mọi ad |
| Telegram (chủ đề, nút) | nút mới đụng nút cũ | `test_tg_*.py` xanh; tiền tố callback riêng `ads_` |
| Báo cáo ngày | thêm khối quảng cáo | `test_reports.py` xanh |
| Xuất/nhập cấu hình | khoá `[ads]` mới, token mới | `test_transfer.py` xanh; token đi theo kho bí mật như các token khác |

### Chạy thật

- Đồng bộ tài khoản thật; `/ads` khớp Ads Manager.
- Một video đã đăng -> đề xuất -> duyệt -> campaign PAUSED -> duyệt bật với ngân sách nhỏ nhất chủ chọn -> chạy 3–5 ngày -> đánh giá -> đề xuất (tắt/tăng/giữ) -> duyệt -> Meta đổi đúng.
- Thử chặn: đề xuất tăng ngân sách vượt trần bị từ chối, không có request ghi.

### Tài liệu

- Đặc tả: nhóm yêu cầu mới `FR-ADS-*` (đọc, đánh giá, đề xuất, thực thi có duyệt, trần, tự tắt tuỳ chọn), luật `BR-ADS-*` (không chi tiền khi chưa duyệt; trần trong mã), dịch vụ ngoài "Meta Marketing API", rủi ro.
- Plan app: thêm dòng kế hoạch quảng cáo.

## Architecture

Không có mã mới. Báo cáo `reports/07-verification-results.md`.

## Related code files

Sửa: `docs/video-creator-spec.md`, `plans/261112-video-creator-app/plan.md`, `plan.md` này.

## Implementation Steps

1. Toàn bộ test (`.venv/Scripts/python.exe -m pytest -m "not live"`), rồi các test live quảng cáo.
2. Sao lưu `app.db`, thử migration trên bản sao, khởi động mã mới khi hàng đợi trống.
3. Chạy thật theo mục trên; ghi số liệu, ảnh chụp thẻ Telegram.
4. Điền ma trận; cập nhật tài liệu.

## Todo list

- [ ] Test đầy đủ + live
- [ ] Sao lưu + migration bản sao
- [ ] Chuỗi thật 1 campaign
- [ ] Ma trận + tài liệu

## Success Criteria

- Chuỗi thật chạy trọn, tổng chi tiêu đúng bằng mức chủ duyệt, không đồng nào phát sinh ngoài duyệt.
- Mọi dòng ma trận "đạt" kèm số liệu.

## Risk Assessment

- Quảng cáo bị Meta từ chối duyệt -> đổi video/chữ, không tính là lỗi app.
- Ngân sách nhỏ cho số liệu ít -> kết luận "Chưa đủ dữ liệu" là đúng; kiểm luật bằng test, không ép kết luận.

## Security Considerations

- Báo cáo không chứa token, id tài khoản quảng cáo đầy đủ, số tiền thanh toán.

## Next steps

- Chạy 2–4 tuần, chỉnh ngưỡng theo dữ liệu thật; xem xét lên mức truy cập Full nếu cần đồng bộ dày hơn.
