"""Last stage of a Studio render: audio, master export, cover, format check, and the version record."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from videocreator.config import Settings
from videocreator.db import get_conn, query_one, record_audit
from videocreator.paths import AppPaths
from videocreator.pipeline.export import extract_cover_frame, normalize_to_master
from videocreator.pipeline.preflight import check_all_platforms
from videocreator.studio.audio import build_audio_track
from videocreator.studio.versions import append_studio_version

logger = logging.getLogger("videocreator.studio.agent")

VOICE_OFFLINE_NOTE = "Không lồng tiếng được (dịch vụ MoneyPrinterTurbo không phản hồi); video chỉ có phụ đề"


_ALLOWED_SESSION_COLS = frozenset(
    {"status", "error", "pending_prompt", "session_ref", "cost_usd", "versions_json", "options_json"}
)


def update_session(db_file: Path, session_id: int, **fields: Any) -> None:
    if not fields:
        return
    unknown = set(fields) - _ALLOWED_SESSION_COLS
    if unknown:
        raise ValueError(f"Unsupported studio_sessions column(s): {sorted(unknown)}")
    cols = ", ".join(f"{name} = ?" for name in fields)
    with get_conn(db_file) as conn:
        conn.execute(f"UPDATE studio_sessions SET {cols} WHERE id = ?", (*fields.values(), session_id))


def _asset_path(paths: AppPaths, asset_id: Any, kind: str) -> Path | None:
    if not asset_id:
        return None
    row = query_one(paths.db_file, "SELECT path FROM assets WHERE id = ? AND kind = ?", (int(asset_id), kind))
    if row is None:
        return None
    path = paths.media_dir / str(row["path"])
    return path if path.exists() else None


def export_studio_version(
    paths: AppPaths,
    settings: Settings,
    *,
    session_id: int,
    video_id: int,
    session_dir: Path,
    version_no: int,
    raw_out: Path,
    scenes: list[dict[str, Any]],
    clips: list[Path | None] | None,
    voice_lang: str,
    options: dict[str, Any],
    version_prompt: str,
    session_ref: str | None,
    cost_usd: float = 0.0,
    send_notification: bool = True,
) -> tuple[dict[str, Any], float]:
    """Adds audio (`FR-STD-06`), exports through the same path as every other engine (`BR-FMT-02`),
    sends the video for approval, and records the version. Returns `(version, duration_s)`."""
    notes = ["Studio: chữ có hiệu ứng chuyển động trên footage"]
    if voice_lang in ("vi", "en") and clips is None:
        notes.append(VOICE_OFFLINE_NOTE)
    audio_track = build_audio_track(
        scenes, clips, _asset_path(paths, options.get("sfx_asset_id"), "sfx"), session_dir / "out" / f"v{version_no}.audio.wav"
    )
    rel_out = f"output/video_{video_id}.mp4"
    rel_cover = f"output/cover_{video_id}.jpg"
    duration_s = normalize_to_master(
        raw_out, paths.media_dir / rel_out,
        music_path=_asset_path(paths, options.get("music_asset_id"), "music"), voice_path=audio_track,
    )
    extract_cover_frame(paths.media_dir / rel_out, paths.media_dir / rel_cover, at_s=1.0)
    preflight = check_all_platforms(paths.media_dir / rel_out, settings)
    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            UPDATE videos
            SET status = 'pending_approval', engine = 'studio', output_path = ?, cover_path = ?,
                duration_s = ?, preflight_json = ?, error = NULL, quality_notes = ?
            WHERE id = ? AND status IN ('planned', 'pending_approval', 'failed', 'rendered')
            """,
            (rel_out, rel_cover, round(duration_s, 3), json.dumps(preflight, ensure_ascii=False), " | ".join(notes), video_id),
        )
        record_audit(
            conn, actor="studio_agent", action="video.rendered", object_type="video", object_id=video_id,
            detail=f"studio session #{session_id} v{version_no}, {duration_s:.2f}s",
        )
    shutil.copy2(session_dir / "src" / "Scene.tsx", session_dir / "out" / f"v{version_no}.Scene.tsx")
    shutil.copy2(session_dir / "plan.json", session_dir / "out" / f"v{version_no}.plan.json")

    version = append_studio_version(
        paths.db_file, session_id, prompt=version_prompt,
        output_path=f"studio/{session_id}/out/v{version_no}.mp4",
        cost_usd=cost_usd, session_ref=session_ref, status="done",
    )
    update_session(paths.db_file, session_id, error=None)
    if send_notification:
        notify_studio_pending(paths, video_id)
    return version, duration_s


def notify_studio_pending(paths: AppPaths, video_id: int) -> None:
    try:
        from videocreator.tg.approval_notify import notify_pending

        notify_pending(paths, video_id)
    except Exception as exc:  # the video is ready either way; the approval queue in the UI still shows it
        logger.warning("notify_pending failed for studio video #%d: %s", video_id, exc)
