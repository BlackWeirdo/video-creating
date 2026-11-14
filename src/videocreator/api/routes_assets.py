"""Audio asset management routes (music and SFX, Phase 05, FR-RND-03)."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from videocreator import __version__
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.paths import AppPaths, find_ffmpeg_binary

router = APIRouter()

ALLOWED_AUDIO_EXTENSIONS: set[str] = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


def probe_audio_duration(file_path: Path) -> float:
    """Probes an audio file using `ffprobe` and returns its duration in seconds."""
    ffprobe_bin = find_ffmpeg_binary("ffprobe")
    proc = subprocess.run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            str(file_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError(f"ffprobe failed on audio file {file_path.name}: {proc.stderr[:200]}")
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    if not any(s.get("codec_type") == "audio" for s in streams):
        raise ValueError(f"File '{file_path.name}' contains no valid audio stream")
    dur = float((data.get("format") or {}).get("duration") or 0.0)
    if dur <= 0.1:
        raise ValueError(f"Audio duration invalid ({dur}s)")
    return round(dur, 3)


def import_audio_asset(
    paths: AppPaths,
    source_file: Path,
    *,
    kind: Literal["music", "sfx"] = "music",
    title: str = "",
) -> int:
    ext = source_file.suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise ValueError(f"Unsupported audio extension '{ext}'")

    duration_s = probe_audio_duration(source_file)
    meta = {"title": title.strip() or source_file.stem, "original_name": source_file.name}

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO assets (kind, path, duration_s, meta_json)
            VALUES (?, 'pending', ?, ?)
            """,
            (kind, duration_s, json.dumps(meta, ensure_ascii=False)),
        )
        asset_id = int(cur.lastrowid or 0)
        rel_path = f"assets/{kind}_{asset_id}{ext}"
        dest = paths.media_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, dest)
        conn.execute("UPDATE assets SET path = ? WHERE id = ?", (rel_path, asset_id))
        record_audit(
            conn,
            actor="ui",
            action="asset.imported",
            object_type="asset",
            object_id=asset_id,
            detail=f"{kind}: {meta['title']} ({duration_s}s)",
        )
    return asset_id


@router.get("/assets", response_class=HTMLResponse)
async def assets_page(
    request: Request,
    msg: str | None = None,
) -> HTMLResponse:
    paths: AppPaths = request.app.state.paths
    cfg = load_settings(paths.config_file)
    templates = Jinja2Templates(directory=str(paths.templates_dir))

    raw = query_all(
        paths.db_file,
        "SELECT * FROM assets WHERE kind IN ('music', 'sfx') ORDER BY id DESC",
    )
    assets: list[dict[str, Any]] = []
    for r in raw:
        try:
            meta = json.loads(r.get("meta_json") or "{}")
        except Exception:
            meta = {}
        assets.append({**r, "title": meta.get("title") or r["path"]})

    return templates.TemplateResponse(
        request,
        "assets.html",
        {
            "page": "assets",
            "settings": cfg,
            "assets": assets,
            "msg": msg,
            "version": __version__,
        },
    )


@router.post("/assets/upload")
async def upload_audio_asset(
    request: Request,
    file: UploadFile = File(...),
    kind: str = Form("music"),
    title: str = Form(""),
) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    filename = file.filename or "audio.mp3"
    ext = Path(filename).suffix.lower() or ".mp3"
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Đuôi nhạc '{ext}' không hợp lệ")

    clean_kind: Literal["music", "sfx"] = "sfx" if kind == "sfx" else "music"
    tmp_path = paths.work_dir / f"upload_aud_{hashlib.md5(filename.encode('utf-8')).hexdigest()}{ext}"
    try:
        with tmp_path.open("wb") as out_f:
            while chunk := await file.read(1024 * 1024):
                out_f.write(chunk)
        import_audio_asset(paths, tmp_path, kind=clean_kind, title=title or Path(filename).stem)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    return RedirectResponse(url="/assets?msg=uploaded", status_code=303)


@router.post("/assets/{asset_id}/delete")
async def delete_audio_asset(request: Request, asset_id: int) -> RedirectResponse:
    paths: AppPaths = request.app.state.paths
    row = query_one(paths.db_file, "SELECT * FROM assets WHERE id = ?", (asset_id,))
    if row is None:
        raise HTTPException(status_code=404, detail="Asset not found")
    rel_path = str(row.get("path") or "")
    if rel_path:
        (paths.media_dir / rel_path).unlink(missing_ok=True)
    with get_conn(paths.db_file) as conn:
        conn.execute("DELETE FROM assets WHERE id = ?", (asset_id,))
        record_audit(
            conn,
            actor="ui",
            action="asset.deleted",
            object_type="asset",
            object_id=asset_id,
            detail=rel_path,
        )
    return RedirectResponse(url="/assets?msg=deleted", status_code=303)
