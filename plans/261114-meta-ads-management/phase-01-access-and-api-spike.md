# Phase 01: Kiểm chứng quyền truy cập và Marketing API (cổng vào)

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: chủ chuẩn bị Business Manager, tài khoản quảng cáo, thanh toán (câu hỏi 1–3 trong plan.md). Liên quan S2/S3 của [phase 01 plan app](../261112-video-creator-app/phase-01-verification-spikes.md) (token Meta cho đăng bài, chưa xong).
- Docs: [research 01](research/researcher-01-meta-marketing-api-2026.md)

## Overview

- Ngày: 2026-11-14
- Mô tả: trả lời bằng chạy thật mọi điểm [chưa xác minh] trước khi viết mã sản phẩm. Không viết module `ads/` ở phase này, chỉ script thử trong `spikes/ads/` và báo cáo.
- Ưu tiên: P1 (chặn mọi phase sau)
- Trạng thái triển khai: chưa bắt đầu, chờ chủ
- Trạng thái review: chưa review

## Key Insights

- Dự án này nhiều lần viết mã theo tài liệu rồi sai khi chạy thật (MoneyPrinterTurbo, chỉ số Instagram). Với tiền thật, mọi trường và đơn vị phải được thấy trên phản hồi thật trước.
- Tài khoản sandbox (nếu còn) cho thử tạo campaign không tốn tiền. Không có sandbox -> thử tạo campaign PAUSED trên tài khoản thật với ngân sách tối thiểu rồi xoá, KHÔNG bao giờ bật.
- Quản lý tài khoản của chính mình chạy được ở mức truy cập thấp (Limited) mà không cần App Review; giới hạn lượt gọi thấp quyết định nhịp đồng bộ.

## Requirements

Báo cáo `reports/01-access-and-api-results.md` trả lời đủ, kèm phản hồi thật (đã xoá token/id nhạy cảm):

1. Cách lấy token: system user + quyền `ads_management`, `ads_read` (và `pages_read_engagement` nếu dùng bài đã đăng làm quảng cáo); hạn token; mức truy cập hiện tại của app.
2. Phiên bản Graph dùng cho quảng cáo (`ADS_GRAPH_API_VERSION`), hạn ngưng hỗ trợ.
3. Đọc: danh sách campaign/ad set/ad với `effective_status`, `daily_budget`/`lifetime_budget`, `objective`; insights `level=ad`, `time_increment=1`, các trường video (ThruPlay, p25–p100, 3 giây) và hành động nhắn tin (`onsite_conversion.messaging_conversation_started_7d` hoặc tên hiện hành).
4. Ghi (sandbox hoặc PAUSED): tạo campaign ODAX theo cấu trúc Advantage+ (ngân sách cấp campaign, Advantage+ audience, placement tự động); tạo ad set nhắn tin (`destination_type`); tạo ad từ bài Page sẵn có (`object_story_id`) và từ video tải lên; đổi `status`; đổi `daily_budget`; xoá.
5. Đơn vị tiền VND trong `daily_budget` và ngân sách tối thiểu/ngày; tiền tệ và múi giờ của tài khoản.
6. Header giới hạn lượt gọi (`x-business-use-case-usage`, `x-ad-account-usage`) và chi phí một lượt đồng bộ đầy đủ.
7. Có đọc được gợi ý tối ưu của Meta qua API không.

## Architecture

```
spikes/ads/probe_read.py      # đọc account, campaigns, insights -> lưu JSON mẫu (đã che id)
spikes/ads/probe_write.py     # tạo PAUSED (sandbox ưu tiên) -> đổi status/budget -> xoá
spikes/ads/samples/*.json     # phản hồi thật, làm mẫu test cho phase 02-05
```

## Related code files

Tạo: `spikes/ads/*`, `plans/261114-meta-ads-management/reports/01-access-and-api-results.md`. Đọc: `src/videocreator/posting/meta_auth.py` (xử lý lỗi Graph dùng lại được), `src/videocreator/secrets_store.py`.

## Implementation Steps

1. Chủ: tạo/kiểm Business Manager, tài khoản quảng cáo (tiền VND, múi giờ Asia/Ho_Chi_Minh), thanh toán; tạo system user, gán tài khoản quảng cáo + Page; cấp token cho app.
2. Lưu token vào kho bí mật (`META_ADS_SYSTEM_TOKEN`, `META_AD_ACCOUNT_ID`), không vào file.
3. Chạy `probe_read.py` trên tài khoản thật (chỉ đọc). Lưu mẫu.
4. Tìm/tạo tài khoản sandbox; chạy `probe_write.py` ở đó. Không có sandbox: chạy trên tài khoản thật, chỉ PAUSED, ngân sách tối thiểu, xoá ngay; chủ chứng kiến.
5. Ghi báo cáo, trả lời 7 mục, cập nhật research 01 các điểm đã xác minh.

## Todo list

- [ ] Chủ chuẩn bị tài khoản + token
- [ ] Đọc thật + lưu mẫu
- [ ] Ghi thử (sandbox / PAUSED) + xoá
- [ ] Báo cáo 7 mục

## Success Criteria

- Mỗi mục 1–7 có câu trả lời kèm phản hồi thật; không còn điểm [chưa xác minh] nào chặn phase 02–05.
- Không phát sinh đồng chi tiêu nào (kiểm "Số tiền đã chi" của tài khoản trước/sau).

## Risk Assessment

- Chủ chưa có Business Manager/thanh toán -> chặn cả kế hoạch; phase 02 vẫn chạy được nếu chỉ có quyền đọc.
- Sandbox không còn -> thử trên tài khoản thật có rủi ro bật nhầm; giảm bằng: script không có lệnh đặt `ACTIVE`, ngân sách tối thiểu, xoá ngay.
- Business Verification bị đòi bất ngờ -> chờ Meta, ngoài tầm kiểm soát.

## Security Considerations

- Token system user không hết hạn: quyền rất rộng. Chỉ trong kho bí mật mã hoá; không log; mẫu JSON che `account_id`, `page_id`, token.
- Script ghi không chứa giá trị `ACTIVE` ở bất kỳ đâu (kiểm bằng grep trước khi chạy).

## Next steps

- Phase 02 dùng mẫu thật vừa lưu cho test.
