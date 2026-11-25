# Baseline Trước Refactor (`refactor/modularize`)

- **Nhánh gốc**: `ui-redesign` (`4fecb7c`)
- **Nhánh thực hiện**: `refactor/modularize`
- **Phiên bản khởi điểm**: `2.1.0`
- **Thời điểm đo**: `2026-11-25`

## Kết quả Kiểm chứng Baseline

| Hạng mục | Lệnh | Kết quả | Thời gian |
|---|---|---|---|
| **Frontend Lint & Typecheck** | `npm run lint` (`eslint src && tsc --noEmit`) | `0` lỗi | ~4s |
| **Frontend Standalone Build** | `npm run build` (`next build && copy-standalone-assets.mjs`) | `23/23` trang tĩnh + standalone assets | ~15s |
| **Backend & E2E Local Suite** | `.\.venv\Scripts\pytest.exe -m local -q` | **`259 passed, 1 skipped, 21 deselected`** | `544.44s` (9m 04s) |
| **Tổng số file test** | `tests/test_*.py` | `70` file (`57` có marker `local`, `21` gọi trực tiếp route V1) | — |

## Điểm nóng Kích thước File Trước Khi Tách

### Backend (`src/videocreator/`)
- `models_manager.py`: 845 dòng
- `tts/synthesizer.py`: 773 dòng
- `autopilot/rules.py`: 677 dòng
- `api/v1/routes_resources.py`: 644 dòng
- `pipeline/podcast_studio.py`: 626 dòng
- `pipeline/workflow_engine.py`: 617 dòng
- `api/v1/routes_production.py`: 568 dòng

### Frontend (`web-next/src/app/`)
- `approval/page.tsx`: 647 dòng
- `characters/page.tsx`: 596 dòng
- `welcome/page.tsx`: 590 dòng
- `trends/page.tsx`: 487 dòng
