# Phase 04: Thực thi có duyệt: bật/tắt, đổi ngân sách, trần chi tiêu

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 03](phase-03-evaluation-and-recommendations.md) (`ad_actions`), [phase 01](phase-01-access-and-api-spike.md) (lệnh ghi đã thử thật)
- Mã liên quan: `src/videocreator/tg/callbacks.py` (kiểm người duyệt), `src/videocreator/approvals.py`, `src/videocreator/db.py` (`record_audit`)

## Overview

- Ngày: 2026-11-14
- Mô tả: người duyệt bấm Duyệt trên Telegram hoặc `/ads` -> app kiểm trần -> gọi API -> đọc lại trạng thái từ Meta -> ghi kết quả. Có thêm nút tay "Tắt"/"Bật"/"Đổi ngân sách" trên `/ads` cho từng campaign/ad set (cũng qua cùng đường kiểm).
- Ưu tiên: P1
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Mọi lệnh ghi đi qua MỘT hàm `execute_action(action_id, approver)`; không route nào gọi API ghi trực tiếp. Dễ kiểm, dễ test.
- Tắt (giảm chi) và bật/tăng (tăng chi) khác rủi ro: trần chỉ chặn hướng tăng; tắt luôn được phép (trừ campaign tạo tay khi cờ `manage_external = false`).
- Tăng ngân sách mạnh làm Meta học lại: giới hạn 20%/lần, tối đa 1 lần/48 giờ mỗi đối tượng.

## Requirements

- Người duyệt: `ads.approver_user_ids` (danh sách riêng, câu 6). Campaign tạo tay được quản lý (câu 4: `manage_external = true`).
- Trần trong `config [ads.caps]`; chủ đã chốt `max_daily_budget_per_campaign = 500000`, `max_total_daily_budget = 5000000` (VND). Thiếu khoá thì mọi thao tác tăng chi bị từ chối:
  - `max_daily_budget_per_campaign`, `max_total_daily_budget` (tổng ngân sách/ngày của mọi campaign app quản lý đang bật), `max_active_campaigns`, `max_campaign_days`, `max_budget_step_pct = 20`, `min_hours_between_budget_changes = 48`.
- `execute_action`:
  1. Khoá hàng đợi một luồng (job worker sẵn có), đọc lại trạng thái hiện tại từ Meta trước khi ghi.
  2. Kiểm: người duyệt thuộc `approver_user_ids`; action còn `proposed` và chưa hết hạn; đối tượng là `managed_by_app` hoặc cờ `manage_external`; trần (tính theo trạng thái vừa đọc).
  3. Gọi API với khoá chống lặp (lưu `request_id`; gọi lại thì không ghi hai lần).
  4. Đọc lại; ghi `executed` + `result_json` nếu khớp, `failed` + lý do nếu không.
  5. `record_audit` mọi bước; thẻ Telegram cập nhật kết quả.
- Nút tay trên `/ads` tạo `ad_actions` rồi đi qua cùng `execute_action`.
- Từ chối kèm lý do tiếng Việt cụ thể ("vượt trần tổng 2.000.000đ/ngày: hiện 1.800.000đ + 300.000đ").

## Architecture

```
ads/caps.py       # check_caps(action, current_state, cfg) -> None | CapViolation   (thuần)
ads/execute.py    # execute_action(paths, action_id, approver) ; AdsClient.post(...)
tg/callbacks.py   # ads_ok:<id> / ads_no:<id>
api/routes_ads.py # POST /ads/actions/{id}/approve|reject ; POST /ads/{level}/{id}/pause|activate|budget
```

## Related code files

Tạo: `ads/caps.py`, `ads/execute.py`, `tests/test_ads_caps.py`, `tests/test_ads_execute_live.py`. Sửa: `ads/client.py` (POST), `tg/callbacks.py`, `api/routes_ads.py`, `ads.html`, `config.py`.

## Implementation Steps

1. `caps.py` + test (trạng thái lấy từ mẫu thật phase 01/02, mỗi ca chỉnh 1 số để chạm trần).
2. `execute.py` + chống lặp + đọc lại.
3. Nút Telegram + UI; người không có quyền bấm -> từ chối, không ghi gì.
4. Test live trên sandbox (hoặc PAUSED tài khoản thật như phase 01): tạo đề xuất pause/set_budget, duyệt, kiểm Meta đã đổi; thử vượt trần -> bị chặn, không request ghi nào được gửi.

## Todo list

- [ ] Trần + test
- [ ] execute_action + chống lặp + đọc lại
- [ ] Nút Telegram/UI + kiểm quyền
- [ ] Test live sandbox

## Success Criteria

- Duyệt "Tắt" trên Telegram -> trong vài giây Ads Manager thấy campaign tắt; thẻ báo "Đã tắt, đã kiểm lại".
- Mọi thao tác tăng chi vượt trần bị chặn trước khi gọi API (đếm request trong test live = 0).
- Bấm Duyệt 2 lần nhanh -> chỉ 1 lệnh ghi.

## Risk Assessment

- Trạng thái Meta đổi giữa lúc đề xuất và lúc duyệt (chủ tự sửa trong Ads Manager) -> bước đọc lại trước khi ghi phát hiện, đánh dấu `expired` thay vì ghi đè.
- Lỗi mạng sau khi Meta đã nhận lệnh -> chống lặp + đọc lại phân biệt "đã đổi" và "chưa đổi".

## Security Considerations

- Chỉ người trong `approver_user_ids` (Telegram) hoặc người đăng nhập UI được duyệt; ghi `decided_by`.
- Không có đường nào để AI hoặc job tự gọi `execute_action` cho hướng tăng chi.

## Next steps

- Phase 05 thêm loại action `create_campaign`.
