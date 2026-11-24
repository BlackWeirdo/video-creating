# Kế hoạch Triển khai Tổng thể: Video Creator V2

Ngày lập: 2026-11-24 | Nhánh Git: `v2`  
Đặc tả hệ thống: [docs/video-creator-v2-spec.md](../../docs/video-creator-v2-spec.md)

---

## 1. Mục tiêu Hợp nhất

Xây dựng **Video Creator V2** trên nhánh `v2` của repo `c:\Users\ADMIN\video-creating`, kết hợp:
- **Lõi `video-creating` (V1)**: Trend 5 nguồn, phân tích công thức `rea-video`, kho Sản phẩm/Footage/Shot, duyệt Telegram/Web, đăng bài 4 MXH + R2, kiểm soát ngân sách AI & Subscription-First.
- **Kỹ thuật xử lý gọn nhẹ kiểu `iContent`**: Pipeline hậu kỳ FFmpeg/ASS tự chủ (không còn phụ thuộc MoneyPrinterTurbo) + Studio Việt hóa / Reup / Hybrid Remix / Quốc tế hóa.
- **Hệ sinh thái Multi-Studio & UI kiểu `iCast`**: Đa thương hiệu (`Workspace`), Next.js 15 Standalone + React 19, Video Style Presets, đủ 7 nhóm Studio sáng tạo, đăng thêm YouTube + Gói `.zip`, đóng gói bộ cài `.exe` độc lập cho máy nhân viên.

---

## 2. Lộ trình 4 Đợt Cuốn chiếu

| Đợt | Trọng tâm | Thành quả chạy thật sau khi hoàn thành |
|---|---|---|
| **Đợt 1** *(đã hoàn thành)* | Nền móng Multi-Workspace, Hàng đợi 2 làn, Video Style Engine (gỡ MPT), YouTube + Gói `.zip`, `/api/v1/*` và Shell Next.js 15 cho toàn bộ tính năng lõi | Nền tảng đa thương hiệu chạy trên Next.js 15 + FastAPI, dựng video `9:16` đẹp hơn V1 (sub nhảy chữ, ducking, QC) và đăng đủ 5 MXH + `.zip` |
| **Đợt 2** *(đang thực hiện)* | Trình quản lý Model AI tải thêm + Studio Việt hóa/Reup/Hybrid Remix/Quốc tế hóa + Batch & Product A/B Studio + Kênh Autopilot | Tự động hóa sản xuất số lượng lớn từ Xu hướng, Sản phẩm hoặc Việt hóa/Remix và tự chạy lịch cho kênh vệ tinh |
| **Đợt 3** | Characters & AI Image Studio + News-to-Video + Nhúng trình dựng FreeCut (MIT) + Visual Workflow Node (`@xyflow/react`) | Hoàn thiện bộ công cụ đồng nhất nhân vật, tạo ảnh AI, tin tức, cắt ghép đa track và workflow kéo-thả |
| **Đợt 4** | Studio Tiểu thuyết, Sóng nhạc Podcast (`16:9`), Lip-sync AI + Welcome Wizard, Sao lưu/Khôi phục, Bộ cài `.exe` Inno Setup (+ tùy chọn Nuitka `.pyd`) | Xuất xưởng bộ cài `.exe` hoàn chỉnh cài độc lập cho từng máy nhân viên |

---

## 3. Chi tiết Các Phase trong Đợt 1

| Phase | Tên Phase | Phụ thuộc | Trạng thái | Tiến độ |
|---|---|---|---|---|
| **01** | [Nền móng Multi-Workspace, Hàng đợi 2 làn & `/api/v1` Core](phase-01-multi-workspace-and-dual-lane-queue.md) | Baseline V1 | Xong, test local đạt | 100% |
| **02** | [Video Style Engine, Phụ đề động, Auto-Ducking, QC & Gỡ MPT](phase-02-video-style-engine-and-qc.md) | Phase 01 | Xong, test local đạt | 100% |
| **03** | [Quản lý Kênh, Chính sách duyệt 3 cấp, YouTube & Gói `.zip`](phase-03-channels-youtube-and-publish-packs.md) | Phase 01, 02 | Xong, test local đạt | 100% |
| **04** | [Hoàn thiện Lớp JSON REST API `/api/v1/*` cho toàn bộ tính năng Đợt 1](phase-04-rest-api-v1-surface.md) | Phase 01, 02, 03 | Xong, test local đạt | 100% |
| **05** | [Giao diện Next.js 15 Standalone Studio Shell & Các màn hình Đợt 1](phase-05-nextjs-studio-shell-and-wave1-views.md) | Phase 04 | Xong, test local đạt | 100% |

```
Phase 01 (Workspace + Dual-Lane Queue + /api/v1 Core)
   ├──► Phase 02 (Video Style Engine + QC + Gỡ MPT)
   │       └──► Phase 03 (Channels + 3 Approval Modes + YouTube + .zip)
   │               └──► Phase 04 (Complete /api/v1/* JSON Surface)
   │                       └──► Phase 05 (Next.js 15 App Shell & Views)
```

---

## 3B. Chi tiết Các Phase trong Đợt 2

| Phase | Tên Phase | Phụ thuộc | Trạng thái | Tiến độ |
|---|---|---|---|---|
| **06** | [Trình quản lý Model AI Cục bộ & Bể xoay vòng API Key](phase-06-local-models-and-key-pool.md) | Đợt 1 | Xong, test local đạt | 100% |
| **07** | [Studio Việt hóa / Reup, Hybrid Remix & Quốc tế hóa](phase-07-localize-reup-hybrid-remix.md) | Phase 06 | Xong, test local đạt | 100% |
| **08** | [Batch Studio & Biến thể Sản phẩm A/B kèm Checkpoint Resume](phase-08-batch-and-product-ab-studio.md) | Phase 07 | Chờ | 0% |
| **09** | [Kênh Autopilot tự chạy & Giao diện Next.js Đợt 2](phase-09-autopilot-and-wave2-views.md) | Phase 08 | Chờ | 0% |

---

## 4. Ràng buộc Kỹ thuật & Quy chuẩn Kiểm thử

1. **Không làm vỡ V1 trong quá trình chuyển tiếp**: Toàn bộ route HTMX/Jinja2 cũ giữ nguyên hoạt động cho đến khi Phase 05 thay thế hoàn chỉnh; tất cả test `pytest -m local` hiện hữu phải tiếp tục xanh.
2. **Không dùng mock cho hạ tầng nội bộ**: Test phải chạy với SQLite thật (`WAL`, `foreign_keys = ON`), `JobWorker` thật, `TestClient` thật và FFmpeg thật (`C:\Users\ADMIN\AppData\Local\Programs\iCast\runtime\ffmpeg` + Node `v24.22.1` LTS cho các test Remotion).
3. **An toàn TOML & SQLite Migration**:
   - `config.py` ghi file bằng `tomli_w`: không dùng giá trị `None` trong Pydantic models của `Settings`.
   - `db.py` chạy migration trong `PRAGMA foreign_keys = ON`: các câu `ALTER TABLE ... ADD COLUMN workspace_id` không gắn inline `REFERENCES` kèm `DEFAULT 1`, việc kiểm tra tồn tại workspace thực hiện qua `workspaces.require_workspace()`.
4. **Quy ước ngôn ngữ (`CLAUDE.md`)**: Giao tiếp & tài liệu tiếng Việt; code, comment kỹ thuật và commit messages bằng tiếng Anh theo Conventional Commits.
