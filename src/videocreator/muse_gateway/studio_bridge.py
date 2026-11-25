"""Non-blocking bridge connecting News, Novel, Batch, Autopilot, Trends Remix & Telegram to `muse_tasks`."""
from __future__ import annotations

import json
import logging
from typing import Any

from videocreator.approvals import try_autopilot_approve
from videocreator.config import load_settings
from videocreator.db import get_conn, query_one
from videocreator.jobs import enqueue_job
from videocreator.jsonutil import loads_or
from videocreator.muse_gateway.dispatcher import register_muse_downstream_hook
from videocreator.muse_gateway.refs import validate_muse_refs_policy
from videocreator.muse_gateway.store import (
    ACTIVE_MUSE_TASK_STATUSES,
    create_muse_task,
    list_muse_tasks,
)
from videocreator.paths import AppPaths
from videocreator.pipeline.render import render_video
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.muse_gateway.studio_bridge")


class MuseMediaPendingError(Exception):
    """Raised inside a studio/workflow job when non-blocking Muse media tasks are queued/running."""


def ensure_project_muse_shots(
    paths: AppPaths,
    *,
    workspace_id: int,
    ref_type: str,
    ref_id: int,
    prompts_and_durations: list[tuple[str, float]],
    aspect_ratio: str = "9:16",
    character_id: int | None = None,
) -> tuple[list[int] | None, bool]:
    """Ensures `muse_tasks` video clips exist for a studio project without blocking the worker.

    Returns `(None, False)` while tasks are queued/running so the caller can park in `waiting_media`.
    Returns `(shot_ids, any_partial)` once all tasks have reached a terminal state.
    """
    ws = require_workspace(paths.db_file, workspace_id)
    if str(ws.get("content_policy") or "strict_footage") == "strict_footage":
        raise PermissionError(
            f"Workspace 'strict_footage' không cho phép sinh clip Muse tự động cho {ref_type}."
        )

    existing = list(
        reversed(
            list_muse_tasks(
                paths.db_file,
                workspace_id=workspace_id,
                ref_type=ref_type,
                ref_id=ref_id,
                limit=100,
            )
        )
    )
    if not existing:
        cfg = load_settings(paths.config_file).muse_gateway
        model = cfg.default_video_model or "muse-video"
        refs: list[dict[str, Any]] = []
        if character_id:
            ch = query_one(
                paths.db_file,
                "SELECT cutout_image_path, ref_image_path FROM characters WHERE id = ?",
                (int(character_id),),
            )
            if ch and (ch.get("cutout_image_path") or ch.get("ref_image_path")):
                refs.append({"type": "character", "id": int(character_id)})
        ratio = aspect_ratio if aspect_ratio in ("9:16", "16:9", "1:1", "4:3", "3:4") else "9:16"
        for prompt, dur in prompts_and_durations:
            create_muse_task(
                paths.db_file,
                workspace_id=workspace_id,
                kind="video",
                model=model,
                purpose=ref_type,
                ref_type=ref_type,
                ref_id=ref_id,
                prompt=prompt,
                params={"duration": max(4, min(60, int(round(dur)))), "ratio": ratio},
                refs=refs,
                priority=5,
            )
        return None, False

    if any(t["status"] in ACTIVE_MUSE_TASK_STATUSES for t in existing):
        return None, False

    ready = [t for t in existing if t["status"] == "succeeded" and t.get("shot_id")]
    if not ready:
        errors = "; ".join(str(t.get("error") or "failed") for t in existing[:3])
        raise RuntimeError(f"Tất cả tác vụ Muse video cho {ref_type} #{ref_id} thất bại: {errors}")

    shot_ids = [int(t["shot_id"]) for t in ready]
    any_partial = any(bool(t.get("partial")) for t in ready)
    return shot_ids, any_partial


def create_trend_motion_remix_task(
    paths: AppPaths,
    *,
    workspace_id: int,
    trend_id: int,
    prompt: str,
    rights_confirmed: bool,
    duration_sec: int = 10,
    ratio: str = "9:16",
    max_ref_seconds: float = 12.0,
    actor: str = "api",
) -> dict[str, Any]:
    """Queues a Muse motion-remix video task using a downloaded trend clip (`full_ai` + consent only)."""
    trend_row = query_one(
        paths.db_file,
        "SELECT id, caption, ref_video_path FROM trend_items WHERE id = ?",
        (int(trend_id),),
    )
    if trend_row is None:
        raise LookupError(f"Trend #{trend_id} not found")
    if not trend_row.get("ref_video_path"):
        raise ValueError(f"Trend #{trend_id} chưa có video tham chiếu trên đĩa; hãy tải clip trước.")

    refs = [
        {
            "type": "trend_clip",
            "id": int(trend_id),
            "rights_confirmed": bool(rights_confirmed),
            "max_seconds": max_ref_seconds,
        }
    ]
    validate_muse_refs_policy(paths, workspace_id=workspace_id, refs=refs, actor=actor)
    cfg = load_settings(paths.config_file).muse_gateway
    clean_prompt = (prompt or "").strip() or f"Tạo biến thể chuyển động mới từ ý tưởng: {str(trend_row.get('caption') or '')[:120]}"
    return create_muse_task(
        paths.db_file,
        workspace_id=workspace_id,
        kind="video",
        model=cfg.default_video_model or "muse-video",
        purpose="trend_remix",
        ref_type="trend_item",
        ref_id=int(trend_id),
        prompt=clean_prompt,
        params={
            "duration": max(4, min(60, int(duration_sec))),
            "ratio": ratio if ratio in ("9:16", "16:9", "1:1", "4:3", "3:4") else "9:16",
        },
        refs=refs,
        priority=5,
    )


def _finalize_autopilot_muse_video(paths: AppPaths, task_row: dict[str, Any]) -> None:
    if task_row["status"] != "succeeded" or not task_row.get("shot_id"):
        return
    rule_id = int(task_row.get("ref_id") or 0)
    rule = query_one(paths.db_file, "SELECT * FROM autopilot_rules WHERE id = ?", (rule_id,))
    if rule is None:
        return
    ws_id = int(task_row["workspace_id"])
    shot_id = int(task_row["shot_id"])
    dur_s = max(2.0, float(task_row.get("duration_sec") or 6.0))
    caption = str(task_row["prompt"])[:120]
    plan_payload = {
        "autopilot_rule_id": rule_id,
        "muse_task_id": int(task_row["id"]),
        "shots": [{"shot_id": shot_id, "duration_s": round(min(dur_s, 12.0), 2), "text": caption[:70]}],
        "caption_vi": caption,
        "caption_en": caption,
    }
    with get_conn(paths.db_file) as conn:
        vid = int(
            conn.execute(
                """
                INSERT INTO videos (
                    workspace_id, engine, status, plan_json, voice_lang, caption_lang,
                    target_lang, target_accounts_json, style_preset, aspect_ratio, auto_render
                )
                VALUES (?, 'ffmpeg', 'planned', ?, 'vi', 'vi', 'vi', ?, ?, ?, 0)
                """,
                (
                    ws_id,
                    json.dumps(plan_payload, ensure_ascii=False),
                    str(rule.get("target_account_ids_json") or "[]"),
                    str(rule.get("style_preset") or "tiktok_karaoke"),
                    str(rule.get("aspect_ratio") or "9:16"),
                ),
            ).lastrowid
        )
    render_video(paths, vid, auto_score=False, report_progress=False)
    v_row = query_one(paths.db_file, "SELECT qc_json FROM videos WHERE id = ?", (vid,))
    qc = loads_or((v_row or {}).get("qc_json"), {})
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE videos SET quality_score = ? WHERE id = ?", (8.7 if qc.get("passed") else 5.0, vid))
    try_autopilot_approve(paths, vid)


def _on_downstream_task_finished(paths: AppPaths, task_row: dict[str, Any]) -> None:
    if task_row["status"] in ACTIVE_MUSE_TASK_STATUSES:
        return

    if task_row.get("purpose") == "telegram":
        from videocreator.tg.muse_commands import notify_telegram_muse_result

        notify_telegram_muse_result(paths, task_row)
        return

    ref_type = str(task_row.get("ref_type") or "")
    ref_id = int(task_row.get("ref_id") or 0)
    ws_id = int(task_row["workspace_id"])
    if not ref_type or ref_id <= 0:
        return

    if ref_type == "autopilot_rule":
        _finalize_autopilot_muse_video(paths, task_row)
        return

    if ref_type in ("news_project", "novel_project", "batch_run", "workflow"):
        siblings = list_muse_tasks(
            paths.db_file, workspace_id=ws_id, ref_type=ref_type, ref_id=ref_id, limit=100
        )
        if any(s["status"] in ACTIVE_MUSE_TASK_STATUSES for s in siblings):
            return
        job_map = {
            "news_project": ("news_render", "compute"),
            "novel_project": ("novel_render", "compute"),
            "batch_run": ("batch_run", "io"),
            "workflow": ("workflow_run", "compute"),
        }
        kind, lane = job_map[ref_type]
        enqueue_job(paths.db_file, kind, ref_id=ref_id, lane=lane, workspace_id=ws_id)


register_muse_downstream_hook(_on_downstream_task_finished)

__all__ = [
    "MuseMediaPendingError",
    "create_trend_motion_remix_task",
    "ensure_project_muse_shots",
]
