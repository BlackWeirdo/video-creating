# Phase 05: Đề xuất và lên campaign theo từng video

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 04](phase-04-approved-execution.md) (thực thi có duyệt), [phase 01](phase-01-access-and-api-spike.md) (tạo campaign/ad set/ad đã thử thật), plan app phase 07 (bài đã đăng lên Page để dùng làm quảng cáo)
- Mã liên quan: `videos.plan_json`, `suggestions.formula_json`, `trend_items.analysis_json`, `post_metrics`, `src/videocreator/pipeline/broll_suggest.py` (khuôn AI + kiểm trong mã)

## Overview

- Ngày: 2026-11-14
- Mô tả: với mỗi video đã duyệt/đã đăng, app phân loại nội dung, chọn chiến thuật từ "sách chiến thuật" trong mã, rồi AI điều chỉnh theo số liệu thật của tài khoản và viết đề xuất cụ thể: mục tiêu, ngân sách/ngày, số ngày, đối tượng, vị trí, nội dung chữ (2–3 biến thể), dùng bài đã đăng hay video mới. Duyệt -> app tạo trọn campaign ở trạng thái PAUSED -> duyệt lần hai để bật.
- Ưu tiên: P2
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Gợi ý chạy quảng cáo hiệu quả nhất cho shop nhỏ: đẩy bài tự nhiên đang tốt (đã có `post_metrics` 24h/72h/7d) thay vì đoán. Bài vượt trung vị lượt xem/tương tác -> ứng viên số 1.
- Sách chiến thuật cố định trong mã cho tuần đầu (chưa có dữ liệu); AI chỉ được chọn trong khoảng sách cho phép và trong trần.
- Advantage+ (ngân sách cấp campaign, đối tượng và vị trí tự động) mặc định: Meta tối ưu miễn phí; app chỉ thêm giới hạn cứng tối thiểu (quốc gia, độ tuổi tối thiểu nếu chủ muốn).

## Requirements

- Kênh bán (chủ chốt, câu 1): nhắn tin Messenger/Instagram và website có Meta Pixel -> cả hai mục tiêu nhắn tin và Doanh số đều dùng được; AI chọn theo loại nội dung và kết quả quá khứ.
- Sách chiến thuật ban đầu:

| Loại nội dung (từ plan/formula) | Mục tiêu campaign | Kết quả tối ưu | Thời gian | Ghi chú |
|---|---|---|---|---|
| Quy trình chế tác / ASMR (thu hút) | Nhận diện hoặc Tương tác (xem video) | ThruPlay | 5–7 ngày | Tạo tệp người xem video 50% để bám đuổi |
| Ra mắt / giới thiệu sản phẩm | Tương tác nhắn tin (hoặc Doanh số nếu có Pixel) | cuộc trò chuyện / mua | 7 ngày | Lời kêu gọi nhắn tin hỏi giá |
| Bài tự nhiên đang tốt | Giữ mục tiêu theo loại nội dung, dùng chính bài (`object_story_id`) | như trên | 3–5 ngày | Giữ lượt thích/bình luận sẵn có |
| Bám đuổi (người đã xem/nhắn) | Tương tác nhắn tin / Doanh số | cuộc trò chuyện / mua | liên tục, ngân sách nhỏ | Cần tệp đối tượng tuỳ chỉnh (điều khoản Meta) |

- Đầu vào AI: loại nội dung, mô tả video (plan, caption từng nền tảng sẵn có), phân tích xu hướng gốc nếu có, thông tin sản phẩm (CHỈ dữ liệu chủ nhập, theo luật app), số liệu tự nhiên của bài, kết quả quảng cáo quá khứ theo loại nội dung (phase 06), trần.
- Đầu ra (schema): `objective`, `optimization_goal`, `daily_budget`, `days`, `audience_notes`, `placements = "advantage"`, `creative_source ∈ {existing_post, new_video}`, `primary_texts[2..3]`, `headline`, `call_to_action`, `kpi_target`, `reason`.
- Mã kiểm: mục tiêu thuộc sách cho loại nội dung; ngân sách và số ngày trong trần; chữ quảng cáo không chứa thông tin sản phẩm ngoài dữ liệu chủ nhập (dùng bộ kiểm sự thật sẵn có của planner); không hứa hẹn/so sánh bị chính sách quảng cáo Meta cấm (danh sách cụm từ cấm ngắn trong mã).
- Duyệt 1 (đề xuất) -> tạo campaign + ad set + ad PAUSED, đặt tên `VC#<video_id>-<loại>-<ngày>`, `managed_by_app = 1`. Duyệt 2 -> bật (qua trần của phase 04).
- Nút "Đề xuất quảng cáo" trên trang video và trên thẻ video đã đăng ở Telegram; job tự đề xuất cho bài tự nhiên vượt ngưỡng (tối đa N đề xuất/ngày).

## Architecture

```
ads/playbook.py   # CONTENT_PLAYBOOK + classify_content(video) (thuần)
ads/propose.py    # context -> writer.generate_json(CampaignProposalSchema) -> kiểm -> ad_actions(create_campaign)
ads/create.py     # tạo campaign/ad set/ad PAUSED từ action đã duyệt (gọi từ execute_action)
```

## Related code files

Tạo: các file trên, `tests/test_ads_playbook.py`, `tests/test_ads_propose.py`, `tests/test_ads_create_live.py`. Sửa: `ads/execute.py` (nhánh `create_campaign`), `tg/messages.py`, `tg/callbacks.py`, `api/routes_ads.py`, trang video/approval (nút), `config.py` (`[ads.proposals]`).

## Implementation Steps

1. `playbook.py` + phân loại từ dữ liệu thật (plan/formula của các video hiện có).
2. `propose.py` + schema + kiểm; chạy thật với 2–3 video đã có, lưu đầu ra AI thật làm mẫu test.
3. `create.py` trên sandbox; ghi lại id, kiểm cấu trúc Advantage+ đúng như phase 01.
4. Nút + thẻ Telegram 2 bước duyệt.
5. Test local trên mẫu thật (kiểm trần, kiểm mục tiêu ngoài sách bị loại, cụm từ cấm bị loại); test live tạo PAUSED trên sandbox.

## Todo list

- [ ] Sách chiến thuật + phân loại
- [ ] Đề xuất AI + kiểm + mẫu thật
- [ ] Tạo PAUSED trên sandbox
- [ ] 2 bước duyệt (UI + Telegram)
- [ ] Test local + live

## Success Criteria

- Từ 1 video đã đăng: bấm "Đề xuất quảng cáo" -> trong 1–3 phút có thẻ đề xuất đọc hiểu được; duyệt -> Ads Manager có campaign PAUSED đúng cấu trúc; duyệt lần 2 -> bật.
- Đề xuất vượt trần hoặc sai mục tiêu không bao giờ tới bước tạo.

## Risk Assessment

- Chính sách quảng cáo Meta từ chối nội dung -> trạng thái ad `DISAPPROVED` hiện ở `/ads` + thẻ Telegram; không tự sửa.
- Chưa có Pixel/website -> chỉ dùng mục tiêu nhắn tin/xem video; Doanh số bị ẩn khỏi sách.
- Phụ thuộc plan app phase 07 (đăng lên Page) cho `existing_post`; chưa có thì chỉ `new_video` (tải video lên tài khoản quảng cáo).

## Security Considerations

- Video tải lên chỉ là bản master đã được người duyệt (`BR-PRD`), không dùng video tham khảo (`BR-REF-02`).
- Chữ quảng cáo do AI viết là đề xuất; người duyệt thấy toàn văn trước khi tạo.

## Next steps

- Phase 06 dùng kết quả các campaign này để chỉnh đề xuất sau.
