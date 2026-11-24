# Phase 06: Trình quản lý Model AI Cục bộ & Bể xoay vòng API Key (`V2-AI-01..03`)

## Mục tiêu
1. Bổ sung thư mục `models/` trong `AppPaths` (`VIDEOCREATOR_DATA/models`) và bảng `local_models` quản lý 6 model tùy chọn tải theo nhu cầu (`faster_whisper_small`, `uvr_mdx_kim_vocal2`, `vieneu_tts_vi`, `paddle_lama_inpaint`, `rembg_u2net`, `wav2lip_gan`).
2. Cung cấp adapter tách nhạc/giọng nói (`separate_vocals_and_bgm`) và chép lời mốc thời gian (`transcribe_media_segments`) ưu tiên model cục bộ khi đã cài, kèm fallback FFmpeg DSP chạy thật trên mọi máy.
3. Xây dựng bảng `api_key_pool` + `src/videocreator/ai/key_pool.py` xoay vòng nhiều API Key theo từng nhà cung cấp (`gemini`, `claude`, `openai_compat`, `fal`, `elevenlabs`, `muse`), tự động cooldown khi dính quota/429 và mã hóa key qua `SecretsStore`.
4. Cung cấp REST API `/api/v1/models/*` và `/api/v1/key-pool/*` kèm kiểm thử `tests/test_v2_phase06_models_and_key_pool.py`.
