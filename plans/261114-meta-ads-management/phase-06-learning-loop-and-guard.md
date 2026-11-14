# Phase 06: Học từ kết quả + tự tắt bảo vệ (tuỳ chọn)

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 03](phase-03-evaluation-and-recommendations.md), [phase 05](phase-05-content-based-campaign-proposals.md)

## Overview

- Ngày: 2026-11-14
- Mô tả: tổng hợp kết quả quảng cáo theo loại nội dung, mục tiêu, độ dài video, kiểu mở đầu -> đưa vào ngữ cảnh đề xuất của phase 05 và ngưỡng của phase 03.
- **Đã bỏ phần tự tắt bảo vệ** theo quyết định chủ (câu 5: luôn chờ duyệt). Thay bằng: đề xuất "Nên tắt" nặng (chi >= 3× target, 0 kết quả) gửi Telegram ở mức ưu tiên cao và nhắc lại sau 2 giờ nếu chưa duyệt. Các mục `guard.py`, cờ `auto_pause` bên dưới KHÔNG làm.
- Ưu tiên: P3
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Không cần máy học: bảng tổng hợp đơn giản (trung vị chi phí/kết quả theo nhóm, số mẫu) đủ cho shop nhỏ; nhóm < 3 campaign thì không dùng.
- Tự tắt chỉ giảm chi, nên rủi ro thấp; nhưng chủ quyết (câu hỏi 5 của plan.md).

## Requirements

- View/hàm `performance_by_group(content_type, objective)` -> trung vị, số mẫu, campaign tốt nhất.
- Đề xuất phase 05 nhận khối "kết quả quá khứ" + mã ưu tiên mục tiêu có trung vị tốt hơn khi đủ mẫu.
- Ngưỡng target trong phase 03 tự cập nhật từ trung vị 30 ngày nếu chủ chưa đặt.
- Cờ `[ads.guard] auto_pause = false`; luật kích hoạt: chi >= 3× target mà 0 kết quả, chỉ campaign `managed_by_app = 1`; mỗi lần tự tắt tạo `ad_actions` `executed` với `decided_by = "guard"` và thẻ Telegram có nút "Bật lại".

## Architecture

```
ads/learning.py   # performance_by_group (SQL thuần)
ads/guard.py      # chạy sau ads_evaluate khi cờ bật -> execute_action(..., approver="guard") chỉ cho action=pause
```

## Related code files

Tạo: các file trên, `tests/test_ads_learning.py`, `tests/test_ads_guard.py`. Sửa: `ads/propose.py`, `ads/evaluate.py`, `config.py`, `tg/messages.py`.

## Implementation Steps

1. `learning.py` + test trên số liệu thật đã đồng bộ.
2. Nối vào `propose.py` và target của `evaluate.py`.
3. `guard.py`: chỉ action `pause`; test rằng guard không bao giờ tạo `activate`/`set_budget` tăng.
4. Thẻ Telegram "Đã tự tắt" + nút bật lại (đi qua duyệt + trần như thường).

## Todo list

- [ ] Tổng hợp theo nhóm
- [ ] Nối vào đề xuất và ngưỡng
- [ ] Guard chỉ-tắt + test
- [ ] Thẻ Telegram

## Success Criteria

- Sau >= 3 campaign mỗi nhóm, đề xuất mới trích dẫn kết quả quá khứ đúng số liệu.
- Guard tắt: chỉ khi cờ bật, chỉ campaign app quản lý, chỉ hướng tắt (test khẳng định).

## Risk Assessment

- Mẫu nhỏ gây kết luận sai -> ngưỡng số mẫu tối thiểu, hiện số mẫu trên mọi chỉ số.
- Guard tắt nhầm campaign đang học -> luật guard chặt hơn luật "Nên tắt" (3× thay vì 2×) và bỏ qua campaign < 3 ngày.

## Security Considerations

- Guard dùng chung `execute_action`, chung audit; không có đường ghi riêng.

## Next steps

- Phase 07 kiểm chứng toàn bộ trên tài khoản thật.
