"""Diagnostic HTML fallback page when Next.js Studio UI fails to start."""
from __future__ import annotations

import html

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from videocreator.paths import AppPaths

router = APIRouter()


@router.get("/ui-unavailable", response_class=HTMLResponse)
async def serve_ui_unavailable_diagnostic(request: Request) -> HTMLResponse:
    """Renders a self-contained Vietnamese diagnostic screen instead of silently dropping users into V1."""
    paths: AppPaths = request.app.state.paths
    boot_log = html.escape(str(paths.logs_dir / "desktop_boot.log"))
    body = f"""<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Video Creator V2 — Giao diện Studio chưa sẵn sàng</title>
  <style>
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      background: #0b0f19;
      color: #e2e8f0;
      display: flex;
      min-height: 100vh;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }}
    .panel {{
      max-width: 680px;
      width: 100%;
      background: #111827;
      border: 1px solid #1e293b;
      border-radius: 16px;
      padding: 28px;
      box-shadow: 0 20px 45px rgba(0, 0, 0, 0.45);
    }}
    h1 {{ margin: 0 0 10px; font-size: 21px; color: #f8fafc; }}
    p {{ margin: 0 0 14px; line-height: 1.6; color: #cbd5e1; font-size: 14px; }}
    .box {{
      background: #0f172a;
      border: 1px solid #334155;
      border-radius: 10px;
      padding: 12px 14px;
      margin: 14px 0 18px;
      font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
      font-size: 12.5px;
      color: #38bdf8;
      word-break: break-all;
    }}
    ul {{ margin: 0 0 20px; padding-left: 20px; color: #cbd5e1; font-size: 13.5px; line-height: 1.65; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    .btn {{
      display: inline-flex;
      align-items: center;
      padding: 9px 16px;
      border-radius: 9px;
      font-size: 13.5px;
      font-weight: 600;
      text-decoration: none;
      cursor: pointer;
      border: 1px solid transparent;
    }}
    .btn-primary {{ background: #2563eb; color: #ffffff; }}
    .btn-secondary {{ background: #1e293b; border-color: #334155; color: #e2e8f0; }}
  </style>
</head>
<body>
  <main class="panel" role="alert">
    <h1>Giao diện Video Creator V2 Studio chưa khởi động được</h1>
    <p>
      Máy chủ API nội bộ đã sẵn sàng, nhưng tiến trình giao diện Next.js Standalone chưa phản hồi.
      Ứng dụng không tự động chuyển ngầm về giao diện V1 cũ để tránh hiển thị thiếu các Studio mới.
    </p>
    <div class="box">Nhật ký khởi động: {boot_log}</div>
    <ul>
      <li>Kiểm tra tệp <code>runtime/node/node.exe</code> và <code>web-next/.next/standalone/server.js</code> trong thư mục cài đặt.</li>
      <li>Nếu đang chạy môi trường phát triển, hãy chạy <code>npm run build</code> trong thư mục <code>web-next</code>.</li>
      <li>Xem chi tiết lỗi cổng mạng hoặc tiến trình tại tệp nhật ký ở trên rồi bấm thử lại.</li>
    </ul>
    <div class="actions">
      <button type="button" class="btn btn-primary" onclick="window.location.reload()">Thử kết nối lại</button>
      <a class="btn btn-secondary" href="/api/v1/health">Kiểm tra API (/api/v1/health)</a>
      <a class="btn btn-secondary" href="/">Mở giao diện dự phòng V1 (đã ngừng phát triển)</a>
    </div>
  </main>
</body>
</html>
"""
    return HTMLResponse(content=body, status_code=200, headers={"Cache-Control": "no-store"})
