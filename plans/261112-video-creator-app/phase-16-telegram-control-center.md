# Phase 16: Điều khiển app qua Telegram

Thứ tự thực hiện: tuần 2, SAU phase 13 và TRƯỚC phase 14 (đánh số 16 vì thêm sau, 2026-11-12).

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 06](phase-06-approval-queue-telegram-bot.md) (bot, duyệt), [phase 10](phase-10-scheduling-retry-alerts.md) (lịch, cảnh báo), [phase 13](phase-13-trend-analysis-suggestions.md) (đề xuất xu hướng), [phase 04](phase-04-ai-provider-remix-plan.md) + [phase 05](phase-05-ffmpeg-render-core.md) (planner, render)
- Docs: [research 02 mục 6](research/researcher-02-video-pipeline-and-packaging.md)

## Overview

- Ngày: 2026-11-12
- Mô tả: Telegram thành bảng điều khiển chính. Hai vòng quyết định đều nằm trong chat: (1) có xu hướng mới hoặc footage mới -> có tạo video không; (2) video dựng xong -> có đăng không. Thêm bộ lệnh điều khiển và thông báo tiến độ.
- Ưu tiên: P1
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Gói code của bot đặt tên `tg/` (không đặt `telegram/` để khỏi nhầm với thư viện python-telegram-bot, vốn import bằng tên `telegram`).
- Hai loại "làm lại" đếm RIÊNG, không chồng nhau: tự làm lại do chấm điểm thấp (`videos.auto_retry_count`, tối đa `quality.max_retries` = 2) và người duyệt bấm `Làm lại` (`videos.redo_count`, tối đa 2). Mỗi lần làm lại tạo kịch bản mới cùng công thức, giữ bản cũ ở trạng thái `superseded` để không gửi duyệt trùng.
- Phase 06, 10, 13 đã có từng mảnh (nút Duyệt/Loại, cảnh báo, nút đề xuất). Phase này nối chúng thành 1 luồng không cần mở UI, KHÔNG viết lại.
- Mọi nút và lệnh gọi lại đúng các hàm UI đang gọi (`approve()`, `reject()`, enqueue job, `slots`). Không có logic nghiệp vụ nào chỉ nằm trong bot (DRY).
- "Tạo video" từ Telegram phải chạy thẳng plan -> render -> gửi duyệt, không dừng ở bước xem kịch bản như UI. Cờ `videos.auto_render = 1`.
- Kịch bản theo xu hướng chọn shot từ TOÀN BỘ kho shot (nhiều footage), không gắn 1 footage: planner thêm chế độ `source = "library"`.
- Việc Telegram KHÔNG làm được: nạp footage (bot chỉ tải được file ~20 MB, chưa xác nhận lại) và kết nối tài khoản mạng xã hội (OAuth). Hai việc này vẫn ở UI.
- Không làm ra lệnh bằng câu tự do qua LLM (YAGNI): nút bấm + lệnh cố định đủ dùng, không tốn tiền, không hiểu nhầm.
- `callback_data` tối đa 64 byte -> chỉ chứa mã hành động + id số.
- Nhóm 2–5 người: tin nhắn quá nhiều sẽ bị tắt thông báo. Giới hạn số tin, gộp tin tiến độ bằng cách sửa 1 tin thay vì gửi tin mới.

## Requirements

Vòng 1, quyết định tạo video:

- Xu hướng mới (từ phase 13), 1 tin mỗi đề xuất, tối đa `telegram.max_trend_msgs_per_day` (mặc định 3): tên brand/kênh, link video, số liệu chính (lượt xem, tương tác, số ngày chạy với quảng cáo), 1–2 câu "vì sao hiệu quả", công thức đề xuất, kho shot có đủ không. Nút: `Tạo 1 video` / `Tạo 3 bản` / `Bỏ qua`.
- Footage mới phân tích xong (từ phase 03, 04): "Footage <tên>: N shot. Tạo mấy video?" Nút: `3 bản` / `5 bản` / `Bỏ qua`.
- Sau khi bấm tạo: bot sửa tin thành "Đang tạo, bởi <tên>" và cập nhật tiến độ ngay trên tin đó (lập kịch bản -> dựng -> xong). Ngôn ngữ lời và caption lấy mặc định `telegram.default_voice_lang` / `default_caption_lang`.
- Thiếu shot cần thiết: tin ghi "cần quay thêm: ...", không có nút tạo.

Vòng 2, quyết định đăng:

- Video dựng xong: `send_video` + caption nền tảng đầu tiên + tên sản phẩm + danh sách tài khoản đích mặc định + khung giờ dự kiến + các cảnh báo (câu không có căn cứ trong thông tin sản phẩm, nền tảng không qua kiểm tra định dạng, có cảnh AI). Nút: `Duyệt, xếp lịch` / `Đăng ngay` / `Loại` / `Làm lại` (tạo lại kịch bản khác cùng công thức, tối đa 2 lần mỗi video) / `Tài khoản` / `Caption`.
- `Tài khoản`: bàn phím bật/tắt từng tài khoản (2–3 x 4 nền tảng), nút `Xong`.
- `Caption`: chọn nền tảng -> bot gửi caption hiện tại -> người duyệt trả lời (reply) tin đó bằng caption mới -> lưu vào `captions_json`. Mục cắt đầu tiên nếu thiếu thời gian (sửa caption trong UI).
- `Loại`: bot hỏi lý do, trả lời hoặc bấm `Không cần lý do`.
- Sau khi đăng: tin "Đã đăng <nền tảng>/<tài khoản>" kèm permalink; lỗi đăng kèm nút `Thử lại` (đã có ở phase 10).

Bộ lệnh (đăng ký bằng `set_my_commands` để hiện trong menu):

| Lệnh | Việc |
|---|---|
| `/menu` | Bàn phím các lệnh chính |
| `/status` | Số video theo trạng thái, job đang chạy, chi phí AI hôm nay/hạn mức (phase 06) |
| `/pending` | Gửi lại video đang chờ duyệt (phase 06) |
| `/schedule` | Lịch đăng hôm nay + ngày mai; mỗi mục có nút `Huỷ` / `Đăng ngay` |
| `/trends` | Gửi lại các đề xuất chưa xử lý |
| `/scan` | Quét xu hướng ngay (bình thường chạy theo lịch) |
| `/create` | Liệt kê 5 footage mới nhất, bấm để tạo video |
| `/pause`, `/resume` | Tạm dừng / chạy lại việc đăng tự động (video đã xếp lịch giữ nguyên, bỏ lỡ thì báo) |
| `/report` | Báo cáo ngày (phase 10), báo cáo tuần (phase 15) |
| `/help` | Danh sách lệnh |

Mẫu tương tác lấy ý tưởng từ Muse2Tele (tự viết lại bằng python-telegram-bot; KHÔNG dùng code, trình duyệt giả lập hay cách đăng bài của repo đó, xem plan.md):

- Nhóm duyệt bật Topics: mỗi mảng 1 topic do bot tạo bằng `/setup` (Xu hướng, Chờ duyệt, Đã đăng, Việc tay, Lỗi và cảnh báo, Báo cáo) để tin không lẫn; nhóm không bật Topics thì gửi chung như cũ.
- Phản ứng trạng thái trên tin nhắn lệnh của người dùng: 👀 đã nhận, 👍 đang chạy, 👌 xong, 👎 lỗi (kèm tin lỗi).
- Một tin tiến độ "⚙️ <việc>: <bước>" được sửa liên tục rồi xoá khi xong (đã có ở `progress.py`).
- Gộp album: nhiều bản của cùng 1 đề xuất gửi thành 1 album kèm 1 bàn phím chọn bản.
- Trả lời (reply) vào tin nào thì lệnh áp vào đúng video/đề xuất của tin đó.
- Chấm điểm tự động trước khi gửi người duyệt: sau khi dựng, provider vai trò `vision` (qua bộ định tuyến phase 18) xem video + kịch bản và chấm theo thang 10 (mở đầu có hút không, sản phẩm có rõ không, chữ có trong vùng an toàn không, lời có khớp hình không). Dưới `quality.min_score` (mặc định 8) thì tự "Làm lại" tối đa `quality.max_retries` (mặc định 2) trong hạn mức AI; vẫn không đạt thì vẫn gửi duyệt kèm điểm và lý do. Điểm hiện trong tin duyệt. Chấm điểm KHÔNG thay người duyệt.
- "Gói chỉ dẫn" (preset): bộ chỉ dẫn đặt tên sẵn cho writer (giọng thương hiệu, kiểu video: ra mắt, quy trình chế tác, khuyến mãi), lưu trong DB, chọn khi bấm tạo video hoặc trong `/create`; xuất/nhập dạng JSON.

Thông báo và giới hạn:

- Giờ yên lặng `telegram.quiet_hours` (mặc định 22:00–07:00): hoãn tin xu hướng và tin "video xong"; lỗi đăng và cảnh báo token vẫn gửi.
- Mọi hành động ghi `audit_log` (ai, lúc nào, hành động, đối tượng).

## Architecture

```
telegram_bot.py        # giữ: khởi động, allowlist, send_text
tg/handlers.py   # lệnh
tg/callbacks.py  # router callback: "<mã>:<id>[:<tham số>]" -> gọi hàm nghiệp vụ
tg/messages.py   # dựng nội dung tin + bàn phím (hàm thuần, test được không cần mạng)
tg/progress.py   # sửa 1 tin tiến độ theo job
pipeline/planner.py    # thêm source="library" + auto_render
approvals.py           # thêm redo(video_id, by), post_now(video_id, by)
posting/scheduler.py   # cờ paused (bảng settings), kiểm tra trước mỗi lần đăng
```

Migration `004_telegram_control.sql`: `videos.auto_render`, `videos.redo_count`, `videos.auto_retry_count`, `videos.supersedes_id`, `videos.quality_score`, `videos.quality_notes`, `videos.tg_message_id`; trạng thái video `scoring` và `superseded`; bảng `presets` (gói chỉ dẫn), `audit_log`; khoá `settings.posting_paused`.
Trạng thái chờ trả lời (lý do loại, caption mới): bảng `tg_pending_input` (chat_id, user_id, kind, ref_id, hết hạn sau 10 phút), không giữ trong bộ nhớ để sống qua lần khởi động lại.

## Related code files

Tạo: `src/videocreator/tg/handlers.py`, `tg/callbacks.py`, `tg/messages.py`, `tg/progress.py`, `migrations/004_telegram_control.sql`, `tests/test_tg_messages.py`, `tests/test_tg_flows.py`, `tests/test_tg_control_live.py`.
Sửa: `telegram_bot.py` (tách handler ra gói `tg/`), `pipeline/planner.py`, `approvals.py`, `posting/scheduler.py`, `trends/suggest.py` (dùng mẫu tin mới), `pipeline/describe.py` (hook báo footage mới), `config.py`.

## Implementation Steps

1. Tách `telegram_bot.py` thành gói `tg/`; router callback 1 chỗ, kiểm tra allowlist 2 lớp ở đúng 1 hàm.
2. `messages.py`: mẫu tin xu hướng, footage mới, video xong, lịch, kèm bàn phím.
3. Planner `source="library"` + `auto_render`; hook footage mới và đề xuất mới gửi tin.
4. Vòng 2: `Đăng ngay`, `Làm lại`, bàn phím tài khoản, hỏi lý do loại.
5. Lệnh `/schedule`, `/trends`, `/scan`, `/create`, `/pause`, `/resume`, `/menu`, `/help`; `set_my_commands`.
6. `progress.py`; giờ yên lặng; `audit_log`.
7. Sửa caption qua reply (cắt được).
8. Test `-m local` (SQLite thật, không cần mạng): gọi thẳng hàm callback với dữ liệu update thật đã lưu từ 1 lần bấm thật (`tests/samples/tg_updates/*.json`, ghi lại ở bước 9) -> đúng chuyển trạng thái; người ngoài `approver_user_ids` bị từ chối; bấm 2 lần không tạo 2 job; `/pause` chặn đăng; `Làm lại` lần 3 bị từ chối.
9. Test `-m live` (cần bot + nhóm thử): gửi từng loại tin, khẳng định có message id và bàn phím đúng số nút.
10. Checklist tay trên điện thoại: đi hết 2 vòng không mở UI: nhận tin xu hướng -> Tạo 1 video -> nhận video -> đổi tài khoản -> Duyệt -> thấy trong `/schedule` -> nhận tin đã đăng có permalink.

## Todo list

- [ ] Tách gói `tg/` + router callback
- [ ] Mẫu tin + bàn phím
- [ ] Planner theo kho shot + tự dựng
- [ ] Tin xu hướng mới và footage mới có nút tạo
- [ ] Đăng ngay, Làm lại, chọn tài khoản, lý do loại
- [ ] Bộ lệnh + menu
- [ ] Tiến độ, giờ yên lặng, audit log
- [ ] Topics theo mảng, phản ứng trạng thái, album, reply theo ngữ cảnh
- [ ] Chấm điểm tự động + tự làm lại có giới hạn
- [ ] Gói chỉ dẫn (preset) + xuất/nhập JSON
- [ ] Sửa caption qua reply (cắt được)
- [ ] Test local + live + checklist tay

## Success Criteria

- Một ngày làm việc bình thường (không nạp footage mới) chạy hoàn toàn từ điện thoại: 0 lần mở UI.
- Từ lúc bấm `Tạo 1 video` đến lúc nhận video chờ duyệt: < 5 phút với video 20–30 giây.
- Nhóm nhận không quá 3 tin xu hướng mỗi ngày; không có tin nào trong giờ yên lặng trừ lỗi.
- Mọi hành động trong `audit_log` có tên người bấm.

## Risk Assessment

- Phình phạm vi: bot dễ thành UI thứ hai. Giới hạn cứng: chỉ các nút và lệnh liệt kê ở trên; việc khác làm trong UI.
- Tự dựng không qua bước xem kịch bản -> video kém hơn, tốn AI. Giảm thiểu: `Làm lại` có giới hạn, hạn mức ngày vẫn áp dụng, người duyệt vẫn là cửa cuối.
- Bấm nhầm `Đăng ngay` trong nhóm: hỏi xác nhận 1 bước (`Chắc chắn đăng ngay?`).
- Phase này 1.75–2.25 ngày sau khi thêm các mẫu tương tác và chấm điểm (xem plan.md). Cắt theo thứ tự: gói chỉ dẫn, album, sửa caption qua reply, `/create`, Topics.
- Chấm điểm tự động tốn AI và có thể chấm sai: giới hạn số lần làm lại, luôn gửi người duyệt, theo dõi tỉ lệ video điểm cao bị người duyệt loại để chỉnh rubric.

## Security Considerations

- Telegram giờ điều khiển được việc đăng bài: tài khoản Telegram của người duyệt bị chiếm = kẻ khác đăng lên kênh thương hiệu. Khuyến nghị bật xác minh 2 bước Telegram cho mọi người duyệt; ghi trong `docs/install.md`.
- Mọi callback và lệnh kiểm tra cả chat ID lẫn user ID; lệnh thay đổi trạng thái (`/pause`, `/scan`, `/create`, mọi nút) chỉ dành cho `approver_user_ids`.
- Nội dung trả lời của người dùng (caption, lý do) là dữ liệu: escape khi hiển thị, cắt theo giới hạn ký tự nền tảng, không đưa vào lệnh hệ thống.
- Bot không bao giờ gửi token, key hay đường dẫn hệ thống vào chat.

## Next steps

- Phase 17 (Studio) là phase kế tiếp; nó thêm trả lời "Sửa: <prompt>" vào bot.
- Phase 14 (cảnh phụ AI, tuần 4): thêm nút `Tạo cảnh phụ` vào `/menu` nếu cần.
- Ngoài phạm vi: ra lệnh bằng câu tự do qua LLM; nạp footage qua Telegram.
