# Phase 12: Cầu nối Trình dựng FreeCut (MIT) & Bộ ghép Đa track (`V2-EDT-01..05`)

## Mục tiêu
1. Bổ sung `tools/freecut-dist/` vào `.gitignore` và migration `024_v2_timeline_editor.sql` (`editor_projects`).
2. Triển khai cầu nối chuẩn FreeCut `bridge-api.ts` (`/freecut/*`, `/api/editor/jobs/{job}`, `/api/editor/jobs/{job}/prepare`, `/api/editor/heartbeat`, `PUT /api/editor/result`) cập nhật thẳng video thành phẩm & chạy QC/Preflight.
3. Xây dựng `/api/v1/editor/*` (`media`, `projects`, multi-track `render` trim/concat/audio/ASS) kèm kiểm thử `tests/test_v2_phase12_freecut_and_timeline_editor.py`.
