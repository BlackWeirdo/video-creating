# Phase 18: Ưu tiên gói thuê bao, hạn chế API; thêm Muse

Thứ tự thực hiện: đợt 1, ngay SAU phase 04 và TRƯỚC phase 05 (đánh số 18 vì thêm sau, 2026-11-13). Điều kiện: spike S13 ở [phase 01](phase-01-verification-spikes.md).

## Context links

- Plan cha: [plan.md](plan.md)
- Phụ thuộc: [phase 04](phase-04-ai-provider-remix-plan.md) (`AIProvider`, budget). Ảnh hưởng: [phase 13](phase-13-trend-analysis-suggestions.md), [phase 14](phase-14-generative-broll.md), [phase 16](phase-16-telegram-control-center.md), [phase 17](phase-17-studio-agent-two-skills.md)
- Docs phải đọc trước khi viết (nguồn tra ngày 2026-11-13 mâu thuẫn nhau, không dựa vào trí nhớ): điều khoản và trang trợ giúp hiện hành của Anthropic về dùng gói Pro/Max với `claude -p`; docs headless của Claude Code; docs Gemini CLI (headless, quota, loại file đầu vào): https://geminicli.com/docs/resources/quota-and-pricing/ ; Meta Model API cho Muse Spark: https://developer.meta.com/ai/resources/blog/build-with-muse-spark/

## Overview

- Ngày: 2026-11-13
- Mô tả: mọi việc AI đi qua 1 bộ định tuyến: thử đường "gói thuê bao" trước (CLI chính thức của nhà cung cấp, đăng nhập bằng tài khoản thuê bao của chủ máy), hết hạn mức mới sang API trả theo lượt (có trần tiền, tắt hẳn được). Việc không có đường tự động hợp lệ (tạo video trong app Muse, Gemini, Flow) đi qua "trạm việc tay": app soạn sẵn prompt, người làm trong app thuê bao, gửi kết quả lại. Thêm Muse Spark làm lựa chọn viết kịch bản.
- Ưu tiên: P1
- Trạng thái triển khai: hoàn thành (2026-11-13)
- Trạng thái review: đã kiểm thử (`pytest -m local` & S13 vision/writer live)

## Key Insights

- Gói thuê bao cá nhân chỉ có 2 đường lập trình CHÍNH THỨC, đều là CLI của hãng: Claude Code (`claude -p`, đăng nhập Pro/Max) và Gemini CLI (`gemini -p`, đăng nhập Google; docs ghi Google AI Pro 1.500 yêu cầu/ngày). App gọi 2 CLI này như tiến trình con. Không có đường nào khác: KHÔNG lấy token từ trình duyệt, KHÔNG điều khiển giao diện web, KHÔNG dùng công cụ bên thứ ba đăng nhập hộ gói thuê bao (cùng lý do đã loại Google Flow qua CDP và phần lõi Muse2Tele).
- Giới hạn phải nói rõ với người dùng:
  - Hạn mức gói thuê bao nhỏ và tính theo cửa sổ thời gian; máy chủ chạy 24/7 sẽ có lúc chạm trần -> việc phải CHỜ hoặc sang API. "Không gọi API chút nào" chỉ đạt được nếu chấp nhận chờ.
  - Điều khoản: các nguồn tra được nói `claude -p` với tài khoản của chính mình là được phép, còn sản phẩm bên thứ ba đi nhờ gói thuê bao thì không; quy định tính phí cho dùng lập trình thay đổi trong năm 2026 và các nguồn mâu thuẫn. App này là công cụ nội bộ chạy trên máy của chủ tài khoản bằng binary chính thức; vẫn phải đọc điều khoản hiện hành ở S13 trước khi dựa vào. Một gói thuê bao = một người; không chia sẻ đăng nhập cho cả nhóm.
  - Gói thuê bao KHÔNG bao gồm API: Claude Pro không cho hạn mức Anthropic API, Gemini Pro không cho hạn mức Gemini API.
- Muse (Meta): Muse Spark là model chữ, có API chính thức (Meta Model API, tương thích OpenAI SDK, trả theo token, đang preview và theo nguồn tra được chỉ mở cho nhà phát triển ở Mỹ) -> thêm làm `AIProvider` viết kịch bản NẾU tài khoản người dùng đăng ký được hợp lệ; không dùng proxy để lách giới hạn vùng. Muse Video chưa có API (preview/"sắp có") -> tạo video bằng Muse chỉ qua trạm việc tay trong app Meta AI.
- Việc tốn token nhất là Studio (phase 17) -> chuyển sang chạy bằng `claude -p` là khoản tiết kiệm lớn nhất. Việc nhìn ảnh phúc tra của rea-video cũng do chính agent Claude Code làm (skill cho phép: agent tự là VLM), không cần key VLM riêng.
- Giảm số lượt gọi trước khi nghĩ đến giá: mô tả shot 1 lần/footage rồi lưu; 1 lượt trả N kịch bản + 4 caption; phân tích video xu hướng lưu lại dùng chung cho đề xuất và Studio; chấm điểm chỉ chạy khi video qua preflight.
- Không có đường thuê bao cho: giọng đọc (trừ nhà cung cấp mà gói thuê bao gồm sẵn hạn mức API như ElevenLabs: kiểm tra ở S12), R2, API đăng bài, YouTube Data API. Đây không phải chi phí AI theo token đáng kể.

## Requirements

- Bộ định tuyến theo vai trò, cấu hình trong Settings (kéo thả thứ tự):

```toml
[ai.routes]
vision  = ["claude_cli", "gemini_api"]                    # mô tả shot (thumbnail qua claude_cli, video qua gemini_api), chấm điểm
writer  = ["claude_cli", "muse_api", "claude_api"]
checker = ["claude_cli", "claude_api", "gemini_api"]
studio  = ["claude_cli", "claude_api"]                    # phase 17
videogen = ["manual", "gateway_api:kling", "gateway_api:seedance", "veo_api"]   # phase 14; với videogen đây là danh sách LỰA CHỌN người dùng bấm chọn từng lần, không tự chuyển sang API
[ai.policy]
api_fallback = "ask"        # "auto" | "ask" (hỏi qua Telegram) | "never" (chỉ dùng gói thuê bao, hết thì chờ)
offpeak_hours = "23:00-06:00"   # việc không gấp chạy trong khung này
```

- Theo kết quả S13 (người dùng đã chốt Hướng A ngày 2026-11-13): bỏ `gemini_cli` (Google ngừng phục vụ gói cá nhân từ 18/06/2026); `claude_cli` là CLI gói thuê bao chính cho cả `vision` (đọc ảnh thu nhỏ), `writer`, `checker`, `studio`. `agy_cli` có thể thêm như lựa chọn TẮT mặc định kèm cảnh báo điều khoản.

- Provider CLI (`claude_cli`, `gemini_cli`) hiện thực đúng interface `AIProvider` của phase 04: ghi prompt + đường dẫn file (thumbnail, video) vào thư mục làm việc tạm, gọi CLI ở chế độ không tương tác với đầu ra JSON, validate bằng Pydantic như mọi provider khác. Cờ và định dạng đầu ra lấy từ docs/S13, không đoán.
- CLI chạy trong thư mục tạm riêng, chỉ được đọc file app đặt vào đó, không được chạy lệnh hay sửa file ngoài thư mục (trừ phiên Studio, theo luật của phase 17).
- Nhận biết hết hạn mức: phân loại lỗi CLI thành `quota` / `auth` / `other`. `quota` -> đánh dấu provider nghỉ tới giờ hồi (đọc từ thông báo nếu có, không thì 60 phút) -> sang provider kế. `auth` -> Telegram báo "cần đăng nhập lại <CLI> trên máy chủ".
- Chính sách `api_fallback`: `never` -> job vào trạng thái `waiting_quota`, tự chạy lại khi provider hồi; `ask` -> tin Telegram có nút `Dùng API (ước ~X USD)` / `Chờ`; `auto` -> sang API trong trần ngày.
- Việc không gấp (quét xu hướng, phân tích, dựng lô ban đêm) xếp vào giờ thấp điểm để dành hạn mức ban ngày cho việc người dùng bấm.
- Đồng hồ sử dụng: bảng `ai_usage` thêm `route` (`subscription`/`api`/`manual`); trang chủ và `/status` hiện: số lượt qua gói thuê bao, số lượt và tiền qua API hôm nay, provider nào đang nghỉ vì hết hạn mức.
- `muse_api`: adapter tương thích OpenAI SDK, chỉ bật khi có key Meta Model API hợp lệ; chỉ vai trò writer/checker.
- Chính sách `ask` trước khi có bot (phase 06): câu hỏi hiện trong UI; từ phase 06 gửi thêm qua Telegram.
- Trạm việc tay (`manual`): THIẾT KẾ ghi ở đây cho đủ bức tranh, HIỆN THỰC ở [phase 14](phase-14-generative-broll.md) (vì clip nhận về chỉ dùng được khi kho cảnh phụ và luật planner của phase 14 có mặt; làm ở đây sẽ ra tính năng chưa dùng được). Dùng cho tạo video bằng Muse/Meta AI, Gemini (Veo), Flow, hoặc bất kỳ app thuê bao nào:
  - App tạo "phiếu việc": prompt đã soạn (tiếng Anh, theo mẫu của từng app), ảnh tham chiếu nếu có, thông số (9:16, số giây), ghi chú "không đưa sản phẩm vào".
  - Gửi phiếu vào topic Telegram "Việc tay" (prompt ở dạng bấm-để-chép) và hiện trong UI.
  - Người làm tạo clip trong app thuê bao của họ, rồi TRẢ LỜI tin phiếu bằng file video (bot nhận file tới khoảng 20 MB) hoặc thả file vào thư mục `inbox/` của máy chủ.
  - App nhập clip thành cảnh phụ `ai_broll` (gắn nhãn, theo luật phase 14: không bao giờ là cảnh sản phẩm), đóng phiếu. Phiếu quá 48 giờ tự nhắc 1 lần rồi huỷ.
- Đăng nhập CLI là thao tác tay 1 lần trên máy chủ (mở cửa sổ đăng nhập của chính CLI); trang Settings có nút "Kiểm tra" từng CLI và hướng dẫn. App không lưu, không đọc token của CLI.

## Architecture

```
ai/router.py          # get_provider(role) -> RoutedProvider: thử lần lượt theo [ai.routes], áp policy, ghi ai_usage.route
ai/cli_base.py        # chạy CLI: thư mục tạm, timeout, bắt stdout/stderr, phân loại lỗi quota/auth/other
ai/claude_cli.py      # AIProvider qua `claude -p` (ảnh: đặt thumbnail vào thư mục tạm để CLI đọc)
ai/gemini_cli.py      # AIProvider qua `gemini -p` (video: theo kết quả S13; không được thì gửi khung hình)
ai/muse_api.py        # AIProvider qua Meta Model API (tuỳ chọn)
ai/quota.py           # trạng thái nghỉ/hồi của từng provider (bảng provider_state)
api/routes_ai.py, web/templates/ai_routes.html
(manual/tickets.py, api/routes_manual.py, manual.html: phase 14)
```

Migration `001b_routing.sql` (chạy ngay sau 001): `ai_usage.route`, bảng `provider_state` (name, resting_until, last_error); trạng thái job thêm `waiting_quota`. Bảng `manual_tickets` (id, kind, prompt, ref_path, status, tg_message_id, result_asset_id, created_at, closed_at) tạo ở migration `006_shot_asset.sql` của phase 14.

## Related code files

Tạo: `src/videocreator/ai/router.py`, `ai/cli_base.py`, `ai/claude_cli.py`, `ai/gemini_cli.py`, `ai/muse_api.py`, `ai/quota.py`, `api/routes_ai.py`, `web/templates/ai_routes.html`, `migrations/001b_routing.sql`, `tests/test_router.py`, `tests/test_cli_errors.py`, `tests/test_cli_live.py`, `reports/18-subscription-routing.md`.
Sửa: `ai/__init__.py` (`get_provider` trả router), `ai/budget.py` (chỉ tính tiền cho route `api`), `jobs.py` (`waiting_quota`), `config.py`, `docs/install.md` (cài và đăng nhập 2 CLI).

## Implementation Steps

1. Đọc docs nêu ở Context links + kết quả S13; ghi vào `reports/18-subscription-routing.md`: lệnh và cờ không tương tác của từng CLI, dạng đầu ra JSON, thông báo lỗi hết hạn mức thật (chép nguyên văn), loại file đầu vào, điều khoản liên quan.
2. `cli_base.py` + `quota.py`.
3. `claude_cli.py`, `gemini_cli.py` theo đúng interface phase 04.
4. `router.py` + chính sách `api_fallback` + `waiting_quota`.
5. Trang định tuyến + đồng hồ sử dụng + nút kiểm tra CLI.
6. `muse_api.py` (chỉ khi người dùng có key hợp lệ; không thì bỏ).
7. (Trạm việc tay: làm ở phase 14.)
8. Test `-m local` (không gọi AI): router đi đúng thứ tự khi provider đầu đang nghỉ (trạng thái thật trong SQLite); `never` đưa job sang `waiting_quota` và job tự chạy lại khi hết giờ nghỉ; phân loại lỗi trên các thông báo lỗi THẬT đã chép ở bước 1 (`tests/samples/cli_errors/`).
9. Test `-m live` (cần 2 CLI đã đăng nhập trên máy): mỗi CLI trả 1 kịch bản hợp schema từ kho shot mẫu; `claude_cli` mô tả đúng số thumbnail; `ai_usage.route = subscription`, `cost_usd = 0`.
10. Checklist tay: tắt mạng của 1 CLI / đăng xuất -> Telegram báo đúng loại lỗi; chạy 1 ngày thật, xem tỉ lệ lượt qua gói thuê bao.

## Todo list

- [x] Đọc docs + điều khoản, viết báo cáo (`reports/18-subscription-routing.md`)
- [x] Chạy CLI + phân loại lỗi + trạng thái nghỉ/hồi (`ai/cli_base.py`, `ai/quota.py`)
- [x] Provider `claude_cli` (`ai/claude_cli.py`, theo Hướng A đã chốt; bỏ `gemini_cli`)
- [x] Router + chính sách dự phòng API + `waiting_quota` (`ai/router.py`, `jobs.py`)
- [x] UI định tuyến + đồng hồ sử dụng (`api/routes_ai.py`, `web/templates/ai_routes.html`)
- [x] `muse_api` (`ai/muse_api.py`)
- [x] Test local + live (`test_cli_errors.py`, `test_router.py`, `test_cli_live.py`)

## Success Criteria

- Một ngày sản xuất bình thường (5–10 video chế độ Nhanh): >= 90% lượt gọi AI chữ/nhìn ảnh đi qua gói thuê bao; tiền API chữ trong ngày gần 0.
- Đặt `api_fallback = "never"`: không có lượt API nào, việc bị dồn lại được chạy khi hạn mức hồi, người dùng được báo.
- Đổi thứ tự provider trong Settings có hiệu lực ngay ở job kế tiếp, không sửa code.
- (Tiêu chí của trạm việc tay nằm ở phase 14.)

## Risk Assessment

- Điều khoản hoặc cách tính phí của hãng thay đổi (đã thay đổi trong 2026): đường CLI có thể bị hạn chế hoặc tính phí riêng. Giảm thiểu: mọi thứ đi qua router, đổi sang API chỉ là đổi thứ tự cấu hình; đọc lại điều khoản khi nâng cấp CLI.
- Hạn mức Pro không đủ cho Studio (phiên dài): Studio có thể cần gói Max hoặc API. S11 + S13 đo.
- CLI đổi cờ/định dạng đầu ra sau khi tự cập nhật -> ghim phiên bản CLI nếu được, test live chạy sau mỗi lần nâng cấp.
- Gemini CLI có thể không nhận file video -> vision lùi về gửi khung hình (chất lượng mô tả kém hơn, mất âm thanh) hoặc dùng Gemini API cho riêng bước mô tả shot (rẻ: 1 lần/footage).
- Meta Model API không mở cho tài khoản người dùng -> không có `muse_api`; Muse chỉ còn ở trạm việc tay.
- Trạm việc tay phụ thuộc người làm: không tính vào mục tiêu "tự động"; chỉ dùng cho cảnh phụ.
- Độ trễ: CLI khởi động chậm hơn API vài giây mỗi lượt; chấp nhận.

## Security Considerations

- App không đọc, không sao chép, không xuất token đăng nhập của CLI; file export cấu hình (phase 08) không chứa đăng nhập CLI, máy mới phải tự đăng nhập.
- CLI là agent có công cụ: chạy trong thư mục tạm, tắt quyền chạy lệnh và ghi ngoài thư mục (theo cờ chính thức tra ở bước 1); nội dung từ video xu hướng đưa vào prompt được đánh dấu là dữ liệu.
- Không dùng proxy/VPN để lách giới hạn vùng của bất kỳ nhà cung cấp nào; không tạo nhiều tài khoản để cộng hạn mức.
- File người dùng gửi qua Telegram cho phiếu việc: kiểm tra đuôi, probe bằng ffprobe, giới hạn dung lượng trước khi nhập.

## Next steps

- Phase 05 trở đi dùng `get_provider(role)` như cũ, không biết bên dưới là CLI hay API.
- Phase 17: phiên Studio mặc định chạy bằng `claude -p`; Agent SDK + API key là đường dự phòng.
- Phase 14: `videogen` mặc định là `manual`; các model API (Kling, Seedance, Veo...) luôn có sẵn trong phần mềm, người dùng chọn khi cần.
