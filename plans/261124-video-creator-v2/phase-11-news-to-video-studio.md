# Phase 11: Studio Tin tức / Bài viết sang Video & Gói đăng bài (`V2-NWS-01..04`)

## Mục tiêu
1. Bổ sung migration `023_v2_news_studio.sql` (`news_projects`) và `src/videocreator/pipeline/news_studio.py`.
2. Trích xuất sự kiện từ URL HTML / RSS / văn bản thô bằng `html.parser`, bảo toàn nguyên vẹn các số liệu (`preserved_tokens`), tóm tắt kịch bản 3 phần theo ngân sách âm tiết, dựng video qua FFmpeg + QC + gói đăng bài `.zip`.
3. Cung cấp `/api/v1/news/*` và kiểm thử `tests/test_v2_phase11_news_to_video.py`.
