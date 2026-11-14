# Phase 17: Studio, dựng lại video theo prompt bằng rea-video + video-shotcraft

Thứ tự thực hiện: đầu tuần 3, SAU phase 16 và TRƯỚC phase 14 (thêm 2026-11-12 theo yêu cầu người dùng). Điều kiện vào phase: spike S11 ở [phase 01](phase-01-verification-spikes.md) đạt.

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 03](phase-03-footage-import-shot-library.md) (kho shot, sản phẩm), [phase 04](phase-04-ai-provider-remix-plan.md) (budget, luật sản phẩm), [phase 06](phase-06-approval-queue-telegram-bot.md) (duyệt), [phase 13](phase-13-trend-analysis-suggestions.md) (video xu hướng đã tải), [phase 16](phase-16-telegram-control-center.md) (Telegram)
- Skill đã cài ở máy người dùng: `~/.claude/skills/rea-video/`, `~/.claude/skills/video-shotcraft/` (đã đọc `SKILL.md` của cả hai ngày 2026-11-12)
- Docs phải đọc trước khi viết: Claude Agent SDK `https://code.claude.com/docs/en/agent-sdk`; skill `claude-api` (model, giá); `video-shotcraft/references/pipeline.md`, `guided-free-creation.md`, `final-review.md`, `music-beat-sync.md`; `rea-video/references/remake.md`, `review.md`

## Overview

- Ngày: 2026-11-12
- Mô tả: chế độ dựng thứ hai bên cạnh FFmpeg. Người dùng viết prompt, chọn footage và (tuỳ chọn) 1 video xu hướng; một agent chạy trong app, nạp đủ 2 skill, tự phân tích video tham khảo, viết kịch bản mới, dựng bằng Remotion với footage thật, rồi đưa vào hàng chờ duyệt. Sửa tiếp bằng prompt.
- Ưu tiên: P1
- Trạng thái triển khai: chưa bắt đầu
- Trạng thái review: chưa review

## Key Insights

- Hai skill là hướng dẫn cho AGENT, không phải thư viện. Dùng "triệt để" = phải có agent đọc `SKILL.md` và làm theo: bước nhìn ảnh phúc tra của rea-video (`review` / `apply-review`), bước chọn thẻ shot, viết code Remotion và QA khung hình của video-shotcraft đều do agent làm. Cách tích hợp đúng: nhúng Claude Agent SDK (Claude Code dạng thư viện, có sẵn công cụ đọc/ghi file, chạy lệnh, nạp skill).
- Đính chính đánh giá cũ (brainstorm mục 3.6): video-shotcraft CÓ dùng được footage mp4. `assets/lib/ClipCard.tsx` bọc mp4 bằng `OffthreadVideo` để các thẻ shot điều khiển chuyển động máy. Kèm `Caption`, `FlashCut`, `DigitRoll`, `FlatPanel`, `VerticalTicker`, phân tích nhịp nhạc, tìm SFX, QA khung hình, trình sửa Workbench.
- rea-video có sẵn đúng thứ cần cho "dựng lại bằng nguyên liệu của mình": `decompose` (tách shot, tách giọng/nhạc/SFX, `VIDEO.md`), `video/content.md` (đường kể chuyện: mỗi shot thu hút, bổ sung hay kết luận), `video/packaging.md` (trục thời gian phụ đề, chữ, sticker), `rea-video assemble` (lắp footage của người dùng vào lại timeline gốc).
- Ưu tiên gói thuê bao (chốt 2026-11-13, [phase 18](phase-18-subscription-first-routing.md)): phiên Studio mặc định chạy bằng Claude Code không tương tác (`claude -p`, binary chính thức, đăng nhập gói Pro/Max của chủ máy, nạp 2 skill từ thư mục dự án). Claude Agent SDK + API key là đường DỰ PHÒNG theo chính sách `api_fallback`. `studio/agent.py` che 2 đường sau 1 hàm. Việc nhìn ảnh phúc tra của rea-video do chính agent làm, không cần key VLM. Hạn mức Pro có thể không đủ cho phiên dài: đo ở S11/S13, có thể cần Max.
- Không thay FFmpeg. Hai chế độ sống song song: "Nhanh" (phase 05, rẻ, tất định, cho 5–10 video/ngày) và "Studio" (phase này, đắt và chậm hơn, cho video cần thiết kế riêng). Chọn theo từng video.
- Giảm chi phí lâu dài: bản Studio người dùng ưng được lưu thành MẪU (dự án Remotion + props JSON). Video sau dùng lại mẫu bằng `remotion render --props`, không cần agent. Agent thiết kế 1 lần, dùng nhiều lần.
- Template gốc của video-shotcraft là 1920x1080 ngang cho sản phẩm phần mềm. Dọc 1080x1920 với footage trang sức là dùng ngoài thiết kế gốc: chất lượng phải đo ở S11, không giả định.
- CHƯA xác nhận (đo ở S11): Agent SDK nạp skill từ thư mục dự án thế nào; chi phí và thời gian 1 lần chạy; Remotion + Chrome headless trên Windows; giấy phép Remotion cho công ty (miễn phí cho cá nhân và nhóm nhỏ, công ty lớn hơn phải mua).

## Requirements

Đầu vào 1 phiên Studio:

- Prompt tự do (tiếng Việt hoặc Anh), ví dụ "dựng theo nhịp video này nhưng mở đầu bằng cận cảnh chạm khắc, tông ấm, chữ ít".
- 1+ footage hoặc danh sách shot từ kho; sản phẩm liên quan (kéo theo `products.facts_json`).
- Tuỳ chọn: 1 video xu hướng đã có trong `media/reference/` (phase 13) hoặc file người dùng nạp.
- Tuỳ chọn: nhạc/SFX từ thư viện người dùng đã nạp; ngôn ngữ lời; thời lượng; mẫu đã lưu.

Luồng agent (mỗi bước ghi tiến độ ra UI và Telegram):

1. Phân tích: dùng lại thư mục kết quả rea-video đã có từ phase 13 nếu video tham khảo đã được phân tích (`reference_videos.rea_dir`); chưa có thì `rea-video decompose` -> agent làm đủ bước nhìn ảnh phúc tra -> `apply-review`. Đọc `VIDEO.md` theo lớp như skill hướng dẫn.
2. Kịch bản: giữ đường kể chuyện và nhịp của video tham khảo, thay toàn bộ hình bằng shot trong kho, lời chỉ từ `facts_json`. Xuất `script.json` cùng schema `plan_json` của phase 04 (dùng chung validate luật sản phẩm).
3. Điểm dừng xác nhận: hiện kịch bản + bảng "shot tham khảo -> shot của mình" cho người dùng; bấm Tiếp hoặc gõ prompt sửa. (Bỏ qua được bằng tuỳ chọn "chạy thẳng".)
4. Dựng: agent theo video-shotcraft, tạo dự án Remotion trong `media/studio/<id>/`, footage qua `ClipCard`/`OffthreadVideo`, phụ đề `Caption`, chuyển cảnh và chữ từ thẻ shot, cắt theo nhịp nhạc, SFX. Khung 1080x1920, 30 fps.
5. QA: bước `final-review` của skill + bộ kiểm tra của app (xem dưới) -> render mp4 -> `export.normalize()` + `preflight.check()` của phase 05 (cùng bản master đa nền tảng như chế độ Nhanh) -> video vào `pending_approval` như mọi video khác.
6. Sửa tiếp: prompt mới trên cùng phiên (giữ ngữ cảnh), ví dụ "cảnh 2 chậm lại", "đổi nhạc". Mỗi lần sửa ra 1 phiên bản, giữ bản cũ.

Luật độ chính xác sản phẩm (đưa vào system prompt của agent VÀ kiểm tra bằng code sau khi agent xong):

- Hình sản phẩm chỉ từ file trong kho shot; cấm ảnh/clip AI, cấm gọi `rea-video remake-run` và capsule-cinema (sinh AI, tốn tiền).
- Trên thành phần chứa footage `has_product = 1`: cấm CSS `filter`, `mix-blend-mode`, `opacity` < 1, `playbackRate` khác 1, lớp phủ màu. Bộ kiểm tra quét file `.tsx` sinh ra; vi phạm -> trả lại agent sửa 1 lần, vẫn sai -> job `failed`.
- Chuyển động máy của `ClipCard` (zoom, nghiêng 2.5D) được phép nhưng sản phẩm phải nằm trọn khung ở khung giữa mỗi shot; ghi chú trong tin duyệt "có hiệu ứng chuyển động trên footage".
- Lời và caption qua đúng bước đối chiếu `facts_json` của phase 04.

Khác:

- Trần `budget.studio_daily_usd` (mặc định lấy từ S11, tạm 10 USD) và trần mỗi lần chạy (số lượt agent tối đa + USD tối đa); hiện ước tính trước khi bấm.
- Nút "Lưu làm mẫu" và "Dựng từ mẫu" (chọn shot + lời mới, không gọi agent).
- Nút "Mở Workbench" (trình sửa của video-shotcraft, `node workbench/scripts/open.mjs <project>`) để chỉnh tay; cắt được.
- Telegram: trả lời (reply) tin video bằng "Sửa: <prompt>" -> chạy bước 6; lệnh `/studio` chỉ mở link tới trang Studio (nhập prompt dài trên UI). Cắt được.

## Architecture

```
studio/agent.py        # bọc Claude Agent SDK: tạo phiên, system prompt (luật sản phẩm + đường dẫn), giới hạn công cụ, stream tiến độ
studio/session.py      # bảng studio_sessions: id, video_id, prompt, ref_item_id, session_ref (để nối tiếp), status, cost_usd, versions_json
studio/checks.py       # quét .tsx theo luật sản phẩm; ffprobe đầu ra; đối chiếu file nguồn chỉ nằm trong kho shot
studio/templates.py    # lưu mẫu (bảng studio_templates), dựng từ mẫu bằng `npx remotion render --props`
vendor/skills/rea-video/, vendor/skills/video-shotcraft/   # bản sao ghim theo commit, kèm LICENSE (skill rea-video chỉ là hướng dẫn; CLI `rea-video` là gói Python đã cài từ phase 03)
api/routes_studio.py + web/templates/studio.html           # form prompt, tiến độ, phiên bản, điểm dừng xác nhận
```

- Agent chạy như 1 job trong worker sẵn có (1 phiên Studio tại 1 thời điểm).
- Thư mục làm việc của agent: `media/studio/<id>/`; footage được liên kết chỉ-đọc vào `public/`.
- Công cụ cho phép: đọc/ghi/sửa file trong thư mục làm việc, nạp skill, và lệnh shell theo danh sách trắng: `rea-video`, `ffmpeg`, `ffprobe`, `node`, `npx remotion`, `npm ci` (trong thư mục làm việc), `uv run` cho script của skill. Không web, không lệnh khác.
- Model agent đọc từ config (`studio.model`, mặc định `claude-opus-5-5`); chi phí ghi vào `ai_usage` kind `studio`.
- Node.js + Chrome headless của Remotion: cài lần đầu khi mở Studio (không nhét vào bộ cài chính), có nút kiểm tra môi trường.

## Related code files

Tạo: `src/videocreator/studio/agent.py`, `studio/session.py`, `studio/checks.py`, `studio/templates.py`, `api/routes_studio.py`, `web/templates/studio.html`, `migrations/005_studio.sql`, `vendor/skills/` (2 skill), `tests/test_studio_checks.py`, `tests/test_studio_live.py`, `reports/17-studio-spike.md`.
Sửa: `ai/budget.py` (trần Studio), `pipeline/planner.py` (xuất hàm validate dùng chung), `tg/callbacks.py` (reply "Sửa:"), `config.py`, `docs/install.md` (Node.js, giấy phép Remotion).

## Implementation Steps

1. Đọc docs Agent SDK và các file tham chiếu của 2 skill nêu ở Context links; ghi cách nạp skill, giới hạn công cụ, nối tiếp phiên vào `reports/17-studio-spike.md`. Không đoán API.
2. Sao 2 skill vào `vendor/skills/` (ghim commit), cài `rea-video` CLI và `npm ci` cho template.
3. `studio/agent.py`: 1 phiên tối thiểu chạy bước 1 (phân tích + phúc tra) trên 1 video tham khảo thật; stream tiến độ.
4. Bước 2–3: kịch bản + validate + điểm dừng xác nhận trên UI.
5. Bước 4–5: dựng Remotion dọc với footage thật, `checks.py`, render, đưa vào hàng duyệt.
6. Bước 6: sửa bằng prompt, quản lý phiên bản.
7. Trần chi phí, ước tính, ghi `ai_usage`.
8. Lưu mẫu / dựng từ mẫu.
9. Workbench, Telegram "Sửa:" (cắt được).
10. Test `-m local` (không gọi AI): `checks.py` trên file `.tsx` thật lấy từ 1 lần chạy thật (lưu `tests/samples/studio/`), gồm bản sạch và bản cố ý thêm `filter` -> phải bắt được; dựng từ mẫu bằng Remotion thật trên clip mẫu -> ffprobe 1080x1920.
11. Test `-m live` (TỐN TIỀN THẬT, chỉ chạy khi người dùng đồng ý): 1 phiên đầy đủ trên clip mẫu + 1 video tham khảo ngắn -> có mp4 hợp lệ, `checks` sạch, chi phí dưới trần mỗi lần chạy.
12. Checklist tay: người dùng chạy 3 prompt khác nhau trên footage trang sức thật, chấm: đúng ý prompt, sản phẩm không bị biến dạng/đổi màu, có đáng tiền và thời gian so với chế độ Nhanh không.

## Todo list

- [ ] Đọc docs, ghi báo cáo cách tích hợp
- [ ] Vendor 2 skill + cài môi trường
- [ ] Agent: phân tích + phúc tra
- [ ] Kịch bản + điểm dừng xác nhận
- [ ] Dựng Remotion dọc + checks + render
- [ ] Sửa bằng prompt + phiên bản
- [ ] Trần chi phí
- [ ] Lưu mẫu / dựng từ mẫu
- [ ] Workbench, Telegram "Sửa:" (cắt được)
- [ ] Test local + live + checklist tay

## Success Criteria

- Từ 1 prompt + footage + 1 video xu hướng: ra video dọc theo đúng nhịp và cấu trúc video tham khảo, 100% hình sản phẩm từ footage thật, vào hàng duyệt, không thao tác tay ngoài điểm dừng xác nhận.
- Prompt sửa ("đổi nhạc", "bỏ chữ ở cảnh 3") ra phiên bản mới mà không dựng lại từ đầu phần phân tích.
- `checks.py` bắt được 100% vi phạm luật sản phẩm trong bộ mẫu.
- Dựng từ mẫu đã lưu: không gọi agent, xong trong vài phút.
- Chi phí và thời gian mỗi phiên được ghi lại; người dùng quyết định dùng Studio cho bao nhiêu video mỗi ngày dựa trên số thật.

## Risk Assessment

- Chi phí và thời gian chưa biết (đoán: vài USD và 10–30 phút mỗi video, CHƯA đo). Nếu S11 cho thấy quá đắt: Studio chỉ dùng để tạo mẫu, sản xuất hằng ngày chạy "dựng từ mẫu".
- Kết quả không ổn định giữa các lần chạy (bản chất agent). Giảm thiểu: điểm dừng xác nhận, phiên bản, mẫu đã lưu.
- video-shotcraft thiết kế cho phim ngang về phần mềm; dọc + trang sức có thể ra kết quả kém. Lùi: chỉ dùng phần chữ/phụ đề/chuyển cảnh/nhịp của nó phủ lên bản dựng FFmpeg, hoặc dừng phase ở bước 4.
- Windows: nhiều phần của skill chỉ được thử trên macOS. S11 quyết định.
- Giấy phép Remotion: người dùng phải tự kiểm tra điều kiện công ty trước khi dùng thương mại.
- Phase lớn nhất plan: 3–4 ngày. Lộ trình thành khoảng 4 tuần. Cắt theo thứ tự: Telegram "Sửa:", Workbench, lưu mẫu (giữ nếu chi phí cao).

## Security Considerations

- Agent có quyền chạy lệnh trên máy chủ. Giới hạn: thư mục làm việc riêng, danh sách trắng lệnh, không truy cập web, không có key mạng xã hội/R2/Telegram trong môi trường của agent (chỉ key Anthropic và key VLM cho rea-video).
- Văn bản lấy từ video xu hướng (phụ đề OCR, caption) đi vào ngữ cảnh agent = dữ liệu không tin cậy, có thể chứa câu lệnh cài cắm. System prompt nói rõ đó là dữ liệu; quan trọng hơn là giới hạn công cụ ở trên và cửa duyệt của con người trước khi đăng.
- Code agent sinh ra chỉ chạy trong Remotion ở thư mục làm việc; `npm ci` chỉ từ lockfile đã vendor, không cài gói mới.
- Bản sao skill ghim commit; cập nhật skill là thao tác có chủ ý, đọc diff trước.

## Next steps

- Phase 14 (cảnh phụ AI) dời sang tuần 4. Cảnh phụ AI sau này có thể được Studio dùng như 1 loại shot `ai_broll` theo đúng luật hiện có.
