# Đặc tả phần mềm: Video Creator (nội bộ, trang sức bạc thủ công)

Phiên bản đặc tả: 1.0, ngày 2026-11-13. Trạng thái: chưa triển khai.
Kế hoạch triển khai đi kèm: [plans/261112-video-creator-app/plan.md](../plans/261112-video-creator-app/plan.md). Khi đặc tả và kế hoạch khác nhau về HÀNH VI của phần mềm thì đặc tả này đúng; về THỨ TỰ và cách làm thì kế hoạch đúng.

Quy ước: mỗi yêu cầu có mã (ví dụ `FR-REN-03`). "Phải" là bắt buộc; "nên" là mong muốn, cắt được. Mục ghi "(chờ Sx)" phụ thuộc kết quả bước kiểm chứng Sx ở giai đoạn 01 và có thể đổi; phương án lùi ghi ở mục 17.

---

## 1. Mục đích và phạm vi

### 1.1 Mục đích

Phần mềm nội bộ giúp một thương hiệu trang sức bạc thủ công sản xuất 5–10 video ngắn mỗi ngày từ video tự quay, đăng lên nhiều mạng xã hội để xây thương hiệu, bán hàng và làm nguyên liệu quảng cáo, với con người duyệt mọi video trước khi đăng.

### 1.2 Trong phạm vi

1. Quản lý sản phẩm, footage và kho shot.
2. AI phân tích footage, viết kịch bản và caption từ thông tin sản phẩm.
3. Dựng video dọc 9:16 theo hai chế độ: Nhanh (tự động, số lượng) và Studio (theo prompt, thiết kế riêng).
4. Quét và phân tích video xu hướng cùng ngành, đề xuất video nên làm.
5. Duyệt video trong giao diện và trên Telegram.
6. Lên lịch và đăng lên Facebook Page, Instagram, Threads, TikTok qua API chính thức, 2–3 tài khoản mỗi nền tảng.
7. Điều khiển và nhận báo cáo qua Telegram bot.
8. Cảnh phụ (không chứa sản phẩm) từ AI hoặc kho stock.
9. Bộ cài Windows, chuyển cấu hình giữa các máy.

### 1.3 Ngoài phạm vi

- Bán phần mềm cho bên khác; nhiều thương hiệu trong một bản cài.
- Tạo và quản lý quảng cáo trả tiền (app chỉ xuất video; lên quảng cáo làm trong công cụ của nền tảng).
- Trả lời bình luận, tin nhắn khách hàng.
- Đăng bài, lấy dữ liệu hay dùng dịch vụ AI bằng cách điều khiển trình duyệt, lấy token từ trình duyệt, giả lập dấu vân tay trình duyệt, proxy lách giới hạn vùng, hoặc nhiều tài khoản để cộng hạn mức (bao gồm Google Flow qua CDP). Ngoại lệ duy nhất: `muse_fox` (`FR-AI-10`).
- Dịch vụ trung gian đăng bài (aggregator).
- AI tạo hoặc chỉnh sửa hình ảnh sản phẩm.
- Ra lệnh cho bot bằng câu tự do; nạp footage qua Telegram.
- Đồng bộ dữ liệu giữa nhiều máy.

### 1.4 Người dùng và vai trò

| Vai trò | Mô tả | Quyền |
|---|---|---|
| Chủ máy (owner) | Người cài app, sở hữu các gói thuê bao AI và tài khoản developer | Mọi thứ, gồm Settings, kết nối tài khoản, đăng nhập CLI |
| Người duyệt (approver) | 2–5 người trong nhóm Telegram, có user ID trong danh sách | Tạo video, duyệt/loại, đăng ngay, tạm dừng, xem báo cáo |
| Người xem | Thành viên nhóm Telegram không có trong danh sách | Chỉ đọc tin trong nhóm |

Giao diện web dùng một mật khẩu chung khi mở từ máy khác trong mạng nội bộ; không có tài khoản người dùng riêng trong giao diện (`NFR-SEC-02`).

### 1.5 Thuật ngữ

| Thuật ngữ | Nghĩa |
|---|---|
| Footage | File video gốc do đội tự quay |
| Shot | Một đoạn liên tục cắt ra từ footage, có mốc bắt đầu/kết thúc |
| Kịch bản (plan) | Danh sách shot theo thứ tự + lời + caption cho một video |
| Công thức (formula) | Cấu trúc kể chuyện của video: mở đầu, nhịp, thứ tự cảnh |
| Bản master | File video cuối cùng, một định dạng dùng chung cho mọi nền tảng |
| Cảnh phụ | Clip không chứa sản phẩm (AI tạo hoặc stock), có gắn nhãn |
| Video tham khảo | Video xu hướng của bên khác, chỉ dùng phân tích nội bộ |
| Chế độ Nhanh | Dựng tự động bằng FFmpeg hoặc MoneyPrinterTurbo |
| Chế độ Studio | Dựng theo prompt bằng agent nạp skill rea-video và video-shotcraft |
| Đường gói thuê bao | Gọi AI qua CLI chính thức đăng nhập bằng gói thuê bao của chủ máy |
| Trạm việc tay | App soạn phiếu việc, người làm trong app thuê bao rồi gửi kết quả lại |
| Máy chủ | Máy duy nhất chạy bot, lịch đăng và dựng video |

---

## 2. Tổng quan hệ thống

### 2.1 Kiến trúc

```
┌──────────────────────── Máy chủ: PC Windows bật 24/7 ────────────────────────┐
│  Tiến trình app (Python 3.11, 1 event loop)                                   │
│   ├─ FastAPI + giao diện Jinja2/HTMX (cửa sổ pywebview hoặc trình duyệt)      │
│   ├─ Worker job (1 việc nặng một lúc)     ├─ Scheduler (tick 60 giây + cron)  │
│   ├─ Telegram bot (long polling)          └─ SQLite + thư mục media           │
│  Tiến trình con do app quản lý                                                │
│   ├─ ffmpeg / ffprobe        ├─ rea-video CLI        ├─ yt-dlp                │
│   ├─ MoneyPrinterTurbo (API 127.0.0.1)                                        │
│   ├─ claude -p, gemini -p (đường gói thuê bao)                                │
│   └─ node / remotion (chỉ chế độ Studio)                                      │
└───────────────────────────────────────────────────────────────────────────────┘
   Ngoài máy: API AI (dự phòng), Cloudflare R2, Graph API (Facebook, Instagram,
   Threads), TikTok API, YouTube Data API, Meta Ad Library API, Telegram Bot API
```

### 2.2 Luồng chính

```
(A) Footage ─► tách shot ─► mô tả shot ─► kịch bản ─► dựng ─► chấm điểm ─► duyệt ─► xếp lịch ─► đăng ─► số liệu
(B) Xu hướng: quét ─► xếp hạng ─► tải top N ─► phân tích ─► đề xuất ─► [người quyết định tạo] ─► vào (A) từ bước kịch bản
(C) Studio: prompt + footage + video tham khảo ─► agent phân tích ─► kịch bản ─► [xác nhận] ─► dựng ─► vào (A) từ bước duyệt
```

Hai điểm quyết định của con người: có tạo video không (sau đề xuất hoặc footage mới), và có đăng không (sau khi dựng xong). Không có đường nào đăng bài mà không qua duyệt (`FR-APR-01`).

### 2.3 Ràng buộc thiết kế

| Mã | Ràng buộc |
|---|---|
| C-01 | Một máy chủ duy nhất chạy bot và lịch đăng. Máy khác (`role = client`) chỉ mở giao diện của máy chủ qua trình duyệt. |
| C-02 | Đăng bài và lấy số liệu chỉ qua API chính thức của nền tảng. |
| C-03 | Không ORM, không hàng đợi ngoài (Redis/Celery), không build step cho giao diện. Node.js chỉ cần cho Studio. |
| C-04 | Công cụ bên ngoài (rea-video, MoneyPrinterTurbo, CLI AI, Remotion) chạy như tiến trình con, ghim phiên bản, không import vào mã app. |
| C-05 | Kiểm thử không dùng dữ liệu giả lập: FFmpeg thật, SQLite thật, API thật; thiếu key thì bỏ qua test đó. |
| C-06 | Mọi lời gọi AI đi qua bộ định tuyến (mục 8); không nơi nào gọi thẳng một nhà cung cấp. |

---

## 3. Quy tắc nghiệp vụ xuyên suốt

Các quy tắc này áp cho mọi chế độ dựng và mọi module; chúng được kiểm tra bằng mã, không chỉ bằng prompt.

### 3.1 Độ chính xác sản phẩm

| Mã | Quy tắc |
|---|---|
| BR-PRD-01 | Mọi khung hình có sản phẩm phải lấy nguyên từ footage do người dùng nạp. AI chỉ được chọn và sắp xếp shot. |
| BR-PRD-02 | Trên shot `has_product = 1` chỉ được: cắt theo thời gian, đổi kích thước, cắt khung theo vùng người dùng chọn, chồng chữ, chuyển cảnh cắt thẳng hoặc mờ dần ngắn. Cấm: bộ lọc màu, làm nét/làm mịn/phóng to bằng AI, đổi tốc độ, lớp phủ màu, độ trong suốt dưới 1. |
| BR-PRD-03 | Footage quay dọc giữ nguyên khung. Footage quay ngang: dùng vùng cắt 9:16 người dùng đã chọn, hoặc đặt nguyên khung trên nền mờ. Không tự cắt giữa khung, không dùng AI đoán vùng cắt. |
| BR-PRD-04 | Thông tin sản phẩm trong lời thoại và caption (chất liệu, tuổi bạc, đá, kích thước, giá, kỹ thuật) chỉ được lấy từ dữ liệu sản phẩm người dùng nhập. Không có dữ liệu thì viết về cảm xúc/quy trình, không viết thông số. |
| BR-PRD-05 | Lời nhắc sản phẩm A không được đặt trên shot chỉ có sản phẩm B. Kịch bản chỉ được trộn nhiều sản phẩm khi công thức là dạng bộ sưu tập. |
| BR-PRD-06 | Sau khi viết, một bước kiểm tra đối chiếu lời và caption với dữ liệu sản phẩm; câu không có căn cứ được đánh dấu cho người duyệt, không tự sửa. |
| BR-PRD-07 | Cảnh phụ (AI hoặc stock) không bao giờ là cảnh sản phẩm, tối đa 2 cảnh mỗi video, không là cảnh mở đầu trừ khi người dùng sửa tay; video có cảnh phụ phải hiện nhãn khi duyệt và gắn nhãn nội dung AI khi nền tảng yêu cầu. |
| BR-PRD-08 | Tạo chuyển động từ ảnh sản phẩm thật bằng AI tắt mặc định và có cảnh báo biến dạng. |
| BR-PRD-09 | Người duyệt là lớp kiểm tra cuối. Màn hình duyệt phải hiện: tên sản phẩm, câu bị đánh dấu, nhãn cảnh phụ, ghi chú "có hiệu ứng chuyển động trên footage" (Studio). |

### 3.2 Bản master và định dạng

| Mã | Quy tắc |
|---|---|
| BR-FMT-01 | Mỗi video có đúng một bản master dùng cho cả bốn nền tảng: MP4, H.264 High, `yuv420p`, 1080x1920, 30 fps cố định, quét liên tục, màu bt709, GOP đóng 2 giây, `+faststart`; AAC-LC stereo 48 kHz từ 128 kbps, luôn có track âm thanh; âm lượng khoảng -14 LUFS. |
| BR-FMT-02 | Mọi engine dựng (FFmpeg, MoneyPrinterTurbo, Studio) phải đưa đầu ra qua cùng một hàm chuẩn hoá và cùng một hàm kiểm tra định dạng. |
| BR-FMT-03 | Kiểm tra định dạng đối chiếu bảng giới hạn từng nền tảng trong cấu hình (thời lượng, dung lượng, tỉ lệ, fps, codec). Trước khi có số chính thức (chờ S10, giai đoạn 11): 5–90 giây, dưới 100 MB. |
| BR-FMT-04 | Phụ đề và chữ không nằm trong 15% trên, 25% dưới, 12% mép phải của khung. Tỉ lệ nằm trong cấu hình. |
| BR-FMT-05 | Hình chỉ được nén tối đa hai lần từ footage đến bản master (đoạn trung gian CRF 14, bản cuối CRF 18 preset slow). |
| BR-FMT-06 | Mỗi video có ảnh bìa `cover.jpg`, đổi được lúc duyệt. |

### 3.3 Nội dung của bên khác

| Mã | Quy tắc |
|---|---|
| BR-REF-01 | Video tham khảo chỉ dùng phân tích nội bộ: lưu ở `media/reference/`, tối đa N video mỗi ngày (mặc định 5), tự xoá file sau 7 ngày, giữ lại kết quả phân tích dạng văn bản. |
| BR-REF-02 | Không có đường nào trong mã đưa video tham khảo vào kho shot, vào bản dựng hay vào bài đăng. |
| BR-REF-03 | Chỉ học cấu trúc (mở đầu, nhịp, thứ tự cảnh); không sao chép hình, lời, nhạc của video gốc. |
| BR-REF-04 | App tự tải video không đăng nhập, không cookie, không proxy, không vượt chặn; lỗi thì lùi về phân tích số liệu và caption. **Ngoại lệ do chủ quyết định 2026-11-14:** dữ liệu xu hướng (danh sách video, số liệu, quảng cáo) được lấy qua dịch vụ quét bên thứ ba Apify (`FR-TRD-11`), kể cả Profile cá nhân công khai; tài khoản của chủ không tham gia việc quét. Không áp dụng cho đăng bài và quản lý quảng cáo (luôn qua API chính thức). |

### 3.4 Chi phí và gói thuê bao

| Mã | Quy tắc |
|---|---|
| BR-COST-01 | Việc AI chữ và nhìn ảnh thử đường gói thuê bao trước, API trả tiền chỉ là dự phòng theo chính sách người dùng chọn (`never` / `ask` / `auto`). |
| BR-COST-02 | Ba hạn mức tiền API mỗi ngày, tách riêng: chữ và nhìn ảnh (mặc định 5 USD), sinh video (15 USD), Studio qua API (đặt sau S11/S13, tạm 10 USD). Chạm hạn mức thì chặn trước khi gọi. Model chưa có giá trong `[prices]` cũng bị chặn trước khi gọi (nếu không, lượt gọi bị tính 0 USD). "Ngày" của mọi hạn mức, báo cáo ngày và giới hạn theo ngày là ngày theo `schedule.timezone` (đổi lúc 00:00 giờ địa phương). |
| BR-COST-03 | Sinh video qua API không bao giờ tự chạy; chỉ khi người dùng chọn một model cụ thể và đã thấy giá ước tính. |
| BR-COST-04 | Mỗi lượt gọi AI ghi lại: vai trò, nhà cung cấp, đường (`subscription` / `api` / `manual`), số đơn vị, tiền. |
| BR-COST-05 | Một gói thuê bao là của một người; app không lưu, không đọc, không xuất token đăng nhập của CLI. |

---

## 4. Yêu cầu chức năng

### 4.1 Sản phẩm (PRD)

| Mã | Yêu cầu |
|---|---|
| FR-PRD-01 | Thêm, sửa, xoá sản phẩm với: tên, chất liệu, đá, kích thước, kỹ thuật chế tác, giá (tuỳ chọn công bố), ghi chú. |
| FR-PRD-02 | Xoá sản phẩm đang gắn với footage thì chỉ ẩn (không xoá cứng), để video cũ còn truy vết được. |
| FR-PRD-03 | Dữ liệu sản phẩm là nguồn duy nhất cho thông tin sản phẩm trong lời và caption (`BR-PRD-04`). |

### 4.2 Footage và kho shot (FTG)

| Mã | Yêu cầu |
|---|---|
| FR-FTG-01 | Nạp footage bằng chọn file trong giao diện hoặc dán đường dẫn thư mục trên máy chủ. Chỉ nhận đuôi video cho phép. |
| FR-FTG-02 | File được chép vào `media/footage/<id>.mp4` (tên ASCII). Phát hiện trùng bằng sha256 và từ chối. |
| FR-FTG-03 | Khi nạp, người dùng phải chọn ít nhất một sản phẩm hoặc đánh dấu "không có sản phẩm". Sửa được theo từng shot. AI chỉ gợi ý, không tự gán. |
| FR-FTG-04 | Cảnh báo khi footage quay ngang hoặc cạnh ngắn dưới 1080. Footage ngang cho chọn vùng cắt 9:16 hoặc để "nguyên khung trên nền mờ". |
| FR-FTG-05 | Sau khi nạp, app tự tách shot (rea-video; lùi PySceneDetect, chờ S1), tạo ảnh thu nhỏ khung giữa, bỏ shot dưới 0.7 giây, chia shot dài hơn 8 giây thành đoạn 3–5 giây. |
| FR-FTG-06 | Sau tách shot, app tự mô tả từng shot: mô tả, thẻ, có sản phẩm hay không, chất lượng 1–5. Mô tả chỉ chạy một lần cho mỗi footage và lưu lại. |
| FR-FTG-07 | Kho shot: lưới ảnh thu nhỏ, lọc theo footage/sản phẩm/thẻ, bấm xem lại đúng đoạn shot. |
| FR-FTG-08 | Hiện tiến độ và lỗi của việc phân tích; có nút phân tích lại. Tắt app giữa chừng thì mở lại tự chạy tiếp. |
| FR-FTG-09 | Khi footage phân tích xong, bot hỏi trên Telegram có tạo video không (`FR-TG-11`). |

### 4.3 Kịch bản và caption (PLN)

| Mã | Yêu cầu |
|---|---|
| FR-PLN-01 | Tạo N kịch bản từ một footage, hoặc từ toàn bộ kho shot (khi tạo theo đề xuất xu hướng). Chọn: ngôn ngữ lời (không / Việt / Anh), ngôn ngữ caption (Việt / Anh), thời lượng mục tiêu (15–30 giây), gói chỉ dẫn. Chế độ kho shot chỉ đưa shot đã mô tả, tối đa 40, ưu tiên shot gợi ý của đề xuất và chỉ thêm shot cùng sản phẩm (trừ công thức bộ sưu tập), liệt kê theo nhóm sản phẩm. Kịch bản theo đề xuất nhận đủ phân tích video mẫu (mở đầu, cấu trúc, nhịp cắt, kiểu chữ, không khí nhạc, lý do hiệu quả), đánh dấu là dữ liệu. |
| FR-PLN-02 | Kịch bản chỉ chứa `shot_id` có thật; mốc cắt nằm trong shot; tổng thời lượng trong khoảng mục tiêu. Vi phạm thì bị loại khi kiểm tra. |
| FR-PLN-03 | Mỗi kịch bản trong một lần tạo dùng một công thức khác nhau; kịch bản có tập shot trùng trên 70% với bản đã có của cùng nguồn bị loại. Kho quá ít shot thì báo, không ép ra bản trùng. |
| FR-PLN-04 | Mỗi kịch bản có bốn caption riêng cho Facebook, Instagram, Threads, TikTok (độ dài và hashtag theo từng nền tảng), sinh trong cùng một lượt gọi. Cắt theo giới hạn ký tự của nền tảng. |
| FR-PLN-05 | Áp các quy tắc `BR-PRD-04`, `05`, `06`. |
| FR-PLN-06 | Người dùng xem và sửa lời, caption trước khi dựng (giao diện). Từ Telegram, kịch bản được dựng thẳng không qua bước này (`FR-TG-12`). |
| FR-PLN-07 | Gói chỉ dẫn: bộ chỉ dẫn đặt tên cho người viết (giọng thương hiệu, kiểu video), lưu trong cơ sở dữ liệu, xuất/nhập dạng JSON. |

### 4.4 Dựng video chế độ Nhanh (REN)

| Mã | Yêu cầu |
|---|---|
| FR-REN-01 | Dựng một kịch bản thành bản master theo `BR-FMT-*` và `BR-PRD-*`. |
| FR-REN-02 | Engine `ffmpeg`: cắt shot, ghép, phụ đề ASS (font Be Vietnam Pro, đúng dấu tiếng Việt), nhạc nền người dùng nạp cắt theo độ dài và mờ dần cuối. Không có nhạc thì chèn track im lặng. Tuỳ chọn `render.keep_original_audio` (mặc định tắt): giữ tiếng gốc của footage, trộn ở mức 0,3 dưới giọng đọc/nhạc; shot không có tiếng được đệm im lặng. |
| FR-REN-03 | Engine `mpt` (MoneyPrinterTurbo, chờ S12): nhận các đoạn đã cắt theo thứ tự cùng lời có sẵn; làm lồng tiếng, phụ đề khớp giọng, nhạc, chuyển cảnh. Mặc định dùng khi video có lồng tiếng. |
| FR-REN-04 | Trong MoneyPrinterTurbo phải tắt: AI tự viết kịch bản, tư liệu stock và AI video cho cảnh sản phẩm, đổi tốc độ, cắt lấp khung, nhạc mặc định, tính năng đăng bài. Cấu hình của nó do app sinh ra. |
| FR-REN-05 | Engine `mpt` lỗi hoặc dịch vụ tắt thì video tự lùi về `ffmpeg`, có ghi chú trên màn hình duyệt. |
| FR-REN-06 | Giọng đọc: chọn nhà cung cấp và giọng mặc định riêng cho tiếng Việt và tiếng Anh, có nghe thử, ghi đè theo video. Nhân bản giọng tắt mặc định và chỉ dùng với sự đồng ý của chủ giọng. |
| FR-REN-07 | Phụ đề theo giọng đọc mặc định; phụ đề bằng nhận dạng tiếng nói (whisper) chỉ khi người dùng chọn cho footage có tiếng nói thật. Kiểu phụ đề cấu hình một lần, áp cho mọi engine. |
| FR-REN-08 | Nhạc nền và hiệu ứng âm thanh do người dùng tự nạp. App không tự tải nhạc. |
| FR-REN-09 | Chạy lô: nút "Dựng tất cả kịch bản đã lập" và lịch dựng ban đêm; chạy tuần tự một video một lúc. |
| FR-REN-10 | Nên: xuất thêm bản 1:1 hoặc 16:9 từ cùng kịch bản; hiệu ứng âm thanh tại điểm cắt. |
| FR-REN-11 | Sau dựng: chạy kiểm tra định dạng cho cả bốn nền tảng và lưu kết quả; video không đạt nền tảng nào thì ghi rõ lý do và tài khoản nền tảng đó bị bỏ chọn. |
| FR-REN-12 | Xem lại video trong giao diện; nút dựng lại. Lỗi dựng hiện kèm đuôi thông báo lỗi. |

### 4.5 Chế độ Studio (STD)

| Mã | Yêu cầu |
|---|---|
| FR-STD-01 | Đầu vào một phiên: prompt tự do; một hoặc nhiều footage/shot; sản phẩm liên quan; tuỳ chọn một video tham khảo, nhạc, ngôn ngữ lời, thời lượng, mẫu đã lưu. |
| FR-STD-02 | Một agent chạy trong app, nạp skill rea-video và video-shotcraft (bản sao ghim trong `vendor/skills/`), mặc định qua `claude -p` bằng gói thuê bao; Claude Agent SDK với API key là dự phòng (chờ S11, S13). |
| FR-STD-03 | Bước 1, phân tích video tham khảo: dùng lại kết quả rea-video đã có; chưa có thì chạy `rea-video decompose` rồi agent làm bước nhìn ảnh phúc tra của skill. |
| FR-STD-04 | Bước 2, kịch bản: giữ đường kể chuyện và nhịp của video tham khảo, thay toàn bộ hình bằng shot trong kho; cùng định dạng và cùng bộ kiểm tra với kịch bản chế độ Nhanh. |
| FR-STD-05 | Bước 3, điểm dừng xác nhận: hiện kịch bản và bảng "shot tham khảo → shot của mình"; người dùng bấm tiếp hoặc gõ prompt sửa. Có tuỳ chọn chạy thẳng. |
| FR-STD-06 | Bước 4, dựng bằng Remotion theo video-shotcraft: footage qua thành phần `ClipCard`, phụ đề, chữ, chuyển cảnh, cắt theo nhịp nhạc, hiệu ứng âm thanh; khung 1080x1920, 30 fps. |
| FR-STD-07 | Bước 5, kiểm tra: bước QA của skill, rồi bộ kiểm tra của app quét mã dựng theo `BR-PRD-02`; vi phạm thì trả agent sửa một lần, vẫn sai thì việc thất bại. Sau đó chuẩn hoá và kiểm tra định dạng (`BR-FMT-02`). |
| FR-STD-08 | Sửa tiếp bằng prompt trên cùng phiên; mỗi lần sửa ra một phiên bản, giữ bản cũ. |
| FR-STD-09 | Lưu bản ưng ý thành mẫu; dựng video mới từ mẫu (chọn shot và lời mới) không cần agent. |
| FR-STD-10 | Agent bị cấm: sinh hình AI, gọi các tính năng sinh video trả tiền của rea-video, truy cập web, chạy lệnh ngoài danh sách cho phép, đọc/ghi ngoài thư mục làm việc của phiên. |
| FR-STD-11 | Mỗi phiên có giới hạn số lượt và tiền; hiện ước tính trước khi chạy; ghi chi phí và thời gian thật. |
| FR-STD-12 | Nên: nút mở trình sửa Workbench của video-shotcraft; trả lời "Sửa: <prompt>" vào tin video trên Telegram. |
| FR-STD-13 | Một phiên Studio tại một thời điểm. Node.js và trình duyệt của Remotion được cài khi lần đầu mở Studio, có nút kiểm tra môi trường. |

### 4.6 Xu hướng và đề xuất (TRD)

| Mã | Yêu cầu |
|---|---|
| FR-TRD-01 | Danh sách theo dõi do người dùng nhập: tài khoản brand, kênh, hashtag, từ khoá, Page quảng cáo; bật/tắt từng mục. |
| FR-TRD-02 | Nguồn, theo thứ tự ưu tiên: YouTube Data API, Instagram Business Discovery, Meta Ad Library API (chỉ quảng cáo có phân phối ở EU, chờ S6), Instagram Hashtag Search (top media theo hashtag, cách chính thức gần nhất với "Reels đang lên"). Facebook Fanpage (`page`) / Profile (`account`): chỉ là danh sách theo dõi tay có nút "Mở trang", không quét tự động (Meta không có API Reels xu hướng; đọc Fanpage người khác cần quyền Page Public Content Access qua xét duyệt app; Profile không có API). Nguồn thiếu key hoặc quyền tự tắt và hiện lý do. Thêm mục theo dõi sai nguồn/loại bị từ chối kèm câu giải thích. |
| FR-TRD-03 | Quét một lần mỗi ngày theo giờ cấu hình và khi bấm "Quét ngay" (giao diện hoặc `/scan`). Lỗi một nguồn không chặn nguồn khác. Theo dõi hạn mức từng nguồn và dừng trước khi vượt. |
| FR-TRD-04 | Chấm điểm trong từng nguồn, không trộn thang giữa các nguồn. Mạng xã hội: theo tương tác chia cho tuổi bài. Quảng cáo: theo số ngày chạy, còn chạy hay không, reach EU; chỉ lấy quảng cáo video chạy từ 30 ngày. |
| FR-TRD-05 | Tải file của top N video theo `BR-REF-*` bằng yt-dlp; Ad Library không tải được thì người dùng tự nạp file tham khảo. |
| FR-TRD-06 | Phân tích: có file thì chạy rea-video rồi provider vai trò `vision` viết phân tích; không có file thì YouTube qua URL, còn lại theo số liệu và caption. Kết quả: mở đầu, cấu trúc theo thời gian, nhịp cắt, kiểu chữ, không khí nhạc, lý do hiệu quả. |
| FR-TRD-07 | Đề xuất: tối đa 3 mỗi ngày, mỗi đề xuất có mô tả ngắn, công thức áp được vào bộ lập kịch bản, shot gợi ý, link tham khảo. Kho thiếu loại shot cần thì ghi "cần quay thêm: ...". Video quét tự động: đề xuất được sinh một lần khi cả lô phân tích xong (kể cả khi việc cuối lỗi), để 3 suất/ngày rơi vào video điểm cao nhất; link dán tay có đề xuất riêng ngay khi phân tích xong. |
| FR-TRD-08 | Đề xuất gửi lên Telegram để quyết định (`FR-TG-10`) và hiện trong giao diện với trạng thái mới / đã gửi / đã nhận / đã bỏ. |
| FR-TRD-09 | Video sinh từ đề xuất lưu liên kết tới đề xuất để so hiệu quả sau này. |
| FR-TRD-11 | Khi có `APIFY_API_TOKEN` trong kho bí mật, các nguồn sau dùng Apify (giữ nguyên tên nguồn): `tiktok` (từ khoá, hashtag, tài khoản; từ khoá lọc video trong tháng), `ig_hashtag` (Reels theo hashtag), `ig_discovery` (Reels theo tài khoản), `facebook` (Reels của Fanpage/Profile), `ad_library` (quảng cáo video đang chạy ở quốc gia `trends.ads_country`, mặc định VN, khớp nguyên cụm từ hoặc mã Page; vẫn chỉ lấy quảng cáo chạy từ 30 ngày). Trước mỗi lần chạy đọc mức đã dùng của tài khoản Apify và dừng nguồn nếu sắp vượt `trends.apify_monthly_usd` (mặc định 5; chủ cho nâng tối đa 20 nếu hiệu quả) hoặc trần tài khoản; mỗi lần chạy có trần riêng 0,5 USD; lỗi tạm thời của Apify được thử lại 2 lần. Không có token thì dùng các nguồn ở `FR-TRD-02`. |
| FR-TRD-10 | Dán link một video/Reel Facebook hoặc Instagram công khai (ô "Thêm video theo link" trên trang Xu hướng, hoặc `/link <link>` trên Telegram, chỉ người duyệt): app đọc số liệu bằng yt-dlp theo `BR-REF-04`, lưu thành bài xu hướng có nhãn "tự chọn", tải + phân tích (rea-video) ngay, không chiếm suất tải N video/ngày của phần quét; bài tự chọn được ưu tiên khi chọn đề xuất. Tối đa 20 link/ngày, chỉ tính link đọc thành công. Không đọc được thì báo lý do và hướng dẫn nạp file tay. |

### 4.7 Cảnh phụ (BRL)

| Mã | Yêu cầu |
|---|---|
| FR-BRL-01 | Tạo cảnh phụ từ giao diện: nhập prompt hoặc chọn mẫu, chọn nguồn. Clip xem trước rồi mới Giữ hoặc Xoá; clip giữ lại vào kho như một loại shot dùng lại được. |
| FR-BRL-02 | Nguồn mặc định là trạm việc tay: app tạo phiếu (prompt soạn sẵn, ảnh tham chiếu, thông số 9:16 và số giây), gửi vào Telegram và giao diện; người làm tạo clip trong app thuê bao (Muse/Meta AI, Gemini, Flow...) rồi trả lời tin phiếu bằng file hoặc thả vào thư mục `inbox/`. Phiếu quá 48 giờ nhắc một lần rồi huỷ. |
| FR-BRL-03 | Nguồn API luôn có sẵn và chọn được từng lần: Kling và Seedance (bắt buộc, qua một adapter cổng model), Veo; nên có Sora trực tiếp. Thêm model qua cổng bằng cấu hình, không sửa mã. Áp `BR-COST-02`, `03`. |
| FR-BRL-04 | Nên: kho stock qua MoneyPrinterTurbo cho cảnh không khí, nhãn `stock_broll`. |
| FR-BRL-05 | Áp `BR-PRD-07`, `08` trong bộ kiểm tra kịch bản. |
| FR-BRL-06 | Đề xuất cảnh phụ tự động (nút trên trang cảnh phụ, chạy nền qua vai trò `writer`): dựa trên phân tích video xu hướng, số đo hình ảnh rea-video của video mẫu (`look.md`: cỡ cảnh, chuyển động máy, ánh sáng, nhiệt độ màu, màu, độ tương phản), đề xuất đang mở và kho shot footage. Mỗi ý tưởng có prompt tiếng Việt và tiếng Anh, vị trí chèn, lý do, số giây. Một look chung cùng câu "cảnh quay thật, khung dọc 9:16" được mã nối vào mọi prompt để mọi clip đồng nhất với video mẫu. Mã loại ý tưởng nhắc tên sản phẩm thật hoặc từ chỉ trang sức (bản tiếng Anh), giới hạn 4–10 giây. Chỉ điền form tạo; không tự tạo hay tính tiền. Huỷ được khi job còn chờ. |

### 4.8 Duyệt (APR)

| Mã | Yêu cầu |
|---|---|
| FR-APR-01 | Video chỉ sang trạng thái đã duyệt qua một hàm duyệt duy nhất, gọi từ giao diện hoặc Telegram. Module đăng bài chỉ nhận video đã duyệt. |
| FR-APR-02 | Màn hình duyệt: xem video, caption bốn nền tảng sửa được, tài khoản đích (mặc định các tài khoản đang bật cùng ngôn ngữ với caption và đạt kiểm tra định dạng), ảnh bìa, các thông tin của `BR-PRD-09`, điểm tự động, nút Duyệt / Loại (lý do tuỳ chọn). |
| FR-APR-03 | Một người trong danh sách người duyệt bấm là đủ. Lưu ai duyệt, lúc nào, từ đâu. |
| FR-APR-04 | Hai người bấm gần như cùng lúc: chỉ một lần có hiệu lực, người sau nhận "đã xử lý rồi". |
| FR-APR-05 | Chấm điểm tự động trước khi gửi duyệt: thang 10 theo mở đầu, độ rõ sản phẩm, vùng an toàn của chữ, khớp hình và lời. Dưới ngưỡng (mặc định 8) thì tự làm lại tối đa 2 lần trong hạn mức; vẫn không đạt thì gửi duyệt bản điểm CAO NHẤT trong chuỗi làm lại, kèm điểm và lý do. Mô hình chỉ xem ảnh nhận khung 0,3/1,3/2,3 giây và một khung mỗi shot (tối đa 12); mô hình xem video nhận cả file. Mỗi tiêu chí có bằng chứng trước điểm; điểm tổng do app tính. Không chấm được (thiếu file, quá ít khung, lỗi hoặc hết hạn mức AI, mô hình báo không chấm được) thì KHÔNG tự làm lại, gửi duyệt với điểm trống và lý do. Lần làm lại nhận tiêu chí yếu nhất kèm bằng chứng. |
| FR-APR-06 | Người duyệt bấm "Làm lại" tối đa 2 lần mỗi video (đếm riêng với tự làm lại). Bản bị thay chuyển trạng thái `superseded` và không gửi duyệt nữa. |

### 4.9 Đăng bài và lịch (PST)

| Mã | Yêu cầu |
|---|---|
| FR-PST-01 | Kết nối tài khoản: Facebook Page và Instagram Business qua token Meta (dán token hoặc OAuth, chờ S2–S4), cho nhập nhiều token; Threads và TikTok qua OAuth, lặp lại cho từng tài khoản. Mỗi tài khoản có ngôn ngữ, khung giờ riêng (tuỳ chọn), bật/tắt. |
| FR-PST-02 | Một bài đăng = một video x một tài khoản, dùng caption của đúng nền tảng. Không thể có hai bài đăng cho cùng cặp video–tài khoản. |
| FR-PST-03 | Khi duyệt: với mỗi tài khoản đích, tự xếp vào khung giờ trống sớm nhất của tài khoản đó (một video mỗi khung mỗi tài khoản). Người dùng đổi giờ, huỷ bài chưa đăng, hoặc "Đăng ngay" (có bước xác nhận). |
| FR-PST-04 | Khung giờ mặc định trong cấu hình (múi giờ `Asia/Ho_Chi_Minh`), ghi đè theo tài khoản. Lưu thời gian dạng UTC. |
| FR-PST-05 | Video được tải lên Cloudflare R2 một lần để có URL public (Instagram, Threads; Facebook và TikTok nhận file trực tiếp); xoá sau khi mọi bài đăng của video ở trạng thái cuối 24 giờ. |
| FR-PST-06 | Kiểm tra định dạng lại ngay trước khi đăng; lỗi thì dừng và báo, không gọi API. |
| FR-PST-07 | Đăng nhiều bước (Instagram, Threads, Facebook Reels): lưu mã container / mã Reel trước khi tải lên hoặc publish; khi thử lại phải hỏi trạng thái cũ trước và chỉ làm bước còn thiếu, không tạo bài trùng. Container đã `PUBLISHED` thì tìm bài trong các bài mới nhất (khớp caption); không thấy thì chuyển sang chờ người xác nhận "Đã đăng". Facebook đăng dạng Reel 3 bước (start → tải file → finish), giới hạn 30 Reel/Page/24 giờ. |
| FR-PST-08 | Lỗi tạm thời (mạng, 5xx, giới hạn tần suất): thử lại tối đa 3 lần, giãn 1, 5, 30 phút. Lỗi vĩnh viễn (token, nội dung bị từ chối) hoặc hết lượt: đánh dấu thất bại, báo Telegram kèm hướng dẫn ngắn và nút Thử lại. |
| FR-PST-09 | Bài trễ quá 6 giờ so với lịch (máy tắt): không tự đăng bù, đánh dấu lỡ lịch và hỏi người dùng. |
| FR-PST-10 | TikTok: chế độ hộp nháp cho tới khi app được audit (bot nhắc người dùng bấm đăng trong ứng dụng, có nút "Đã đăng"); chế độ đăng trực tiếp bật bằng một cờ cấu hình sau audit (chờ S5). API hộp nháp không nhận caption, nên tin nhắc kèm caption TikTok để dán. |
| FR-PST-11 | Token sắp hết hạn trong 7 ngày: cảnh báo Telegram. Token TikTok/Threads tự làm mới trước khi đăng. |
| FR-PST-12 | Sau khi đăng: lưu mã bài và đường link; bot gửi link. |
| FR-PST-13 | Nếu Meta không cho đăng công khai khi chưa review (S2 không đạt): cung cấp gói "tải video + caption" để đăng tay cho tới khi review xong. |
| FR-PST-14 | `/pause` dừng mọi việc đăng tự động; bài đã xếp lịch giữ nguyên; `/resume` chạy lại và áp `FR-PST-09` cho bài đã lỡ. |

### 4.10 Telegram bot (TG)

| Mã | Yêu cầu |
|---|---|
| FR-TG-01 | Bot chỉ chạy trên máy chủ. Chỉ nhận lệnh từ nhóm trong danh sách cho phép; hành động thay đổi trạng thái chỉ từ user ID trong danh sách người duyệt. Chat hoặc người lạ bị bỏ qua và ghi log. |
| FR-TG-02 | `/setup` tạo các topic trong nhóm có bật Topics: Xu hướng, Chờ duyệt, Đã đăng, Việc tay, Lỗi và cảnh báo, Báo cáo. Nhóm không bật Topics thì gửi chung. |
| FR-TG-10 | Tin xu hướng: tên brand, link, số liệu chính, lý do hiệu quả, công thức, kho shot có đủ không. Nút: `Tạo 1 video` / `Tạo 3 bản` / `Bỏ qua`. Tối đa 3 tin mỗi ngày. |
| FR-TG-11 | Tin footage mới: "Footage <tên>: N shot. Tạo mấy video?" Nút: `3 bản` / `5 bản` / `Bỏ qua`. |
| FR-TG-12 | Bấm tạo: app lập kịch bản và dựng thẳng, tin được sửa thành tin tiến độ (lập kịch bản → dựng → xong). Dùng ngôn ngữ mặc định trong cấu hình. |
| FR-TG-13 | Tin video chờ duyệt: video (bản xem thử 720p nếu file lớn hơn 45 MB), caption, sản phẩm, tài khoản đích, khung giờ dự kiến, điểm, các cảnh báo. Nút: `Duyệt, xếp lịch` / `Đăng ngay` / `Loại` / `Làm lại` / `Tài khoản` / `Caption`. Nhiều bản của cùng một đề xuất gửi thành một album. |
| FR-TG-14 | `Tài khoản`: bàn phím bật/tắt từng tài khoản. `Caption`: chọn nền tảng, trả lời tin bằng caption mới. `Loại`: hỏi lý do hoặc bấm không cần lý do. |
| FR-TG-15 | Sau khi xử lý, tin được sửa thành "Đã duyệt bởi <tên>" / "Đã loại" và gỡ nút. |
| FR-TG-16 | Lệnh: `/menu`, `/status`, `/pending`, `/schedule`, `/trends`, `/scan`, `/create`, `/pause`, `/resume`, `/report`, `/report week`, `/help`, `/setup`. Đăng ký với Telegram để hiện trong menu. |
| FR-TG-17 | Phản ứng trên tin lệnh của người dùng: 👀 đã nhận, 👍 đang chạy, 👌 xong, 👎 lỗi. Trả lời vào tin nào thì hành động áp cho đối tượng của tin đó. |
| FR-TG-18 | Giờ yên lặng (mặc định 22:00–07:00): hoãn tin xu hướng và tin video xong; lỗi đăng và cảnh báo vẫn gửi. |
| FR-TG-19 | Thông báo hệ thống: đã đăng (kèm link), lỗi đăng (nút Thử lại), lỡ lịch, token sắp hết hạn, hết hạn mức gói thuê bao (nút `Dùng API (~X USD)` / `Chờ`), CLI cần đăng nhập lại, đĩa sắp đầy, sao lưu lỗi, có bản cập nhật. |
| FR-TG-20 | Mọi hành động từ Telegram gọi đúng các hàm nghiệp vụ mà giao diện gọi; không có logic chỉ nằm trong bot. |
| FR-TG-21 | Trạng thái chờ người dùng trả lời (lý do, caption) lưu trong cơ sở dữ liệu, hết hạn sau 10 phút. |

### 4.11 Báo cáo (RPT)

| Mã | Yêu cầu |
|---|---|
| FR-RPT-01 | Báo cáo ngày (mặc định 21:30) và `/report`: đã đăng, lỗi, đang chờ duyệt, lịch ngày mai, video xếp hàng quá 2 ngày, số lượt AI qua gói thuê bao và qua API, tiền API. |
| FR-RPT-02 | Thu số liệu bài đăng (xem, thích, bình luận, chia sẻ) ở mốc 24 giờ, 72 giờ, 7 ngày cho nền tảng cho phép mà không cần quyền mới. Không có dữ liệu thì hiện "không có dữ liệu", không hiện 0. |
| FR-RPT-03 | Báo cáo tuần (thứ Hai 09:00) và `/report week`: số video theo nền tảng, 3 video tốt nhất và kém nhất theo lượt xem 72 giờ, trung bình theo công thức kèm số mẫu, so sánh video từ đề xuất xu hướng với video thường. |
| FR-RPT-04 | Trang chủ: số footage/video theo trạng thái, việc đang chạy, tình trạng từng nhà cung cấp AI, chi phí hôm nay so với hạn mức. |

### 4.12 Cài đặt và vận hành (OPS)

| Mã | Yêu cầu |
|---|---|
| FR-OPS-01 | Bộ cài Windows một file, không cần quyền admin, có shortcut, gỡ được, giữ dữ liệu khi gỡ, tuỳ chọn chạy cùng Windows. Kiểm tra và cài WebView2 nếu thiếu. |
| FR-OPS-02 | Trang Settings: cấu hình, nhập key (chỉ ghi, không hiện lại), định tuyến AI, giọng đọc, khung giờ, hạn mức, kiểm tra từng CLI và từng công cụ ngoài. Đổi cấu hình có hiệu lực ở việc kế tiếp, không cần khởi động lại (trừ cổng mạng và vai trò máy). |
| FR-OPS-03 | Xuất cấu hình ra một file mã hoá bằng mật khẩu (cấu hình, cơ sở dữ liệu, key; không gồm media, không gồm đăng nhập CLI); nhập trên máy khác. Máy nhập mặc định là `client` trừ khi chọn làm máy chủ mới. |
| FR-OPS-04 | Sao lưu cơ sở dữ liệu và cấu hình mỗi đêm, giữ 14 bản. |
| FR-OPS-05 | Dọn đĩa: thư mục làm việc xoá khi xong; bản master của video đã đăng giữ 90 ngày (cấu hình được); footage gốc không bao giờ tự xoá; cảnh báo khi ổ đĩa dưới 10 GB. |
| FR-OPS-06 | Nên: kiểm tra bản cập nhật ở nơi người dùng cấu hình, báo và cài sau khi người dùng bấm, sao lưu trước khi cập nhật. |
| FR-OPS-07 | Nên: chạy không cửa sổ trên Linux (VPS). |
| FR-OPS-08 | Chỉ một bản app chạy trên một máy. |

---

## 5. Mô hình dữ liệu

SQLite, chế độ WAL. Thời gian lưu UTC. Cột `*_json` là văn bản JSON.

| Bảng | Cột chính | Ghi chú |
|---|---|---|
| `products` | id, name, material, facts_json, hidden, created_at | Nguồn sự thật về sản phẩm |
| `footage` | id, path, sha256 (duy nhất), duration_s, width, height, orientation, crop_json, product_ids_json, status, error, created_at | |
| `shots` | id, footage_id (NULL nếu từ asset), asset_id (NULL nếu từ footage), idx, start_s, end_s, description, tags_json, has_product, product_ids_json, quality, thumb_path | Thẻ `ai_broll` / `stock_broll` cho cảnh phụ |
| `assets` | id, kind (`music` / `sfx` / `broll`), path, duration_s, meta_json | |
| `videos` | id, footage_id (NULL khi lấy shot từ nhiều footage), product_ids_json, engine (`ffmpeg` / `mpt` / `studio`), status, plan_json, voice_lang, caption_lang, captions_json, target_accounts_json, output_path, cover_path, duration_s, preflight_json, unsupported_claims_json, quality_score, quality_notes, auto_retry_count, redo_count, supersedes_id, suggestion_id, auto_render, tg_message_id, error, reject_reason, created_at, approved_at, approved_by | Một cột `engine` duy nhất cho cách dựng |
| `accounts` | id, platform, external_id, name, lang, slots_json, secret_key, token_expires_at, enabled | |
| `posts` | id, video_id, account_id, status, scheduled_at, attempts, next_attempt_at, remote_container_id, external_post_id, permalink, error, posted_at; duy nhất (video_id, account_id) | |
| `post_metrics` | id, post_id, checkpoint (`24h` / `72h` / `7d`), fetched_at, views, likes, comments, shares; duy nhất (post_id, checkpoint) | |
| `jobs` | id, kind, ref_id, status, error, log_tail, created_at, started_at, finished_at | |
| `ai_usage` | id, day, role, provider, model, route (`subscription` / `api` / `manual`), kind, input_units, output_units, cost_usd, ref | |
| `provider_state` | name, resting_until, last_error | Trạng thái nghỉ vì hết hạn mức |
| `watch_items` | id, source, kind, value, enabled | |
| `trend_items` | id, source, external_id, url, author, caption, published_at, metrics_json, score, analysis_json, fetched_at; duy nhất (source, external_id) | |
| `reference_videos` | id, trend_item_id, path, rea_dir, downloaded_at, deleted_at | Không có khoá ngoại nào tới `shots` |
| `suggestions` | id, trend_item_id, text, formula_json, status, created_at | |
| `presets` | id, name, kind, body, created_at | Gói chỉ dẫn |
| `studio_sessions` | id, video_id, prompt, ref_item_id, session_ref, status, cost_usd, versions_json | |
| `studio_templates` | id, name, project_path, props_schema_json, created_at | |
| `manual_tickets` | id, kind, prompt, ref_path, status, tg_message_id, result_asset_id, created_at, closed_at | |
| `tg_pending_input` | chat_id, user_id, kind, ref_id, expires_at | |
| `audit_log` | id, at, actor, action, object_type, object_id, detail | |
| `settings` | key, value | Ví dụ `posting_paused` |

Định dạng `plan_json`:

```json
{
  "formula": "hook-first",
  "source": "footage | library",
  "title": "...",
  "product_ids": [3],
  "voice_lang": "none | vi | en",
  "caption_lang": "vi | en",
  "shots": [{"shot_id": 12, "start_s": 0.4, "duration_s": 2.5, "text": "dòng phụ đề hoặc lời"}],
  "captions": {
    "facebook":  {"text": "...", "hashtags": ["..."]},
    "instagram": {"text": "...", "hashtags": ["..."]},
    "threads":   {"text": "...", "hashtags": ["..."]},
    "tiktok":    {"text": "...", "hashtags": ["..."]}
  }
}
```

Bí mật (key API, token mạng xã hội, token bot) không nằm trong cơ sở dữ liệu hay file cấu hình; chúng nằm trong kho bí mật mã hoá (`NFR-SEC-01`).

---

## 6. Trạng thái

```
footage : imported → analysing → analysed | failed

video   : planned → rendering → rendered → scoring → pending_approval → approved → scheduled → posted
          rendering → failed (dựng lại được)
          pending_approval → rejected
          planned | rendered | scoring | pending_approval → superseded (bị thay bằng bản làm lại)
          superseded → pending_approval (chỉ chấm điểm tự động: bản điểm cao nhất của chuỗi làm lại được gửi duyệt)
          scheduled → failed (khi có bài đăng lỗi vĩnh viễn; đăng lại được)
          posted khi mọi bài đăng ở trạng thái posted hoặc needs_user_action

post    : scheduled → publishing → posted | failed | needs_user_action (TikTok hộp nháp)
          scheduled → missed (trễ quá 6 giờ) ; failed | missed → scheduled (người dùng thử lại)
          needs_user_action → posted (người dùng bấm "Đã đăng")

job     : queued → running → done | failed
          queued → waiting_quota → queued (hạn mức hồi hoặc người dùng cho dùng API)

studio  : created → analysing → scripting → awaiting_confirm → building → checking → done | failed
          done → building (sửa bằng prompt, phiên bản mới)

ticket  : open → received → imported | rejected ; open → expired (48 giờ + 1 lần nhắc)
```

Mọi chuyển trạng thái của video và bài đăng là một câu lệnh cập nhật có điều kiện trên trạng thái hiện tại; không đạt điều kiện thì thao tác bị coi là đã có người xử lý. Khi app khởi động: việc đang `running` trở về `queued`; bài đang `publishing` trở về `scheduled`, giữ mã container nếu có; vòng đăng kế tiếp hỏi trạng thái container đó từ nền tảng (không tạo mới) và không đánh bài đã có container là lỡ lịch.

Hàng đợi việc: một worker, lấy việc ưu tiên cao trước rồi việc cũ trước. Việc người dùng chờ (`plan`, `render`, `replan`, `studio`) = 10; phân tích link dán tay = 5; việc nền (quét, phân tích xu hướng, mô tả shot...) = 0. Mỗi lần quét chỉ xếp `trends.auto_analyse_top_n` (mặc định 3) video mỗi nguồn để phân tích.

---

## 7. Giao diện

Ngôn ngữ giao diện: tiếng Việt. Trang, theo thanh điều hướng:

| Trang | Nội dung chính |
|---|---|
| Trang chủ | `FR-RPT-04`, cảnh báo đang mở |
| Sản phẩm | Danh sách, form thêm/sửa |
| Footage | Nạp file, trạng thái phân tích, chọn sản phẩm, chọn vùng cắt cho footage ngang |
| Kho shot | Lưới ảnh, lọc, xem lại, sửa sản phẩm/thẻ, kho cảnh phụ |
| Video | Danh sách theo trạng thái; chi tiết: kịch bản, lời, caption, dựng/dựng lại, engine |
| Chờ duyệt | `FR-APR-02` |
| Lịch đăng | Bảng theo ngày và tài khoản; đổi giờ, huỷ, đăng ngay; lịch sử và lỗi |
| Xu hướng | Danh sách theo dõi; kết quả xếp hạng theo nguồn; đề xuất |
| Studio | Form prompt, tiến độ, điểm dừng xác nhận, phiên bản, mẫu |
| Cảnh phụ | Tạo, phiếu việc tay, xem trước, giữ/xoá |
| Hiệu quả | Bảng bài đăng với số liệu ba mốc |
| Tài nguyên | Nhạc, hiệu ứng âm thanh, giọng đọc (nghe thử), gói chỉ dẫn |
| Tài khoản | Kết nối, ngôn ngữ, khung giờ, hạn token |
| Settings | `FR-OPS-02`, `03`; định tuyến AI; phiên bản; nhật ký |

---

## 8. Định tuyến AI

### 8.1 Vai trò và nhà cung cấp

| Vai trò | Việc | Thứ tự mặc định |
|---|---|---|
| `vision` | Mô tả shot, phân tích video tham khảo, chấm điểm | `claude_cli`, `gemini_api` |
| `writer` | Kịch bản, caption, đề xuất | `claude_cli`, `muse_api`, `claude_api` |
| `checker` | Đối chiếu lời với dữ liệu sản phẩm | `claude_cli`, `claude_api`, `gemini_api` |
| `studio` | Phiên Studio | `claude_cli`, `claude_api` (Agent SDK) |
| `videogen` | Cảnh phụ | Danh sách LỰA CHỌN, không tự chuyển: `manual`, Kling, Seedance, Veo |

Giọng đọc không thuộc bộ định tuyến này; nó do MoneyPrinterTurbo đảm nhiệm với nhà cung cấp người dùng chọn. (`gemini_cli` đã bỏ sau S13 vì ngừng phục vụ gói cá nhân; `agy_cli` tắt mặc định, chỉ bật khi người dùng tự chấp nhận rủi ro điều khoản.)

### 8.2 Hành vi

| Mã | Yêu cầu |
|---|---|
| FR-AI-01 | Mọi nhà cung cấp hiện thực cùng một giao diện hai hàm: mô tả video/ảnh theo lược đồ, và sinh JSON theo lược đồ. Đầu ra luôn được kiểm tra theo lược đồ; sai thì gọi lại một lần rồi thất bại. |
| FR-AI-02 | Bộ định tuyến thử lần lượt theo thứ tự cấu hình, bỏ qua nhà cung cấp đang nghỉ. |
| FR-AI-03 | Nhà cung cấp CLI chạy trong thư mục tạm riêng, chỉ đọc file app đặt vào đó, không được chạy lệnh hay ghi ra ngoài (trừ phiên Studio theo `FR-STD-10`). |
| FR-AI-04 | Lỗi CLI được phân loại: hết hạn mức (nhà cung cấp nghỉ tới giờ hồi; mặc định 60 phút nếu không đọc được), cần đăng nhập lại (báo Telegram), lỗi khác. |
| FR-AI-05 | Khi mọi đường gói thuê bao của một vai trò đều nghỉ: `never` → việc chờ; `ask` → hỏi người dùng kèm ước tính tiền; `auto` → sang API trong hạn mức. |
| FR-AI-06 | Việc không gấp (quét, phân tích xu hướng, dựng lô) chạy vào giờ thấp điểm cấu hình được. |
| FR-AI-07 | Claude API chỉ nhận ảnh, không nhận file video: nhà cung cấp Claude mô tả shot bằng ảnh thu nhỏ. Gemini nhận video trực tiếp qua API; qua CLI thì chờ S13. |
| FR-AI-08 | `muse_api` (Muse Spark qua Meta Model API) chỉ bật khi người dùng có key hợp lệ; chỉ cho `writer` và `checker`. Muse không có đường tạo video tự động; tạo video bằng Muse đi qua trạm việc tay. |
| FR-AI-09 | Đổi thứ tự, model hay chính sách trong Settings có hiệu lực ở lượt gọi kế tiếp. |
| FR-AI-10 | `muse_fox`: gọi Muse (muse.ai) qua REST của FoxProfile mà Muse2Tele đang chạy tại máy (`127.0.0.1:8090`). Quyết định của chủ dự án ngày 2026-11-15, chấp nhận rủi ro điều khoản và khoá tài khoản Muse. App không tự điều khiển trình duyệt, không giữ proxy hay cookie; chỉ gửi prompt (kèm video khi có) vào profile được chọn và đọc trả lời. Tắt mặc định, chỉ bật khi đã cấu hình profile và token FoxProfile. |

---

## 9. Tích hợp bên ngoài

| Hệ thống | Dùng cho | Cách gọi | Ghi chú |
|---|---|---|---|
| FFmpeg / ffprobe | Cắt, ghép, chuẩn hoá, đo | Tiến trình con, đối số dạng danh sách | Kèm trong bộ cài |
| rea-video | Tách shot footage; mổ xẻ video tham khảo | CLI `rea-video decompose` trong venv riêng | Không bật `--vlm`; chờ S1 |
| video-shotcraft | Dựng ở Studio | Skill do agent dùng + Remotion | Bản sao ghim; giấy phép Remotion do người dùng kiểm tra |
| MoneyPrinterTurbo | Lồng tiếng, phụ đề, nhạc, lắp ráp, lô, stock | API tại 127.0.0.1, bản ghim, venv riêng | Chờ S12 |
| Claude Code CLI | `writer`, `vision`, `checker`, `studio` | `claude -p` | Gói thuê bao của chủ máy; chờ S13 |
| Gemini CLI | `vision`, `writer`, `checker` | `gemini -p` | Chờ S13 |
| Anthropic API, Gemini API | Dự phòng | SDK chính thức | Có hạn mức tiền |
| Meta Model API | `muse_api` | Tương thích OpenAI SDK | Tuỳ khả năng đăng ký |
| FoxProfile (Muse2Tele) | `muse_fox` | REST `127.0.0.1:8090/api/v1`, token Bearer | `FR-AI-10`; phụ thuộc giao diện web của Muse |
| Cổng model (fal.ai hoặc Replicate), Veo API | Sinh cảnh phụ | SDK/HTTP | Người dùng chọn từng lần |
| Cloudflare R2 | URL public tạm cho video | S3 API | Tên đối tượng ngẫu nhiên, tự xoá |
| Graph API (Meta) | Đăng Facebook Page, Instagram; Business Discovery; Hashtag | HTTPS, phiên bản ghim | Chờ S2, S3 |
| Threads API | Đăng Threads | OAuth + HTTPS | Đọc tài liệu ở giai đoạn 11 |
| TikTok Content Posting API | Hộp nháp, đăng trực tiếp | OAuth + HTTPS | Chờ S5, audit |
| YouTube Data API | Nguồn xu hướng | API key | Theo dõi quota |
| Meta Ad Library API | Nguồn xu hướng | Token + xác minh danh tính | Chờ S6 |
| yt-dlp | Tải video tham khảo; đọc số liệu công khai của một video Facebook/Instagram được dán link | Tiến trình con, phiên bản ghim, `--ignore-config` (không cookie) | `BR-REF-*` |
| Apify (`clockworks/tiktok-scraper`, `apify/instagram-hashtag-scraper`, `apify/instagram-reel-scraper`, `apify/facebook-reels-scraper`, `apify/facebook-ads-scraper`) | Dữ liệu xu hướng TikTok, Instagram, Facebook Reels, Thư viện quảng cáo Meta mọi quốc gia | REST API, token `APIFY_API_TOKEN`, trả theo kết quả | `FR-TRD-11`, ngoại lệ `BR-REF-04` |
| Telegram Bot API | Điều khiển, thông báo | python-telegram-bot, long polling | Giới hạn file khoảng 50 MB gửi, 20 MB nhận |

---

## 10. Cấu hình

File `config.toml` (không chứa bí mật). Các nhóm khoá:

| Nhóm | Khoá chính | Mặc định |
|---|---|---|
| chung | `role`, `host`, `port` | `server`, `127.0.0.1`, 8765 |
| `[ai.routes]` | `vision`, `writer`, `checker`, `studio`, `videogen` | Mục 8.1 |
| `[ai.policy]` | `api_fallback`, `offpeak_hours` | `ask`, 23:00–06:00 |
| `[budget]` | `daily_usd`, `generative_daily_usd`, `studio_daily_usd` | 5, 15, 10 |
| `[prices.<model>]` | Giá từng model | Theo S7 |
| `[quality]` | `min_score`, `max_retries` | 8, 2 |
| `[schedule]` | `timezone`, `auto`, `slots`, `daily_report_at`, `weekly_report_at` | `Asia/Ho_Chi_Minh`, true, 5 khung, 21:30, thứ Hai 09:00 |
| `[telegram]` | `allowed_chat_ids`, `approver_user_ids`, `quiet_hours`, `max_trend_msgs_per_day`, `default_voice_lang`, `default_caption_lang` | —, —, 22:00–07:00, 3, `none`, `vi` |
| `[platform_limits.<nền tảng>]` | thời lượng, dung lượng, tỉ lệ, fps, codec, ký tự caption | `BR-FMT-03` |
| `[safe_zone]` | `top`, `bottom`, `right` | 0.15, 0.25, 0.12 |
| `[mpt]` | phiên bản ghim, cổng | — |
| `[voice]` | nhà cung cấp và giọng cho `vi`, `en` | Theo S8/S12 |
| `[trends]` | giờ quét, quốc gia Ad Library, số ngày nhìn lại, `download_top_n`, `reference_keep_days` | —, —, —, 5, 7 |
| `[tiktok]` | `mode` | `inbox` |
| `[studio]` | `model`, giới hạn lượt và tiền mỗi phiên | `claude-opus-5-5`, theo S11 |
| `[retention]` | `output_days`, `backup_keep` | 90, 14 |
| `[r2]` | `bucket`, `public_base` | — |

---

## 11. Yêu cầu phi chức năng

### 11.1 Bảo mật

| Mã | Yêu cầu |
|---|---|
| NFR-SEC-01 | Bí mật nằm trong kho mã hoá (DPAPI trên Windows; file quyền 600 trên Linux), không vào file cấu hình, log, prompt, tin Telegram hay phản hồi API của app. Log thay mọi giá trị bí mật bằng `***`. |
| NFR-SEC-02 | Mặc định chỉ nghe `127.0.0.1`. Nghe địa chỉ khác bắt buộc có mật khẩu giao diện; thiếu thì từ chối khởi động. Chỉ dùng trong mạng nội bộ hoặc sau HTTPS. |
| NFR-SEC-03 | Văn bản từ bên ngoài (caption, phụ đề nhận dạng từ video tham khảo, câu trả lời Telegram) là dữ liệu: đánh dấu rõ trong prompt, không đưa vào lệnh hệ thống, luôn thoát ký tự khi hiển thị. |
| NFR-SEC-04 | Agent và CLI có quyền chạy lệnh bị giới hạn theo `FR-AI-03` và `FR-STD-10`; môi trường của chúng không chứa key mạng xã hội, R2 hay Telegram. |
| NFR-SEC-05 | File tải lên và file nhận qua Telegram: kiểm tra đuôi, đo bằng ffprobe, giới hạn dung lượng; tên lưu do app đặt. Đường phục vụ media chặn truy cập ngoài thư mục media. |
| NFR-SEC-06 | OAuth dùng tham số `state` ngẫu nhiên, một lần, hết hạn 10 phút. |
| NFR-SEC-07 | Người duyệt nên bật xác minh hai bước trên Telegram, vì Telegram điều khiển được việc đăng bài. |
| NFR-SEC-08 | Mọi hành động thay đổi trạng thái ghi vào nhật ký kiểm toán kèm người thực hiện. |
| NFR-SEC-09 | File xuất cấu hình luôn mã hoá bằng mật khẩu. |

### 11.2 Độ tin cậy

| Mã | Yêu cầu |
|---|---|
| NFR-REL-01 | Tắt app hoặc mất điện bất kỳ lúc nào không làm mất dữ liệu đã ghi và không gây đăng trùng. |
| NFR-REL-02 | Lỗi của bot, MoneyPrinterTurbo, một CLI hay một nguồn xu hướng không làm sập app; chức năng còn lại vẫn chạy. |
| NFR-REL-03 | Máy chủ khởi động lại thì app tự chạy và tiếp tục việc dang dở. |
| NFR-REL-04 | Mọi tiến trình con có giới hạn thời gian. |

### 11.3 Hiệu năng (PC không GPU)

| Mã | Mục tiêu |
|---|---|
| NFR-PERF-01 | Footage 30–60 giây: có shot trong kho trong 5 phút. |
| NFR-PERF-02 | Video 20 giây chế độ Nhanh: dựng xong trong 2 phút (engine `ffmpeg`). |
| NFR-PERF-03 | Từ bấm `Tạo 1 video` trên Telegram đến khi nhận video chờ duyệt: dưới 5 phút cho video 20–30 giây khi đường gói thuê bao còn hạn mức. |
| NFR-PERF-04 | Bài đăng lệch giờ đã xếp dưới 2 phút. |
| NFR-PERF-05 | Phiên Studio: không đặt mục tiêu trước khi đo ở S11. |

### 11.4 Khả năng bảo trì

| Mã | Yêu cầu |
|---|---|
| NFR-MNT-01 | Thêm nền tảng đăng bài, nhà cung cấp AI hay nguồn xu hướng là thêm một adapter theo giao diện có sẵn, không sửa nơi gọi. |
| NFR-MNT-02 | Công cụ ngoài ghim phiên bản; nâng cấp là thao tác có chủ ý, kèm chạy lại test thật. |
| NFR-MNT-03 | Thay đổi cấu trúc cơ sở dữ liệu qua file migration đánh số theo thứ tự thực hiện. |
| NFR-MNT-04 | Mã, tên biến, commit bằng tiếng Anh; giao diện và tin nhắn bot bằng tiếng Việt. |

### 11.5 Môi trường

- Máy chủ: Windows 10/11, PC bật 24/7, tắt sleep/hibernate, kết nối internet ổn định.
- Phần mềm kèm theo: WebView2, FFmpeg; cài riêng: Claude Code, Gemini CLI, Node.js (Studio).
- Khuyến nghị: 16 GB RAM, ổ SSD còn trống từ 100 GB.

---

## 12. Kiểm thử và nghiệm thu

### 12.1 Cách kiểm thử

- `pytest -m local`: FFmpeg, SQLite, MoneyPrinterTurbo, Remotion thật trên clip mẫu thật do người dùng cấp; không gọi dịch vụ ngoài.
- `pytest -m live`: gọi dịch vụ thật bằng tài khoản thử; thiếu key hoặc chưa đăng nhập thì bỏ qua; test tốn tiền thật chỉ chạy khi người dùng đồng ý.
- Danh sách kiểm tay cho thao tác cần người: bấm nút Telegram, đăng nhập OAuth, nghe giọng đọc, chấm chất lượng video.
- Dữ liệu mẫu cho test tính toán (số liệu xu hướng, thông báo lỗi CLI, update Telegram) lấy từ lần chạy thật đã lưu, không tự bịa.

### 12.2 Tiêu chí nghiệm thu theo đợt

| Đợt | Nghiệm thu khi |
|---|---|
| 1 | Từ một footage thật ra ít nhất 3 video khác nhau; người duyệt bấm duyệt; bài xuất hiện công khai trên Facebook Page và Instagram, có link trong app và Telegram. Ít nhất 90% lượt AI chữ/nhìn ảnh đi qua gói thuê bao. Cài trên máy thứ hai bằng một file trong 15 phút. Một video có lồng tiếng Việt được người dùng chấp nhận. |
| 2 | Một ngày thật: từ 5 video đăng đúng lịch lên bốn nền tảng (TikTok ở hộp nháp nếu chưa audit), thao tác tay chỉ là duyệt, làm hoàn toàn từ điện thoại. Mỗi tuần có ít nhất 5 đề xuất từ xu hướng; bấm `Tạo 1 video` ra video chờ duyệt. |
| 3 | Từ một prompt, footage và một video xu hướng: Studio ra video dọc theo cấu trúc video tham khảo, 100% hình sản phẩm từ footage thật, bộ kiểm tra bắt được mọi vi phạm trong bộ mẫu; sửa được bằng prompt; dựng lại được từ mẫu. |
| 4 | Một phiếu việc tay đi trọn vòng; mỗi model API bắt buộc (Kling, Seedance, Veo) sinh được một clip 9:16; báo cáo tuần đến Telegram với số liệu ba mốc cho Facebook và Instagram. |

### 12.3 Kiểm tra bắt buộc cho quy tắc nghiệp vụ

| Quy tắc | Kiểm tra |
|---|---|
| BR-PRD-02 | Mọi bộ lọc trong các lệnh dựng thuộc danh sách cho phép; bộ kiểm tra Studio bắt được mã có `filter`, đổi tốc độ, lớp phủ |
| BR-PRD-03 | Clip mẫu quay ngang không bị cắt giữa khung |
| BR-PRD-05, 07 | Kịch bản vi phạm bị từ chối khi kiểm tra |
| BR-FMT-01 | Đo bản master của cả ba engine khớp từng mục |
| BR-FMT-03 | Kiểm tra định dạng trả lỗi đúng khi hạ giới hạn |
| BR-REF-01, 02 | File quá hạn bị xoá; không truy vấn nào đưa video tham khảo vào kho shot |
| BR-COST-02 | Đặt hạn mức rất thấp thì lượt gọi kế tiếp bị chặn, không gọi API |
| FR-APR-04, FR-PST-02, 07 | Duyệt hai lần, thử lại sau mất mạng không sinh bài trùng |
| FR-PST-09 | Bài trễ 7 giờ thành lỡ lịch, không đăng bù |

---

## 13. Ánh xạ yêu cầu sang giai đoạn triển khai

| Nhóm yêu cầu | Giai đoạn |
|---|---|
| Kiểm chứng S1–S13, đăng ký tài khoản | 01 |
| Khung app, dữ liệu, trạng thái, bí mật (mục 5, 6, NFR-SEC-01, NFR-REL) | 02 |
| FR-PRD, FR-FTG | 03 |
| FR-PLN, FR-AI-01, BR-PRD-04..06, BR-COST-02 | 04 |
| FR-AI-02..09, BR-COST-01, 04, 05 | 18 |
| FR-REN-01, 02, 11, 12; BR-FMT; BR-PRD-02, 03 | 05 |
| FR-APR-01..04; FR-TG-01, 13 (bản tối thiểu), 15 | 06 |
| FR-PST-01, 02, 05..08, 12, 13 | 07 |
| FR-OPS-01..03, 06..08; NFR-SEC-02, 09 | 08 |
| FR-REN-03..10 | 09 |
| FR-PST-03, 04, 09, 11; FR-RPT-01; FR-OPS-04, 05 | 10 |
| FR-PST-10, Threads, TikTok | 11 |
| FR-TRD-01..04 | 12 |
| FR-TRD-05..09; BR-REF | 13 |
| FR-TRD-10, FR-TRD-11; FR-TRD-02 (nguồn Facebook) | plan `261114-meta-reels-facebook-sources` |
| FR-TG-02, 10..21; FR-APR-05, 06; FR-PLN-07; FR-PST-14 | 16 |
| FR-STD | 17 |
| FR-BRL; BR-PRD-07, 08; BR-COST-03 | 14 |
| FR-RPT-02, 03 | 15 |

Thứ tự thực hiện: 01, 02, 03, 04, 18, 05, 06, 07, 08, 09 (đợt 1); 10, 11, 12, 13, 16 (đợt 2); 17 (đợt 3); 14, 15 (đợt 4).

---

## 14. Rà soát chồng chéo (kết quả lần rà 2026-11-13)

| Chỗ dễ chồng chéo | Cách phân định trong đặc tả này |
|---|---|
| Ba cách dựng | Một cột `engine`; mọi engine dùng chung kịch bản (`plan_json`), bộ kiểm tra kịch bản, hàm chuẩn hoá, hàm kiểm tra định dạng, hàng chờ duyệt |
| Ba nơi vẽ phụ đề (ASS, MoneyPrinterTurbo, Remotion) | Một cấu hình kiểu phụ đề và một vùng an toàn dùng chung |
| Hai cách cấu hình model | Chỉ còn `[ai.routes]` theo vai trò |
| Lồng tiếng tự viết và MoneyPrinterTurbo | Chỉ MoneyPrinterTurbo; tự viết chỉ là phương án lùi nếu S12 không đạt |
| Cắt theo nhịp nhạc | Chỉ có ở Studio |
| Phân tích video tham khảo ở xu hướng và ở Studio | Chạy rea-video một lần, lưu thư mục kết quả, Studio dùng lại |
| "Làm lại" tự động và thủ công | Hai bộ đếm riêng, bản cũ thành `superseded` |
| Giao diện và Telegram | Cùng gọi một bộ hàm nghiệp vụ; bot không có logic riêng |
| Trạm việc tay ở giai đoạn 18 và 14 | Thiết kế ghi ở 18, hiện thực ở 14 cùng kho cảnh phụ |
| Ô chọn tài khoản đích | Có từ giai đoạn 07 (khi có tài khoản), không phải 06 |
| Hạn mức tiền | Ba hạn mức tách riêng, chỉ tính cho đường API |
| Thông báo Telegram | Mỗi loại thông báo có một nơi phát sinh; giờ yên lặng và giới hạn số tin áp ở một lớp gửi chung |

Tính năng bổ sung khi rà soát vì trước đó thiếu: sao lưu cơ sở dữ liệu hằng đêm, dọn đĩa và cảnh báo đầy đĩa, lưu kết quả kiểm tra định dạng và câu bị đánh dấu vào video, trạng thái `superseded` và `waiting_quota`.

---

## 15. Giả định

1. Đội có quyền với mọi footage, nhạc và hiệu ứng âm thanh nạp vào app.
2. Mỗi tài khoản Instagram là Business/Creator và liên kết một Page.
3. Chủ máy sở hữu các gói thuê bao AI và tự đăng nhập CLI trên máy chủ.
4. Sản lượng 5–10 video mỗi ngày, mỗi video 15–30 giây.
5. Người dùng chấp nhận tính chất vùng xám của việc tải video tham khảo trong giới hạn `BR-REF-*`, và (2026-11-14) của việc lấy dữ liệu xu hướng qua dịch vụ quét bên thứ ba Apify, trái điều khoản của Meta và TikTok; rủi ro chính là bộ quét hỏng khi nền tảng đổi trang.

## 16. Rủi ro chính

| Rủi ro | Ảnh hưởng | Xử lý |
|---|---|---|
| Meta yêu cầu App Review để đăng công khai | Không đăng tự động được trong đợt 1 | `FR-PST-13`; nộp review sớm |
| TikTok không qua audit | TikTok luôn cần một thao tác tay | Hộp nháp là trạng thái chấp nhận được |
| Điều khoản gói thuê bao thay đổi | Mất đường gói thuê bao | Đổi thứ tự trong bộ định tuyến sang API |
| Hạn mức gói thuê bao không đủ | Việc phải chờ | Chính sách `ask`/`auto`; giờ thấp điểm; cân nhắc gói cao hơn |
| rea-video, video-shotcraft, MoneyPrinterTurbo không chạy tốt trên Windows | Mất một phần tính năng | Phương án lùi ở mục 17 |
| Video na ná nhau làm giảm reach | Hiệu quả kém | Công thức từ xu hướng, gói chỉ dẫn, loại bản trùng, người duyệt |
| Nền tảng nén lại làm mất chi tiết sản phẩm | Sai lệch hình | Xem lại bài đầu tiên, chỉnh chất lượng bản master |
| Lịch triển khai 22–26 ngày làm việc không có đệm | Trượt | Thứ tự cắt trong kế hoạch |

## 17. Điểm chờ kiểm chứng và phương án lùi

| Mã | Câu hỏi | Nếu không đạt |
|---|---|---|
| S1 | rea-video chạy trên Windows bằng CLI | Tách shot bằng PySceneDetect; phân tích video tham khảo bằng Gemini |
| S2, S3 | Meta đăng công khai không cần review; loại và hạn token | Nộp review, `FR-PST-13`; token 60 ngày kèm cảnh báo |
| S4 | OAuth trả về `localhost` | Trang callback tĩnh HTTPS, người dùng dán mã |
| S5 | TikTok hộp nháp, hồ sơ audit | Đăng riêng tư rồi đổi công khai tay; hoặc gói đăng tay |
| S6 | Quyền Ad Library, lấy file | Chỉ số liệu và link; hoặc bỏ nguồn này |
| S7 | Model và giá Gemini | Gửi khung hình thay video |
| S8 | Giọng tiếng Việt chấp nhận được | Không lồng tiếng Việt, chỉ phụ đề |
| S9 | FFmpeg có libass, font Việt | Dùng bản build khác |
| S10 | Giới hạn chính thức từng nền tảng | Dùng mức an toàn của `BR-FMT-03` |
| S11 | Hai skill dựng video dọc trên Windows; chi phí; giấy phép Remotion | Studio chỉ phân tích và viết kịch bản, dựng bằng chế độ Nhanh; hoặc bỏ Studio |
| S12 | MoneyPrinterTurbo giữ thứ tự, không cắt khung, có giọng Việt | Chỉ dùng phần giọng và phụ đề; hoặc tự viết phần lồng tiếng |
| S13 | `claude -p`, `gemini -p` bằng gói thuê bao; điều khoản; Meta Model API | Vai trò tương ứng dùng API có hạn mức; Muse chỉ ở trạm việc tay |
