"""FreeCut (MIT) editor asset resolution and `/api/editor/*` bridge handlers (V2-EDT-01..03)."""
from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path
from typing import Any

from videocreator.config import load_settings
from videocreator.db import get_conn, query_one, record_audit
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths, REPO_ROOT
from videocreator.pipeline.export import extract_cover_frame
from videocreator.pipeline.preflight import check_all_platforms
from videocreator.pipeline.probe import probe_video
from videocreator.pipeline.qc import run_video_qc
from videocreator.safe_paths import safe_upload_stem

_LIVE_HEARTBEATS: dict[str, str] = {}


def find_freecut_dist_dir() -> Path | None:
    """Finds bundled or env-configured MIT FreeCut static editor assets."""
    candidates: list[Path] = []
    env_dir = (os.environ.get("VIDEOCREATOR_FREECUT_DIR") or "").strip()
    if env_dir:
        candidates.append(Path(env_dir).expanduser().resolve())
    candidates.append(REPO_ROOT / "tools" / "freecut")
    candidates.append(REPO_ROOT / "tools" / "freecut-dist")
    for cand in candidates:
        if (cand / "index.html").is_file():
            return cand
    return None


def get_bridge_job_state(paths: AppPaths, job_key: str) -> dict[str, Any]:
    """Builds the FreeCut `BridgeState` JSON for `/api/editor/jobs/{job}`."""
    try:
        video_id = int(str(job_key).strip())
    except ValueError:
        return {"state": "missing"}

    v_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if v_row is None or not v_row.get("output_path"):
        return {"state": "missing"}

    rel_out = str(v_row["output_path"]).lstrip("/")
    mp4_path = paths.media_dir / rel_out
    if not mp4_path.exists():
        return {"state": "missing"}

    info = probe_video(mp4_path)
    plan = loads_or(v_row.get("plan_json"), {})
    if not isinstance(plan, dict):
        plan = {}

    subs: list[dict[str, Any]] = []
    cache = loads_or(v_row.get("render_cache_json"), {})
    sub_rel = str(cache.get("sub_events_file") or "") if isinstance(cache, dict) else ""
    if sub_rel and (paths.media_dir / sub_rel).exists():
        raw_subs = loads_or((paths.media_dir / sub_rel).read_text(encoding="utf-8"), [])
        if isinstance(raw_subs, list):
            for idx, ev in enumerate(raw_subs, start=1):
                if isinstance(ev, dict):
                    subs.append(
                        {
                            "id": f"sub_{idx}",
                            "startSeconds": float(ev.get("start_s") or 0.0),
                            "endSeconds": float(ev.get("end_s") or 1.0),
                            "text": str(ev.get("text") or ""),
                        }
                    )

    if not subs:
        cursor = 0.0
        for idx, sh in enumerate(plan.get("shots") or [], start=1):
            dur = max(0.5, float(sh.get("duration_s") or 2.0))
            txt = str(sh.get("text") or "").strip()
            if txt:
                subs.append(
                    {
                        "id": f"sub_{idx}",
                        "startSeconds": round(cursor, 3),
                        "endSeconds": round(cursor + dur, 3),
                        "text": txt,
                    }
                )
            cursor += dur

    return {
        "state": "ready",
        "project": {
            "job": str(video_id),
            "name": str(plan.get("title") or f"Video #{video_id}"),
            "width": info.width or 1080,
            "height": info.height or 1920,
            "fps": int(round(info.fps)) or 30,
            "duration": round(info.duration_s, 3),
            "file_name": mp4_path.name,
            "video_url": f"/files/{rel_out}",
            "sub_style": {"font_size": 52, "bottom": 280},
            "subs": subs,
        },
    }


def record_editor_heartbeat(job_key: str, *, closing: bool = False) -> dict[str, Any]:
    clean_key = (job_key or "").strip()
    if closing:
        _LIVE_HEARTBEATS.pop(clean_key, None)
    elif clean_key:
        _LIVE_HEARTBEATS[clean_key] = "active"
    return {"ok": True, "job": clean_key, "closing": closing}


def save_editor_result(
    paths: AppPaths,
    *,
    raw_bytes: bytes,
    filename: str = "freecut_export.mp4",
    job_key: str | None = None,
    workspace_id: int = 1,
) -> dict[str, Any]:
    """Saves an exported FreeCut timeline video back into Video Creator and runs preflight + QC."""
    if not raw_bytes or len(raw_bytes) < 128:
        raise ValueError("Uploaded FreeCut export video is empty or invalid")

    ext = Path(filename or "export.mp4").suffix.lower()
    if ext not in (".mp4", ".mov", ".webm", ".mkv"):
        ext = ".mp4"
    safe_orig = f"{safe_upload_stem(filename, fallback='export')}{ext}"

    target_video_id: int | None = None
    if job_key:
        try:
            cand_id = int(str(job_key).strip())
            if query_one(paths.db_file, "SELECT id FROM videos WHERE id = ?", (cand_id,)):
                target_video_id = cand_id
        except ValueError:
            target_video_id = None

    token = secrets.token_hex(4)
    rel_out = (
        f"output/video_{target_video_id}_freecut_{token}{ext}"
        if target_video_id is not None
        else f"output/freecut_{token}_{safe_orig}"
    )
    dest_path = paths.media_dir / rel_out
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(raw_bytes)

    info = probe_video(dest_path)
    settings = load_settings(paths.config_file)
    preflight_map = check_all_platforms(dest_path, settings)
    qc_report = run_video_qc(dest_path, expect_voice=False)

    rel_cover = f"output/cover_freecut_{token}.jpg"
    try:
        extract_cover_frame(dest_path, paths.media_dir / rel_cover, at_s=min(1.0, max(0.1, info.duration_s * 0.4)))
    except Exception:
        rel_cover = ""

    with get_conn(paths.db_file) as conn:
        if target_video_id is not None:
            conn.execute(
                """
                UPDATE videos
                SET output_path = ?,
                    cover_path = COALESCE(NULLIF(?, ''), cover_path),
                    duration_s = ?,
                    preflight_json = ?,
                    qc_json = ?,
                    status = 'pending_approval',
                    error = NULL
                WHERE id = ?
                """,
                (
                    rel_out,
                    rel_cover,
                    round(info.duration_s, 3),
                    json.dumps(preflight_map, ensure_ascii=False),
                    json.dumps(qc_report, ensure_ascii=False),
                    target_video_id,
                ),
            )
            video_id = target_video_id
        else:
            cur = conn.execute(
                """
                INSERT INTO videos (
                    workspace_id, engine, status, plan_json,
                    output_path, cover_path, duration_s, preflight_json, qc_json
                )
                VALUES (?, 'ffmpeg', 'pending_approval', '{}', ?, ?, ?, ?, ?)
                """,
                (
                    int(workspace_id),
                    rel_out,
                    rel_cover or None,
                    round(info.duration_s, 3),
                    json.dumps(preflight_map, ensure_ascii=False),
                    json.dumps(qc_report, ensure_ascii=False),
                ),
            )
            video_id = int(cur.lastrowid)

        record_audit(
            conn,
            actor="freecut_bridge",
            action="save_editor_result",
            object_type="video",
            object_id=video_id,
            detail=f"{rel_out} ({len(raw_bytes)} bytes)",
        )

    return {
        "path": rel_out,
        "name": dest_path.name,
        "size": len(raw_bytes),
        "video_id": video_id,
        "qc": qc_report,
    }
