# Phase 03: Đánh giá hiệu quả + đề xuất hành động

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 02](phase-02-readonly-sync-and-reports.md)
- Mã liên quan: `src/videocreator/ai/router.py` (`get_provider(paths, "writer")`, `QuotaWaitRequested`), `src/videocreator/pipeline/broll_suggest.py` (khuôn: ngữ cảnh -> AI -> mã kiểm -> lưu), `src/videocreator/jobs.py`

## Overview

- Ngày: 2026-11-14
- Mô tả: mỗi ad/ad set/campaign có kết luận (Chưa đủ dữ liệu / Hiệu quả / Cần sửa / Nên tắt / Nên tăng ngân sách) do LUẬT trong mã tính; AI viết lời giải thích dễ hiểu và gợi ý sửa cụ thể. Mỗi gợi ý thành một dòng `ad_actions` ở trạng thái `proposed`, gửi chủ đề Telegram "Quảng cáo". Chưa thực thi gì (phase 04).
- Ưu tiên: P1
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Kết luận bật/tắt phải tái lập được và giải thích được: dùng luật, không để AI tự quyết. AI làm phần chẩn đoán bằng lời (vì sao CTR thấp, nên đổi gì ở video).
- Meta cần thời gian học (giai đoạn học máy, khoảng 50 kết quả/tuần cho mỗi ad set); đánh giá sớm là sai. Luật phải có trạng thái "Chưa đủ dữ liệu".
- Mục tiêu (target) chi phí/kết quả: chủ đặt theo từng mục tiêu; chưa đặt thì lấy trung vị 30 ngày của chính tài khoản; chưa có lịch sử thì chỉ báo số liệu, không kết luận "Nên tắt".

## Requirements

- Chỉ số chính theo mục tiêu campaign:

| Mục tiêu | Kết quả | Chỉ số phụ |
|---|---|---|
| Nhận diện / lượt xem video | ThruPlay | hook rate = 3s/impressions, hold rate = ThruPlay/3s, CPM |
| Tương tác nhắn tin | cuộc trò chuyện bắt đầu | CTR, chi phí/cuộc trò chuyện |
| Lưu lượng truy cập | lượt nhấp liên kết / xem trang đích | CTR liên kết, CPC |
| Doanh số (có Pixel) | mua hàng | ROAS, CPA |

- Luật (ngưỡng nằm trong config `[ads.rules]`, giá trị mặc định ghi rõ và chủ sửa được):
  - Chưa đủ dữ liệu: chạy < 3 ngày HOẶC impressions < 3.000 HOẶC chi < 1× target.
  - Nên tắt: chi >= 2× target mà 0 kết quả; HOẶC chi phí/kết quả > 2× target sau >= 5 ngày.
  - Cần sửa nội dung: CTR < 50% trung vị tài khoản; hook rate thấp (video không giữ được 3 giây đầu).
  - Cần sửa đối tượng: CPM > 2× trung vị; tần suất > 3 trong 7 ngày (nhàm).
  - Nên tăng ngân sách: chi phí/kết quả <= 70% target, >= 5 ngày, ổn định 3 ngày gần nhất; đề xuất tăng tối đa 20%.
  - Hiệu quả: còn lại, chi phí/kết quả <= target.
- AI (vai trò `writer`, gói thuê bao): nhận kết luận + số liệu + mô tả video (plan, phân tích xu hướng nếu có), trả về lời giải thích tiếng Việt, 1–3 gợi ý sửa cụ thể. AI không được đổi kết luận; nếu lời AI mâu thuẫn kết luận, mã bỏ lời AI và giữ kết luận.
- `ad_actions(id, level, target_external_id, action ENUM(pause, activate, set_budget, create_campaign), params_json, verdict, rule_ids, ai_explanation, status ENUM(proposed, approved, rejected, executed, failed, expired), proposed_at, decided_by, decided_at, executed_at, result_json)`. Một đối tượng chỉ có 1 đề xuất `proposed` cùng loại; đề xuất quá 24 giờ -> `expired`.
- Thẻ Telegram: tên campaign/ad, kết luận, 3 số chính, lời AI, nút Duyệt / Bỏ qua (nút Duyệt chỉ hoạt động từ phase 04; trước đó thẻ chỉ để xem).

## Architecture

```
ads/evaluate.py   # evaluate_ad(row, targets, medians) -> Verdict(rule_ids, label, numbers)  (thuần, không mạng)
ads/explain.py    # build context -> writer.generate_json(AdExplanationSchema) -> kiểm mâu thuẫn
ads/recommend.py  # verdict -> ad_actions(proposed) + chống trùng + hết hạn
job "ads_evaluate" chạy sau mỗi ads_sync
```

## Related code files

Tạo: các file trên, `tests/test_ads_evaluate.py`, `tests/test_ads_recommend.py`. Sửa: migration (thêm `ad_actions` nếu chưa ở phase 02), `config.py` (`[ads.rules]`, `[ads.targets]`), `tg/messages.py`, `tg/callbacks.py`, `api/routes_ads.py`, `ads.html` (cột kết luận).

## Implementation Steps

1. `evaluate.py` + test luật trên số liệu thật đồng bộ ở phase 02 (lưu thành mẫu), cộng bản sao chỉnh 1 trường mỗi ca để chạm từng ngưỡng.
2. `recommend.py` + chống trùng + hết hạn.
3. `explain.py` + schema; test live gọi AI thật (cổng biến môi trường).
4. Thẻ Telegram (chỉ xem) + cột kết luận trên `/ads`.

## Todo list

- [ ] Luật + test ngưỡng
- [ ] ad_actions + chống trùng
- [ ] AI giải thích + kiểm mâu thuẫn
- [ ] Thẻ Telegram + UI

## Success Criteria

- Với dữ liệu thật của tài khoản, mỗi ad có đúng 1 kết luận và danh sách luật đã kích hoạt; chủ đọc hiểu được lý do.
- Ad mới chạy 1 ngày luôn là "Chưa đủ dữ liệu", không bao giờ "Nên tắt".
- AI hết hạn mức -> kết luận vẫn có (luật không cần AI), lời giải thích bổ sung sau.

## Risk Assessment

- Ngưỡng mặc định không hợp ngành trang sức nhỏ ở Việt Nam -> chủ sửa trong config; phase 06 điều chỉnh theo dữ liệu.
- Tên chỉ số "kết quả" của Meta đổi -> đọc từ `actions_json`, ánh xạ một chỗ, test live phát hiện.

## Security Considerations

- Tên campaign, nội dung quảng cáo là dữ liệu ngoài khi đưa vào AI: bọc khối, thoát `<`, như `broll_suggest`.
- Phase này không ghi gì tới Meta.

## Next steps

- Phase 04 cho nút Duyệt thực thi được.
