# Thông báo Phát hành Nội bộ & Sổ tay Nhân sự — Video Creator V2 (`2.3.0`)

Tài liệu này dành cho đội ngũ biên tập viên, vận hành kênh và IT nội bộ khi cài đặt và sử dụng **Video Creator V2 (`2.3.0`)** từ bộ cài `VideoCreatorV2Setup.exe`.

---

## 1. Điểm Mới Nổi Bật ở Bản `2.3.0`

1. **Sinh ảnh Nhân vật & Bối cảnh AI thật qua Google Imagen 3 (`imagen-3.0-generate-002`)**:
   - Tại trang **Nhân vật & Ảnh AI** (`/characters`), **Bản tin** (`/news`), và **Tiểu thuyết** (`/novel`), khi đã khai báo `GEMINI_API_KEY` (hoặc khóa xoay vòng `gemini` trong Key Pool) và còn hạn mức ngân sách tạo sinh trong ngày (`generative_daily_usd`, mặc định `~$0.03`/ảnh), ứng dụng gọi trực tiếp **Google Imagen 3** để sinh ảnh nền/nhân vật chất lượng cao rồi ghép lớp nhân vật đã tách nền.
   - Khi chạy trên máy hoàn toàn offline, chưa điền `GEMINI_API_KEY`, hoặc chạm trần ngân sách ngày, ứng dụng **không báo lỗi dừng luồng** mà tự chuyển sang phông nền màu chuẩn hóa tại chỗ và gắn nhãn cảnh báo minh bạch (`SimulationBadge`) để nhân viên biết ngay đây là bản dựng nháp offline.
2. **Chuyển đổi Kênh (Workspace) mượt mà, không trộn dữ liệu**:
   - Toàn bộ **20/20 màn hình** đã đồng bộ cơ chế hủy truy vấn cũ tự động khi đổi Workspace trên thanh bên trái, đảm bảo danh sách sản phẩm, video và dự án luôn đúng kênh đang chọn.
3. **Chế độ chẩn đoán rõ ràng khi cổng giao diện gặp sự cố**:
   - Nếu cổng giao diện bị phần mềm diệt virus chặn, ứng dụng mở màn hình chẩn đoán tiếng Việt (`/ui-unavailable`) kèm hướng dẫn kiểm tra tệp nhật ký `desktop_boot.log`.

---

## 2. Giải Thích Các Nhãn Cảnh Báo Dự Phòng (`SimulationBadge`)

> **Lưu ý quan trọng cho Nhân viên Biên tập**: Khi thấy nhãn màu vàng cam trên thẻ ảnh hoặc dự án, đó **KHÔNG PHẢI lỗi phần mềm** mà là thông báo minh bạch cho biết bước đó vừa dùng chế độ dự phòng offline/tiết kiệm chi phí. Hãy làm theo cột **Cách bật chế độ AI thật** bên dưới nếu cần bản xuất thương mại hoàn chỉnh.

| Mã nhãn hiển thị | Ý nghĩa thực tế | Khi nào xuất hiện? | Cách bật chế độ AI thật 100% |
|---|---|---|---|
| `ai_image_canvas_placeholder` | Ảnh nền studio đang dùng khung màu hình học tạo tại chỗ thay vì ảnh sinh từ AI đám mây. | Chưa nhập `GEMINI_API_KEY`, đang tắt `api_fallback = "never"`, mất mạng, hoặc vượt hạn mức `generative_daily_usd`. | Vào **Cài đặt -> Khóa API & Bảo mật**, nhập `GEMINI_API_KEY` (hoặc thêm khóa `gemini` vào Key Pool) và đảm bảo hạn mức `generative_daily_usd >= $0.10`. |
| `cutout_colorkey_fallback` | Tách nền nhân vật đang dùng bộ lọc khóa màu FFmpeg thay vì mạng nơ-ron tách nền. | Chưa tải mô hình `rembg_u2net` về máy. | Vào **Cài đặt -> Mô hình AI Offline**, bấm tải và kiểm tra mô hình **`rembg_u2net`** (~176 MB, chạy CPU). |
| `ocr_inpaint_delogo_fallback` | Xóa phụ đề gốc (hardsub) đang dùng dải làm mờ `boxblur`/`delogo` thay vì tái tạo nền AI. | Chưa tải mô hình `lama_inpaint` hoặc chọn chế độ làm mờ nhanh. | Vào **Cài đặt -> Mô hình AI Offline**, tải mô hình **`lama_inpaint`** và chọn chế độ xóa phụ đề `inpaint` trong Studio Việt hóa (`/localize`). |
| `audio_sep_midside_fallback` | Tách lời & nhạc nền đang dùng lọc tần số Mid/Side thay vì AI tách nhạc chuyên sâu. | Chưa tải mô hình `mdx_vocal` (`Kim_Vocal_2.onnx`). | Vào **Cài đặt -> Mô hình AI Offline**, tải mô hình **`mdx_vocal`** để giữ trọn tiếng nhạc nền khi lồng tiếng mới. |
| `offline_nllb_translation` | Bản dịch kịch bản dùng mô hình dịch máy cục bộ NLLB-200 trên CPU thay vì Claude/Gemini. | Máy không có mạng hoặc hạn mức Claude/Gemini đang nghỉ chờ quota. | Có thể dùng ngay (đã dịch tiếng Việt thật trên CPU), hoặc đánh thức kết nối AI tại Cài đặt để biên tập văn phong mượt hơn. |
| `tts_tone_placeholder` | Giọng đọc đang là âm thanh kiểm tra nhịp (`test_tone`), chưa phải giọng người đọc thật. | Đang để `voice.vi_provider = "test_tone"` hoặc mạng chặn Edge-TTS khi chưa tải VieNeu-TTS. | Chọn `edge_tts` (khi có mạng) hoặc tải mô hình **`vieneu_tts`** trong **Cài đặt -> Mô hình AI Offline** để đọc giọng tiếng Việt hoàn toàn offline. |
| `lipsync_waveform_preview` | Chuyển động miệng nhân vật đang nhép theo biên độ âm lượng giọng đọc (2D Viseme) thay vì tái tạo khuôn mặt sâu. | Máy trạm chỉ có CPU phổ thông, chưa nạp mô hình Wav2Lip cục bộ. | Phù hợp cho avatar minh họa 2D/bản tin nhanh; với sản phẩm thật trong Workspace `strict_footage`, ưu tiên dùng cảnh quay người thật. |

---

## 3. Quy Tắc Bắt Buộc Theo Loại Kênh (`content_policy`)

1. **Kênh Hàng Thật (`strict_footage`)**:
   - Chỉ được dựng từ video quay sản phẩm thật của cửa hàng; hệ thống tự động chặn tạo ảnh sản phẩm bằng AI (`BR-PRD-01`), chặn Reup và chặn nhân bản giọng nói.
2. **Kênh Phối Trộn (`hybrid_remix`)**:
   - Cho phép lấy bố cục video xu hướng / bản tin và chèn cảnh sản phẩm thật vào giữa.
3. **Kênh Sáng Tạo AI (`full_ai`)**:
   - Cho phép dùng đầy đủ Tiểu thuyết AI, Bản tin AI, Ảnh Imagen 3 và Việt hóa đa ngôn ngữ.

---

## 4. Checklist Kiểm Tra 5 Phút Trên Máy Sạch (Windows 10 LTSC / Windows 11)

Khi cài đặt lần đầu trên máy nhân viên mới (không cần quyền Administrator, không cần cài sẵn Python/Node/FFmpeg):

- [ ] **Bước 1 — Cài đặt Offline**: Chạy `VideoCreatorV2Setup.exe` -> cài vào `%LOCALAPPDATA%\Programs\VideoCreatorV2`. Quá trình kích hoạt môi trường hoàn tất trong vài chục giây mà không cần kết nối Internet.
- [ ] **Bước 2 — Khởi chạy & Kiểm tra kết nối nội bộ**: Mở biểu tượng **Video Creator V2** ngoài Desktop -> cửa sổ Studio mở lên, góc trái dưới báo trạng thái kết nối xanh lá (`Ổn định`).
- [ ] **Bước 3 — Kiểm tra trang Cài đặt & Mô hình**: Vào `/settings` -> tab **Mô hình AI Offline** hiển thị danh sách mô hình cùng dung lượng ổ đĩa trống; tab **Giao diện** chuyển đổi Sáng / Tối tức thì.
- [ ] **Bước 4 — Dựng thử 1 video kiểm tra FFmpeg & Phụ đề**: Nhập thử 1 đoạn video ngắn tại `/footage` (hoặc tạo 1 Bản tin ngắn tại `/news` trên kênh `full_ai`), bấm **Dựng video** -> thanh tiến trình thời gian thực chạy đến `100%` và phát được video MP4 có tiếng + phụ đề tiếng Việt không lỗi phông chữ.
- [ ] **Bước 5 — Lưu ý Microsoft Visual C++ trên Windows 10 LTSC cũ**: Bộ cài đã ghim sẵn phiên bản thư viện tương thích trực tiếp với Windows 10 Enterprise LTSC. Nếu máy mới cài trắng hoàn toàn chưa từng có `vcruntime140.dll`, chỉ cần cài gói chuẩn `VC_redist.x64.exe` của Microsoft một lần duy nhất.
