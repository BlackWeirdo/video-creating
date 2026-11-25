"""FreeCut (MIT) static editor mount & `/api/editor/*` bridge endpoints."""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel

from videocreator.editor_bridge import (
    find_freecut_dist_dir,
    get_bridge_job_state,
    record_editor_heartbeat,
    save_editor_result,
)
from videocreator.paths import AppPaths
from videocreator.safe_paths import UnsafePathError, resolve_within

router = APIRouter()

_FALLBACK_EDITOR_HTML = """<!doctype html>
<html lang="vi">
<head>
  <meta charset="utf-8" />
  <title>Trình dựng Timeline FreeCut Bridge</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #0b0f17; color: #e2e8f0; padding: 24px; }
    .card { max-width: 720px; margin: 0 auto; background: #111827; border: 1px solid #1e293b; border-radius: 12px; padding: 20px; }
    code { background: #1e293b; padding: 2px 6px; border-radius: 4px; color: #38bdf8; }
  </style>
</head>
<body>
  <div class="card">
    <h2>Trình dựng Timeline (FreeCut Bridge)</h2>
    <p>Cầu nối <code>/api/editor/*</code> đã sẵn sàng. Hãy dùng tab <strong>Multi-Track Timeline Composer</strong> hoặc gắn bản build FreeCut MIT vào <code>tools/freecut-dist/</code>.</p>
  </div>
</body>
</html>
"""


class HeartbeatBody(BaseModel):
    job: str = ""
    closing: bool = False


def _serve_bundle_file(dist_dir: Path, rel_subpath: str) -> FileResponse:
    try:
        target = resolve_within(dist_dir, rel_subpath)
    except UnsafePathError as exc:
        raise HTTPException(status_code=403, detail="Forbidden editor asset path") from exc
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Editor asset not found")
    media_type, _ = mimetypes.guess_type(str(target))
    return FileResponse(path=str(target), media_type=media_type or "application/octet-stream")


@router.get("/freecut")
@router.get("/freecut/{subpath:path}")
async def serve_freecut_editor(subpath: str = "") -> Any:
    dist_dir = find_freecut_dist_dir()
    if dist_dir is None:
        return HTMLResponse(_FALLBACK_EDITOR_HTML)
    clean = subpath.strip().lstrip("/")
    if not clean:
        return _serve_bundle_file(dist_dir, "index.html")
    try:
        cand = resolve_within(dist_dir, clean)
    except UnsafePathError as exc:
        raise HTTPException(status_code=403, detail="Forbidden") from exc
    if cand.is_file():
        return _serve_bundle_file(dist_dir, clean)
    return _serve_bundle_file(dist_dir, "index.html")


@router.get("/assets/{subpath:path}")
async def serve_freecut_root_assets(subpath: str) -> FileResponse:
    dist_dir = find_freecut_dist_dir()
    if dist_dir is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return _serve_bundle_file(dist_dir, f"assets/{subpath}")


@router.get("/moss-tts/{subpath:path}")
async def serve_freecut_moss_tts(subpath: str) -> FileResponse:
    dist_dir = find_freecut_dist_dir()
    if dist_dir is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    return _serve_bundle_file(dist_dir, f"moss-tts/{subpath}")


@router.get("/api/editor/jobs/{job}")
async def api_editor_get_job(request: Request, job: str) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    return JSONResponse(get_bridge_job_state(paths, job))


@router.post("/api/editor/jobs/{job}/prepare")
async def api_editor_prepare_job(job: str) -> JSONResponse:
    return JSONResponse({"ok": True, "job": job})


@router.post("/api/editor/heartbeat")
async def api_editor_heartbeat(body: HeartbeatBody) -> JSONResponse:
    return JSONResponse(record_editor_heartbeat(body.job, closing=body.closing))


@router.put("/api/editor/result")
async def api_editor_put_result(
    request: Request,
    name: str = Query(default="freecut_export.mp4"),
    job: str | None = Query(default=None),
    workspace_id: int = Query(default=1),
) -> JSONResponse:
    paths: AppPaths = request.app.state.paths
    raw = await request.body()
    try:
        saved = save_editor_result(
            paths,
            raw_bytes=raw,
            filename=name,
            job_key=job,
            workspace_id=workspace_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return JSONResponse(saved)
