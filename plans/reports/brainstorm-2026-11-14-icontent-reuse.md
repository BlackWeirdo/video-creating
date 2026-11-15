# Brainstorm: học gì từ iContent Studio cho Video Creator

Ngày: 2026-11-14. Trạng thái: đề xuất, chờ người dùng chốt. Nguồn: `BAO_CAO_KIEN_TRUC_ICONTENT.md`, README iContent, plan `261112-video-creator-app/plan.md`, spec `docs/video-creator-spec.md`, code `src/videocreator`.

## 1. Câu hỏi

1. Có nên làm frontend giống iContent không?
2. Tính năng nào của iContent bổ sung được, hoặc thay thế được Video Creator?

Ràng buộc giữ nguyên: mục tiêu là footage tự quay -> kịch bản -> dựng 9:16 -> người duyệt -> đăng qua API chính thức; hình sản phẩm chỉ từ footage thật; Telegram là bảng điều khiển chính; rea-video + video-shotcraft vẫn ở Studio (phase 17).

## 2. Hai sự thật phải nói trước

**a) Bản quyền.** iContent là phần mềm thương mại, có khoá bản quyền Ed25519 (`license.py`, README mục "Bản quyền"). Chép code của nó (`timeline.js`, `tts.py`, `render.py`, `qc.py`, mẫu giọng trong `data/voices/`) vào app của thương hiệu = rủi ro vi phạm bản quyền, kể cả khi app chỉ dùng nội bộ. Được phép: học ý tưởng, thông số công khai (filter FFmpeg, ngưỡng), rồi tự viết. Phần mã nguồn mở bên trong (FreeCut, miniPaint, đều MIT) thì lấy từ GitHub gốc, không lấy từ bộ cài iContent.

**b) Hai app giải hai bài toán khác nhau.** iContent = bản địa hoá video người khác (tải Douyin -> tách nhạc -> OCR/ASR -> dịch -> lồng tiếng -> xoá sub gốc). Video Creator = biến footage của chính mình thành video bán hàng rồi đăng. Khoảng 60% lõi iContent (tách nhạc UVR, OCR hardsub, xoá sub Telea, nhận diện người nói, dịch Trung-Việt, Hán-Việt, quét Douyin) không có chỗ dùng, và quy trình "tải video Trung về lồng tiếng" còn trái quy tắc "hình chỉ từ footage thật".

=> **Không thay thế được.** Chỉ bổ sung từng mảnh.

## 3. Frontend

Hiện trạng: Jinja2 + HTMX, 21 trang, ~2.750 dòng, 14 mục trên thanh ngang trên cùng (đã chật). iContent: SPA Vanilla JS 28 module, hash router, Canvas timeline tự viết, dark theme, rail trái.

| Phương án | Làm gì | Công | Ưu | Nhược |
|---|---|---|---|---|
| A. Viết lại SPA kiểu iContent | Bỏ HTMX, router JS, ~20 view JS, gọi JSON API | 5–8 ngày | Trải nghiệm "app" mượt | Viết lại toàn bộ 21 trang đang chạy; phải thêm API JSON song song; lệch kiến trúc đã chốt (không build step, HTMX); Telegram mới là nơi dùng chính nên lợi ích thấp |
| **B. Giữ HTMX, thay vỏ + 1 "đảo" JS (khuyến nghị)** | Rail trái + dark theme bằng biến CSS; ô hàng đợi việc (HTMX polling 1s khi có việc, 5s khi rảnh); toast; 1 trình sửa kịch bản/phụ đề bằng JS thuần chỉ ở trang `video_plan` | 2–3 ngày | Giữ code đang chạy; chỉ đầu tư JS nơi cần tương tác thật | Không có NLE đa track (không cần) |
| C. Chỉ đổi giao diện | Rail + dark theme + toast | 0,5–1 ngày | Rẻ | Không cải thiện thao tác sửa kịch bản |

Ý tưởng UI đáng mượn (tự viết lại):
- Rail trái nhóm mục: Sản xuất (Sản phẩm, Footage, Kho shot, Video, Studio, Cảnh phụ) / Phát hành (Chờ duyệt, Lịch, Tài khoản) / Phân tích (Xu hướng, Hiệu quả) / Hệ thống.
- Polling thích ứng thay vì WebSocket: HTMX `hx-trigger="every 1s"` khi có job chạy, đổi sang `every 5s` khi rảnh. Đủ dùng, đơn giản.
- Đồng hồ âm tiết từng câu (xanh/vàng/đỏ) khi sửa lời đọc: số âm tiết so với `thời lượng shot × 5 âm tiết/giây`. Rẻ, rất có ích cho người duyệt.
- Danh sách câu đồng bộ với `<video>`: bấm câu -> tua tới; đang phát -> tô sáng câu. Dùng `timeupdate`, không cần Canvas.
- Chặn rời trang khi đang sửa dở (`beforeunload`).

Không mượn: Canvas timeline + sóng âm (video 15–60 giây không cần), command palette, FreeCut NLE (Studio đã lo phần sáng tạo; chỉ xét lại nếu người duyệt thật sự cần sửa tay đa track), node workflow editor.

## 4. Tính năng: bảng chấm theo mục tiêu Video Creator

Đã có trong code: `loudnorm I=-14:TP=-1.5` (`pipeline/export.py`). Chưa có: ducking, khớp tốc độ giọng, QC tự động, phụ đề tô từng chữ.

| # | Ý tưởng từ iContent | Hợp mục tiêu? | Phase | Công | Ghi chú |
|---|---|---|---|---|---|
| 1 | QC tự động bằng FFmpeg trước khi gửi duyệt: `blackdetect`, `freezedetect`, `silencedetect`, `ebur128` true peak | Cao | 05, 06 | 0,5 ngày | Người duyệt trên Telegram nhận kèm cảnh báo; chặn video lỗi trước khi tốn công duyệt |
| 2 | Ngân sách âm tiết theo thời lượng shot đưa vào prompt viết kịch bản (`max = slot × 5 × 1.1`) | Cao | 04 | 0,25 ngày | Giảm giọng đọc tràn shot ngay từ gốc |
| 3 | Khớp giọng vào shot: cắt lặng đầu/cuối (`silenceremove`) -> nhờ LLM rút gọn câu nếu > 1,35× -> `atempo` ≤ 1,35 | Cao | 09, 17 | 1 ngày | Hiện chế độ Nhanh/Studio chưa có bước này |
| 4 | Ducking nhạc dưới giọng đọc: `sidechaincompress` (threshold 0.02, ratio 2.5, attack 15, release 350) | Cao | 09 | 0,25 ngày | Nhạc nền người dùng nạp thường to, ăn giọng |
| 5 | Phụ đề ASS kiểu TikTok tô từng chữ (`\kf`/đổi màu chữ đang đọc) | Trung bình | 05 | 1 ngày | Cần mốc thời gian từng chữ: lấy từ TTS (Edge có word boundary) hoặc chạy faster-whisper trên chính file giọng đọc |
| 6 | Chọn ảnh bìa: chấm khung hình theo độ nét, gợi ý 6 ứng viên | Trung bình | 07, 11 | 0,5 ngày | IG/TikTok/FB cần cover; đã có `pipeline/thumbs.py`, chỉ nâng cấp |
| 7 | Checkpoint theo bước + "chạy lại từ bước X" | Trung bình | 05, 09 | 0,5 ngày | Sửa lời -> chỉ dựng lại giọng + render, không chạy lại phân tích |
| 8 | Dọn đĩa theo nhóm, loại trừ job đang chạy | Trung bình | NFR dọn đĩa (đợt 2) | 0,5 ngày | Máy chủ 24/7 sẽ đầy đĩa |
| 9 | Lỗi -> hướng dẫn sửa bằng tiếng Việt (bảng mẫu lỗi -> câu hướng dẫn) | Trung bình | 06, 16 | 0,5 ngày | Hợp người dùng không chuyên; gửi kèm trong tin Telegram |
| 10 | Stock Pexels/Pixabay kèm ghi nguồn + giấy phép | Đã có trong plan | 14 | — | Chỉ mượn ý lưu metadata giấy phép theo clip |
| 11 | VieNeu-TTS (TTS tiếng Việt chạy máy, clone giọng từ 3–8 giây) | Cần kiểm chứng | 09 (spike S8) | spike 0,5 ngày | Có thể cho "giọng thương hiệu" miễn phí; PHẢI kiểm giấy phép thương mại của model trước khi dùng |
| 12 | Reframe bám mặt YuNet | Thấp | — | — | Chỉ có ích nếu footage quay ngang và có người; trang sức cần bám sản phẩm, không bám mặt |
| 13 | Tiến trình giám sát tự khởi động lại khi crash | Thấp–TB | 08 | 0,5 ngày | Có thể thay bằng dịch vụ Windows / Task Scheduler restart |
| — | Tách nhạc, OCR/xoá hardsub, diarization, dịch Trung + Hán-Việt, quét Douyin, Story ảnh AI, workflow node, idle shutdown, khoá bản quyền | Không | — | — | Lệch mục tiêu hoặc trái quy tắc sản phẩm |

Tổng nhóm "Cao" (1–4): khoảng 2 ngày. Nhóm "Trung bình" (5–9): khoảng 3 ngày.

## 5. Câu hỏi chiến lược: thay MoneyPrinterTurbo bằng FFmpeg tự viết?

Ý 3 + 4 + 5 cộng lại chính là phần việc MoneyPrinterTurbo (MPT) đang làm ở chế độ Nhanh (lồng tiếng, phụ đề, nhạc). iContent chứng minh làm trực tiếp bằng FFmpeg + 1 thư viện TTS là đủ. Lợi: bỏ một dịch vụ phụ (đã từng gọi sai API), toàn quyền thời gian từng câu. Hại: phase 09 vừa viết lại và chạy thật hôm nay; đổi tiếp là làm lại. Khuyến nghị: chưa đổi; làm ý 3, 4 bên trong pipeline của mình trước, nếu MPT tiếp tục gây lỗi thì gỡ MPT sau, khi đó công gỡ nhỏ.

## 6. Khuyến nghị cuối

1. Frontend: phương án B, chia 2 bước: (i) vỏ rail + dark + hàng đợi + toast (1 ngày); (ii) trình sửa kịch bản ở `video_plan` có đồng hồ âm tiết + đồng bộ video (1–2 ngày).
2. Tính năng: làm nhóm "Cao" (1–4) trước, gắn vào phase 04/05/09 đang dở; nhóm "Trung bình" xếp vào đợt 2.
3. Không lấy code iContent; tự viết theo thông số công khai. FreeCut/miniPaint nếu cần thì lấy từ repo MIT gốc.
4. Không đẩy lịch hiện tại: các mục trên nằm sau việc chặn đường chính (đăng thật FB/IG — S2, S3).

## 7. Rủi ro

- Thêm việc vào plan đang trễ (22–26 ngày, còn nhiều spike chưa làm). Nên coi đây là việc chen vào phase đang mở, không mở phase mới.
- VieNeu-TTS: chưa rõ giấy phép model cho mục đích thương mại.
- Phụ đề tô chữ phụ thuộc mốc thời gian từng chữ; nếu TTS không trả được thì phải thêm faster-whisper (~1,6 GB model).

## 8. Đo thành công

- QC: 0 video có đoạn đen/đơ/câm lọt vào hàng duyệt.
- Giọng đọc: ≥ 95% câu nằm trong shot, tốc độ ≤ 1,35×.
- Người duyệt sửa 1 câu lời đọc trong < 30 giây trên trang `video_plan`.

## 9. Người dùng trả lời (2026-11-14) và hệ quả

1. **Footage thường quay ngang.** Code hiện có (`pipeline/render.py`): mặc định `blur_pad` (cả khung ngang nằm giữa nền mờ); chế độ `crop` dùng MỘT `x_offset_ratio` cố định cho cả footage (`crop_json`), nhập tay. Thiếu: vị trí cắt theo từng shot, theo dõi sản phẩm di chuyển.
   - YuNet (bám mặt) KHÔNG hợp: cần bám sản phẩm (nhẫn, vòng trong tay), không bám mặt.
   - Đề xuất (KISS, 3 bậc):
     a. AI gợi ý vị trí cắt theo từng shot: bước mô tả shot (Gemini/Claude vision đã chạy ở phase 03) trả thêm khung sản phẩm (bbox) tại 2–3 khung hình -> tính `x_offset` riêng cho shot. Sản phẩm rộng hơn khung 9:16 -> tự về `blur_pad`. (~1 ngày)
     b. Lia chậm khi sản phẩm di chuyển: nội suy `x` giữa các bbox, giới hạn tốc độ lia, đứng yên tối thiểu ~2 giây (học ý `DEAD_ZONE`/`MIN_HOLD` của iContent). Chỉ làm nếu (a) không đủ. (~1 ngày)
     c. Ghim tay trên web: kéo khung 9:16 trên ảnh xem trước của shot, lưu vào shot (đè gợi ý AI). (~0,5 ngày, gộp vào phương án B)
   - Cắt khung không sửa điểm ảnh sản phẩm -> không vi phạm BR-PRD-03. Cần thêm cột crop theo shot (migration mới) thay vì chỉ theo footage.
2. **Có sửa trên web khi cần.** -> Chốt phương án B. Trang `video_plan` thêm: đồng hồ âm tiết, đồng bộ câu-video, nghe thử từng câu, ghim khung cắt từng shot (mục 1c), chặn rời trang khi sửa dở.
3. **Muốn giọng thật của thương hiệu.**
   - VieNeu-TTS: README PyPI của tác giả ghi bản 0.5B Apache 2.0, bản 0.3B CC BY-NC 4.0 (cấm thương mại khi chưa xin phép); trang bên thứ ba ghi khác. -> Chỉ dùng bản ghi rõ Apache 2.0 sau khi đọc model card/LICENSE trên repo gốc, hoặc xin phép tác giả.
   - Phương án dự phòng: TTS trả phí có điều khoản clone thương mại rõ (vd. ElevenLabs) qua API — trái ưu tiên gói thuê bao nhưng hợp lệ như đường dự phòng.
   - Bắt buộc: văn bản đồng ý của người cho mẫu giọng (nhân viên/chủ), lưu kèm mẫu; mẫu sạch 10–30 giây, phòng yên tĩnh.
   - Spike S8 mở rộng: so sánh giọng clone VieNeu vs giọng sẵn đang dùng trên 5 câu kịch bản thật; người dùng nghe và chấm. (~0,5–1 ngày)

## 10. Thứ tự đề xuất (chen vào phase đang mở, không mở phase mới)

1. Spike S8 giọng clone + kiểm giấy phép (phase 09).
2. Nhóm "Cao" 1–4 (phase 04/05/09), ~2 ngày.
3. Crop theo shot bằng AI (mục 9.1a) (phase 03/05), ~1 ngày.
4. Frontend B: vỏ + trình sửa `video_plan` + ghim khung (~3 ngày).
5. Nhóm "Trung bình" và lia chậm (9.1b) sang đợt 2.
Tổng thêm ~6,5–7 ngày vào ước lượng 22–26 ngày.
