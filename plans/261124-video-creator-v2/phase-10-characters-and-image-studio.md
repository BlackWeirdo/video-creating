# Phase 10: Nhân vật Cố định & AI Image Studio kèm Tách nền PNG (`V2-CHR-01..05`)

## Mục tiêu
1. Bổ sung migration `022_v2_characters_and_image_studio.sql` (`characters`, `ai_images`) và bộ lọc tách nền FFmpeg `colorkey`/`chromakey` trong `CREATIVE_REMIX_FILTERS`.
2. Xây dựng `src/videocreator/pipeline/characters.py`: giữ đồng nhất diện mạo (`seed` + `appearance_prompt` + ảnh tham chiếu), tạo ảnh AI & chặn tạo ảnh sản phẩm AI trong workspace `strict_footage` (`BR-PRD-01`), tách nền `rembg` / FFmpeg RGBA PNG, và chuyển ảnh thành shot chuyển động (`zoompan` `5.4s`).
3. Cung cấp `/api/v1/characters/*`, `/api/v1/images/*` và kiểm thử `tests/test_v2_phase10_characters_image_studio.py`.
