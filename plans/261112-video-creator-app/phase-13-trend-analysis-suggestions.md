# Phase 13: Phân tích xu hướng + đề xuất

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 12](phase-12-trend-sources.md), [phase 04](phase-04-ai-provider-remix-plan.md), [phase 06](phase-06-approval-queue-telegram-bot.md)
- Docs: [brainstorm mục 3.3, 3.4](../reports/brainstorm-2026-11-12-video-creator.md), [research 02 mục 1, 2](research/researcher-02-video-pipeline-and-packaging.md)

## Overview

- Ngày: 2026-11-12
- Mô tả: lấy top video mỗi lần quét -> phân tích cấu trúc (hook, nhịp cắt, thứ tự cảnh) -> đối chiếu kho shot -> đề xuất "nên làm video X theo công thức Y" gửi Telegram; bấm 1 nút để tạo kịch bản từ đề xuất.
- Ưu tiên: P2
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Nút thắt là LẤY ĐƯỢC FILE video tham khảo. API chính thức hầu như không cho file: IG chỉ trả `media_url` trong một số trường hợp (thường ẩn với video có nhạc bản quyền); Ad Library chỉ có `ad_snapshot_url` (trang HTML); YouTube không cho tải nhưng Gemini đọc được URL công khai (tính năng preview). Vì vậy người dùng đã chốt cho app tự tải (gạch đầu dòng kế tiếp).
- Tải video tham khảo (người dùng chốt 2026-11-12: app tự tải): dùng `yt-dlp` (gọi như tiến trình con, phiên bản ghim trong `pyproject.toml`) cho URL YouTube, Instagram, TikTok của top video -> đưa file qua rea-video. Người dùng đã được báo: vùng xám điều khoản nền tảng, dễ hỏng khi nền tảng đổi.
  - Chỉ tải top N theo điểm (mặc định 5/ngày), không tải hàng loạt; không đăng nhập, không cookie, không proxy, không vượt chặn. Tải lỗi -> lùi về phân tích số liệu + caption (YouTube: Gemini qua URL), không retry dồn dập.
  - File chỉ dùng phân tích nội bộ: lưu `media/reference/`, không bao giờ vào kho shot, không render, không đăng lại; tự xoá sau 7 ngày. Ràng buộc nằm trong code (bảng riêng, không có đường nào từ `reference` sang `shots`).
  - Ad Library: thử `yt-dlp` với `ad_snapshot_url`; nếu không hỗ trợ thì người dùng tự kéo file vào app (nút "Nạp video tham khảo"). Không viết scraper riêng cho trang snapshot.
  - "Chỉ API chính thức" vẫn áp dụng cho ĐĂNG BÀI và lấy số liệu.
- Đường phân tích: item đã tải được file -> `rea-video decompose` bản đầy đủ (có phần packaging, âm thanh), KHÔNG bật `--vlm` (tránh thêm 1 key API riêng) -> provider vai trò `vision` của bộ định tuyến (phase 18, ưu tiên gói thuê bao) đọc `VIDEO.md` + `video/timeline.md` + `storyboard.jpg` và viết `analysis_json`. Bước nhìn ảnh phúc tra đầy đủ của skill chỉ chạy trong phiên Studio (phase 17). Đây là đường CHÍNH khi S1 đạt (rea-video dùng đúng thiết kế: mổ xẻ video tham khảo). Không có file: YouTube qua URL bằng Gemini; còn lại phân tích số liệu + caption. Thư mục kết quả rea-video của mỗi video tham khảo được giữ lại (nhẹ, dạng text + ảnh) để chế độ Studio (phase 17) dùng lại, kể cả sau khi file video đã tự xoá.
- Chỉ học cấu trúc; video dựng 100% bằng footage của mình.

## Requirements

- Job `analyse_trends` sau mỗi lần quét: top K item/nguồn (K mặc định 3) chưa có `analysis_json`.
- `analysis_json`: `{hook, structure: [{t, what}], cut_pace_s, text_style, music_mood, why_it_works}` (schema Pydantic, qua `AIProvider.describe_video` hoặc `generate_json` khi không có video).
- Job `suggest`: prompt gồm các analysis mới + tóm tắt kho shot (tag, số lượng theo loại) -> tối đa N đề xuất/ngày (mặc định 3): `text` (1–2 câu tiếng Việt), `formula_json` (công thức áp được vào planner), shot gợi ý, link video tham khảo. Nếu kho thiếu loại shot cần thiết -> đề xuất ghi rõ "cần quay thêm: ...".
- Telegram: mỗi đề xuất 1 tin, nút "Tạo kịch bản" / "Bỏ qua". "Tạo kịch bản" -> enqueue job `plan` với `formula_json` -> video `planned` đi tiếp luồng thường (vẫn phải duyệt). [Phase 16](phase-16-telegram-control-center.md) nâng tin này thành "Tạo 1 video / Tạo 3 bản / Bỏ qua" với tự dựng và tin tiến độ; ở phase này chỉ làm bản tối thiểu.
- UI: trang đề xuất (trạng thái `new`/`sent`/`accepted`/`dismissed`).
- Mọi lời gọi AI chịu trần ngân sách ngày; hết ngân sách thì hoãn sang hôm sau, không fail ồn ào.

## Architecture

```
trends/download.py    # fetch_reference(item) bằng yt-dlp (top N/ngày) -> media/reference/; job dọn file quá 7 ngày; bảng reference_videos
trends/analyse.py     # analyse_item(item): chọn đường file đã tải (rea-video) | youtube_url (Gemini) | text-only
trends/suggest.py     # make_suggestions(): analysis + shot library summary -> suggestions
ai/gemini.py          # describe_video nhận thêm kiểu nguồn URL YouTube (cùng hàm, tham số video: Path | str)
pipeline/planner.py   # nhận formula tuỳ chọn từ suggestion
telegram_bot.py       # notify_suggestion(), callback sg_ok:<id> / sg_no:<id>
```

Migration `003_suggestion_link.sql` cũng tạo bảng `reference_videos` (id, trend_item_id, path, rea_dir, downloaded_at, deleted_at). Thêm cột `videos.suggestion_id` (cùng migration) để truy vết video sinh từ đề xuất nào (dùng ở phase 15).

## Related code files

Tạo: `src/videocreator/trends/analyse.py`, `trends/suggest.py`, `migrations/003_suggestion_link.sql`, `web/templates/suggestions.html`, `tests/test_suggest_live.py`, `tests/test_suggestion_flow.py`.
Sửa: `ai/gemini.py`, `pipeline/planner.py`, `telegram_bot.py`, `trends/scan.py` (enqueue sau quét), `api/routes_trends.py`.

## Implementation Steps

0. `uv add yt-dlp` (ghim phiên bản). `download.py` + job dọn; thử tải 1 URL thật của mỗi nguồn, ghi nguồn nào tải được vào báo cáo.
1. Mở rộng `describe_video` nhận URL YouTube; kiểm tra chi phí token 1 Shorts (ghi vào báo cáo).
2. `analyse.py` 3 đường (rea-video trên file đã tải là đường chính); lưu `analysis_json`.
3. `suggest.py` + hàm tóm tắt kho shot.
4. Planner nhận `formula`.
5. Telegram + trang đề xuất.
6. Test `-m local` (thêm): file trong `media/reference/` quá 7 ngày bị job dọn xoá, thư mục rea-video còn lại; không có truy vấn nào đưa `reference_videos` vào `shots`.
6b. Test `-m local`: chấp nhận đề xuất -> tạo job plan, trạng thái `accepted`; bỏ qua -> `dismissed`; bấm 2 lần không tạo 2 job (SQLite thật).
7. Test `-m live`: phân tích 1 Shorts công khai thật qua URL -> `analysis_json` hợp schema; sinh đề xuất từ kho shot mẫu -> >= 1 đề xuất tham chiếu tag có thật trong kho.
8. Checklist tay: người dùng đọc 5 đề xuất đầu, đánh giá có dùng được không (tiêu chí chất lượng duy nhất có nghĩa).

## Todo list

- [ ] Tải video tham khảo (yt-dlp, top N, tự xoá 7 ngày)
- [ ] Gemini nhận URL YouTube
- [ ] Phân tích 3 đường, rea-video là đường chính
- [ ] Sinh đề xuất + đối chiếu kho shot
- [ ] Planner nhận formula
- [ ] Telegram + UI đề xuất
- [ ] Test local + live
- [ ] Người dùng đánh giá chất lượng

## Success Criteria

- Mỗi tuần >= 5 đề xuất đến Telegram, mỗi cái có link tham khảo và công thức cụ thể.
- Bấm "Tạo kịch bản" -> trong vài phút có video chờ duyệt dựng theo công thức đó.
- Chi phí phân tích + đề xuất nằm trong trần ngày.

## Risk Assessment

- Tính năng URL YouTube của Gemini là preview: có thể đổi/giới hạn. Lùi: phân tích text-only (tiêu đề, mô tả, metric) -> đề xuất kém cụ thể hơn; nói rõ trong tin nhắn.
- Đề xuất chung chung, vô dụng: rủi ro chất lượng thật, không đo tự động được. Giảm thiểu: prompt buộc tham chiếu shot cụ thể; người dùng chấm 5 cái đầu rồi chỉnh prompt 1 vòng. Không làm vòng phản hồi tự học (YAGNI).
- Phần lớn tín hiệu IG/Ad Library chỉ là text -> giá trị thực chủ yếu đến từ YouTube. Kỳ vọng nên đặt đúng mức.

## Security Considerations

- Video của bên khác chỉ tải để phân tích nội bộ theo các giới hạn ở Key Insights (top N, `media/reference/`, tự xoá sau 7 ngày); không bao giờ đăng lại hay đưa vào kho shot. Lưu lâu dài chỉ có phân tích dạng text + link.
- Caption/tiêu đề từ bên ngoài đi vào prompt = dữ liệu không tin cậy: đặt trong khối phân tách, output luôn validate schema; text hiển thị được escape.

## Next steps

- [Phase 16](phase-16-telegram-control-center.md): điều khiển toàn bộ luồng qua Telegram (làm ngay sau phase này). Phase 15 dùng `suggestion_id` để so hiệu quả.
