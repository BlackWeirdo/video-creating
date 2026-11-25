"""Multi-scene Muse Storyboard orchestration with last-frame bridging continuity & FFmpeg assembly."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from videocreator.approvals import try_autopilot_approve
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.db_rows import hydrate_row
from videocreator.jobs import enqueue_job
from videocreator.jsonutil import loads_or
from videocreator.muse_gateway.dispatcher import register_muse_downstream_hook
from videocreator.muse_gateway.refs import validate_muse_refs_policy
from videocreator.muse_gateway.store import create_muse_task, get_muse_task
from videocreator.paths import AppPaths
from videocreator.pipeline.compute_job import run_studio_project_job
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.render import render_video
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.muse_gateway.storyboard")

STORYBOARD_ASSEMBLE_JOB_KIND = "muse_storyboard_assemble"


def _hydrate_storyboard(db_file: Path, row: dict[str, Any]) -> dict[str, Any]:
    sb = hydrate_row(
        row,
        json_fields={
            "narration": ("narration_json", {}),
            "simulation_flags": ("simulation_flags_json", []),
        },
        bool_fields=("continuity",),
    )
    segs = query_all(
        db_file,
        "SELECT * FROM muse_storyboard_segments WHERE storyboard_id = ? ORDER BY idx ASC",
        (int(row["id"]),),
    )
    seg_out: list[dict[str, Any]] = []
    for s in segs:
        hs = hydrate_row(s, json_fields={"refs": ("refs_json", [])})
        if hs.get("muse_task_id"):
            hs["task"] = get_muse_task(db_file, int(hs["muse_task_id"]))
        else:
            hs["task"] = None
        seg_out.append(hs)
    sb["segments"] = seg_out
    return sb


def get_storyboard(db_file: Path, storyboard_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM muse_storyboards WHERE id = ?", (int(storyboard_id),))
    return _hydrate_storyboard(db_file, row) if row else None


def list_storyboards(db_file: Path, *, workspace_id: int) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        "SELECT * FROM muse_storyboards WHERE workspace_id = ? ORDER BY id DESC LIMIT 100",
        (int(workspace_id),),
    )
    return [_hydrate_storyboard(db_file, r) for r in rows]


def create_storyboard(
    paths: AppPaths,
    *,
    workspace_id: int,
    title: str,
    segments: list[dict[str, Any]],
    ratio: str = "9:16",
    model: str | None = None,
    continuity: bool = True,
    narration: dict[str, Any] | None = None,
    style_preset: str = "tiktok_karaoke",
    shared_refs: list[dict[str, Any]] | None = None,
    actor: str = "api",
) -> dict[str, Any]:
    ws = require_workspace(paths.db_file, workspace_id)
    if str(ws.get("content_policy") or "strict_footage") == "strict_footage":
        raise PermissionError(
            "Workspace 'strict_footage' cấm tạo Storyboard video AI; hãy dùng 'hybrid_remix' hoặc 'full_ai'."
        )
    if not segments:
        raise ValueError("Storyboard cần ít nhất 1 phân cảnh")

    cfg = load_settings(paths.config_file).muse_gateway
    chosen_model = (model or cfg.default_video_model or "muse-video").strip()
    clean_ratio = (ratio or "9:16").strip()
    if clean_ratio not in ("9:16", "16:9", "1:1", "4:3", "3:4"):
        raise ValueError(f"Unsupported storyboard ratio '{clean_ratio}'")
    style_id = resolve_style_preset(paths.db_file, style_preset)["id"]
    common_refs = list(shared_refs or [])
    if common_refs:
        validate_muse_refs_policy(paths, workspace_id=workspace_id, refs=common_refs, actor=actor)

    clean_title = (title or "").strip() or "Muse Storyboard"
    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO muse_storyboards (
                workspace_id, title, ratio, model, continuity,
                narration_json, style_preset, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'draft')
            """,
            (
                int(workspace_id),
                clean_title,
                clean_ratio,
                chosen_model,
                1 if continuity else 0,
                json.dumps(narration or {}, ensure_ascii=False),
                style_id,
            ),
        )
        sb_id = int(cur.lastrowid)
        for idx, seg in enumerate(segments):
            seg_prompt = str(seg.get("prompt") or "").strip()
            if not seg_prompt:
                raise ValueError(f"Phân cảnh #{idx + 1} thiếu prompt")
            seg_dur = max(2, min(60, int(seg.get("duration_sec") or seg.get("duration") or 8)))
            seg_cap = str(seg.get("caption") or "").strip()
            seg_refs = [*common_refs, *list(seg.get("refs") or [])]
            if seg_refs:
                validate_muse_refs_policy(paths, workspace_id=workspace_id, refs=seg_refs, actor=actor)
            conn.execute(
                """
                INSERT INTO muse_storyboard_segments (
                    storyboard_id, idx, prompt, duration_sec, caption, refs_json, status
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (sb_id, idx, seg_prompt, seg_dur, seg_cap, json.dumps(seg_refs, ensure_ascii=False)),
            )
        record_audit(
            conn,
            actor=actor,
            action="muse.create_storyboard",
            object_type="muse_storyboard",
            object_id=sb_id,
            detail=f"segments={len(segments)} continuity={continuity}",
        )
    created = get_storyboard(paths.db_file, sb_id)
    assert created is not None
    return created


def update_storyboard(
    paths: AppPaths,
    storyboard_id: int,
    *,
    title: str | None = None,
    style_preset: str | None = None,
    narration: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if get_storyboard(paths.db_file, storyboard_id) is None:
        return None
    sets = ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: list[Any] = []
    if title is not None and title.strip():
        sets.append("title = ?")
        params.append(title.strip())
    if style_preset is not None and style_preset.strip():
        sets.append("style_preset = ?")
        params.append(resolve_style_preset(paths.db_file, style_preset)["id"])
    if narration is not None:
        sets.append("narration_json = ?")
        params.append(json.dumps(narration, ensure_ascii=False))
    params.append(int(storyboard_id))
    with get_conn(paths.db_file) as conn:
        conn.execute(f"UPDATE muse_storyboards SET {', '.join(sets)} WHERE id = ?", params)
    return get_storyboard(paths.db_file, storyboard_id)


def delete_storyboard(db_file: Path, storyboard_id: int) -> bool:
    if get_storyboard(db_file, storyboard_id) is None:
        return False
    with get_conn(db_file) as conn:
        conn.execute("DELETE FROM muse_storyboards WHERE id = ?", (int(storyboard_id),))
    return True


def _extract_last_frame_work_rel(paths: AppPaths, storyboard_id: int, seg_idx: int, media_rel: str) -> str:
    src_mp4 = paths.media_dir / media_rel
    rel_png = f"muse_refs/sb_{storyboard_id}_seg_{seg_idx}_last.png"
    dest_png = paths.work_dir / rel_png
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-sseof",
            "-0.15",
            "-i",
            str(src_mp4.resolve()),
            "-frames:v",
            "1",
            "-c:v",
            "png",
            str(dest_png.resolve()),
        ]
    )
    return rel_png


def _enqueue_segment_task(
    paths: AppPaths,
    sb: dict[str, Any],
    seg: dict[str, Any],
    *,
    bridge_work_rel: str | None = None,
    thread_url: str | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    refs = list(seg.get("refs") or [])
    if bridge_work_rel:
        refs = [{"type": "work_rel", "path": bridge_work_rel}, *refs][:16]
    new_chat = not bool(thread_url and account_id)
    task = create_muse_task(
        paths.db_file,
        workspace_id=int(sb["workspace_id"]),
        kind="video",
        model=str(sb["model"]),
        purpose="storyboard",
        ref_type="muse_storyboard_segment",
        ref_id=int(seg["id"]),
        prompt=str(seg["prompt"]),
        params={
            "duration": int(seg["duration_sec"]),
            "ratio": str(sb["ratio"]),
            "new_chat": new_chat,
        },
        refs=refs,
        thread_url=thread_url,
        account_id=account_id,
        priority=5,
    )
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE muse_storyboard_segments SET muse_task_id = ?, status = 'running' WHERE id = ?",
            (int(task["id"]), int(seg["id"])),
        )
    return task


def start_storyboard_generation(paths: AppPaths, storyboard_id: int) -> dict[str, Any]:
    sb = get_storyboard(paths.db_file, storyboard_id)
    if sb is None:
        raise ValueError(f"Storyboard #{storyboard_id} not found")
    segments = [s for s in sb["segments"] if s["status"] != "succeeded"]
    if not segments:
        return sb

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE muse_storyboards SET status = 'generating', error = NULL, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            (int(storyboard_id),),
        )

    if sb["continuity"]:
        first_seg = segments[0]
        bridge_rel: str | None = None
        thread_url: str | None = None
        account_id: str | None = None
        if int(first_seg["idx"]) > 0:
            prev_seg = next(
                (s for s in sb["segments"] if int(s["idx"]) == int(first_seg["idx"]) - 1),
                None,
            )
            prev_task = (prev_seg or {}).get("task")
            if prev_task and prev_task.get("local_path"):
                bridge_rel = _extract_last_frame_work_rel(
                    paths, storyboard_id, int(prev_seg["idx"]), str(prev_task["local_path"])
                )
                thread_url = prev_task.get("thread_url")
                account_id = prev_task.get("account_id")
        _enqueue_segment_task(
            paths, sb, first_seg, bridge_work_rel=bridge_rel, thread_url=thread_url, account_id=account_id
        )
    else:
        for seg in segments:
            _enqueue_segment_task(paths, sb, seg)

    refreshed = get_storyboard(paths.db_file, storyboard_id)
    assert refreshed is not None
    return refreshed


def regenerate_storyboard_segment(
    paths: AppPaths,
    storyboard_id: int,
    seg_idx: int,
    *,
    prompt: str | None = None,
) -> dict[str, Any]:
    sb = get_storyboard(paths.db_file, storyboard_id)
    if sb is None:
        raise ValueError(f"Storyboard #{storyboard_id} not found")
    target = next((s for s in sb["segments"] if int(s["idx"]) == int(seg_idx)), None)
    if target is None:
        raise ValueError(f"Segment #{seg_idx} not found in Storyboard #{storyboard_id}")

    with get_conn(paths.db_file) as conn:
        if prompt is not None and prompt.strip():
            conn.execute(
                "UPDATE muse_storyboard_segments SET prompt = ?, status = 'pending' WHERE id = ?",
                (prompt.strip(), int(target["id"])),
            )
            target["prompt"] = prompt.strip()
        else:
            conn.execute(
                "UPDATE muse_storyboard_segments SET status = 'pending' WHERE id = ?",
                (int(target["id"]),),
            )
        conn.execute(
            "UPDATE muse_storyboards SET status = 'generating', error = NULL WHERE id = ?",
            (int(storyboard_id),),
        )

    bridge_rel: str | None = None
    thread_url: str | None = None
    account_id: str | None = None
    if sb["continuity"] and seg_idx > 0:
        prev_seg = next((s for s in sb["segments"] if int(s["idx"]) == seg_idx - 1), None)
        prev_task = (prev_seg or {}).get("task")
        if prev_task and prev_task.get("local_path"):
            bridge_rel = _extract_last_frame_work_rel(
                paths, storyboard_id, seg_idx - 1, str(prev_task["local_path"])
            )
            thread_url = prev_task.get("thread_url")
            account_id = prev_task.get("account_id")

    _enqueue_segment_task(
        paths, sb, target, bridge_work_rel=bridge_rel, thread_url=thread_url, account_id=account_id
    )
    updated = get_storyboard(paths.db_file, storyboard_id)
    assert updated is not None
    return updated


def advance_storyboard_on_task(paths: AppPaths, task_row: dict[str, Any]) -> None:
    """Downstream dispatcher hook advancing sequential continuity segments & triggering assembly."""
    if task_row.get("ref_type") != "muse_storyboard_segment" or not task_row.get("ref_id"):
        return
    seg_id = int(task_row["ref_id"])
    seg_row = query_one(
        paths.db_file, "SELECT * FROM muse_storyboard_segments WHERE id = ?", (seg_id,)
    )
    if seg_row is None:
        return
    sb_id = int(seg_row["storyboard_id"])
    t_status = str(task_row["status"])
    if t_status not in ("succeeded", "failed", "cancelled"):
        return

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE muse_storyboard_segments SET status = ? WHERE id = ?",
            (t_status, seg_id),
        )

    sb = get_storyboard(paths.db_file, sb_id)
    if sb is None or sb["status"] == "cancelled":
        return

    if t_status == "succeeded" and sb["continuity"]:
        cur_idx = int(seg_row["idx"])
        next_seg = next(
            (s for s in sb["segments"] if int(s["idx"]) == cur_idx + 1 and s["status"] == "pending"),
            None,
        )
        if next_seg is not None:
            bridge_rel: str | None = None
            if task_row.get("local_path"):
                try:
                    bridge_rel = _extract_last_frame_work_rel(
                        paths, sb_id, cur_idx, str(task_row["local_path"])
                    )
                except Exception as exc:
                    logger.warning("Could not extract bridge frame for storyboard #%d: %s", sb_id, exc)
            # Thread continuation uses scene 0's thread_url + account_id
            seg0_task = (sb["segments"][0] or {}).get("task") or task_row
            _enqueue_segment_task(
                paths,
                sb,
                next_seg,
                bridge_work_rel=bridge_rel,
                thread_url=seg0_task.get("thread_url") or task_row.get("thread_url"),
                account_id=seg0_task.get("account_id") or task_row.get("account_id"),
            )
            return

    refreshed = get_storyboard(paths.db_file, sb_id)
    assert refreshed is not None
    statuses = [str(s["status"]) for s in refreshed["segments"]]
    if any(st in ("pending", "running") for st in statuses):
        return

    if all(st == "succeeded" for st in statuses):
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE muse_storyboards SET status = 'assembling', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
                (sb_id,),
            )
        enqueue_job(
            paths.db_file,
            STORYBOARD_ASSEMBLE_JOB_KIND,
            ref_id=sb_id,
            lane="compute",
            workspace_id=int(refreshed["workspace_id"]),
        )
    elif any(st == "succeeded" for st in statuses):
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE muse_storyboards SET status = 'partial', error = 'Một số cảnh thất bại; có thể tạo lại cảnh lỗi hoặc ghép phần đã xong.' WHERE id = ?",
                (sb_id,),
            )
    else:
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE muse_storyboards SET status = 'failed', error = ? WHERE id = ?",
                (str(task_row.get("error") or "Tất cả cảnh storyboard thất bại")[:400], sb_id),
            )


def assemble_storyboard(paths: AppPaths, storyboard_id: int) -> dict[str, Any]:
    """Assembles ready Muse storyboard shots into a full voiced, subtitled, QC-verified `videos` row."""
    sb = get_storyboard(paths.db_file, storyboard_id)
    if sb is None:
        raise ValueError(f"Storyboard #{storyboard_id} not found")

    ready_segs = [
        s
        for s in sb["segments"]
        if s["status"] == "succeeded" and (s.get("task") or {}).get("shot_id")
    ]
    if not ready_segs:
        raise ValueError(f"Storyboard #{storyboard_id} chưa có phân cảnh nào hoàn tất để ghép")

    ws_id = int(sb["workspace_id"])
    narration = dict(sb.get("narration") or {})
    voice_id = str(narration.get("voice_id") or "").strip()
    voice_lang = str(narration.get("lang") or ("vi" if voice_id else "none")).strip()
    if not voice_id and not any(str(s.get("caption") or "").strip() for s in ready_segs):
        voice_lang = "none"
    elif voice_lang not in ("vi", "en", "none"):
        voice_lang = "vi"
    caption_lang = "en" if voice_lang == "en" else "vi"

    planned_shots: list[dict[str, Any]] = []
    any_partial = False
    captions_joined: list[str] = []
    for seg in ready_segs:
        t = seg["task"]
        if t.get("partial"):
            any_partial = True
        dur_s = max(1.5, float(t.get("duration_sec") or seg.get("duration_sec") or 6.0))
        cap = str(seg.get("caption") or "").strip()
        if cap:
            captions_joined.append(cap)
        planned_shots.append(
            {
                "shot_id": int(t["shot_id"]),
                "duration_s": round(dur_s, 2),
                "text": cap,
            }
        )

    full_caption = ". ".join(captions_joined).strip() or str(sb["title"])
    plan_payload = {
        "muse_storyboard_id": storyboard_id,
        "title": str(sb["title"]),
        "voice_id": voice_id,
        "shots": planned_shots,
        "caption_vi": full_caption,
        "caption_en": full_caption,
    }
    ratio = str(sb["ratio"]) if str(sb["ratio"]) in ("9:16", "16:9", "1:1") else "9:16"

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO videos (
                workspace_id, engine, status, plan_json,
                voice_lang, caption_lang, target_lang, style_preset, aspect_ratio, auto_render
            )
            VALUES (?, 'ffmpeg', 'planned', ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                ws_id,
                json.dumps(plan_payload, ensure_ascii=False),
                voice_lang,
                caption_lang,
                caption_lang,
                str(sb.get("style_preset") or "tiktok_karaoke"),
                ratio,
            ),
        )
        video_id = int(cur.lastrowid)

    render_video(paths, video_id, auto_score=False, report_progress=False)
    v_row = query_one(paths.db_file, "SELECT qc_json, quality_score FROM videos WHERE id = ?", (video_id,))
    if v_row and v_row.get("quality_score") is None:
        qc = loads_or(v_row.get("qc_json"), {})
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE videos SET quality_score = ? WHERE id = ?",
                (8.8 if qc.get("passed") else 5.0, video_id),
            )
    try_autopilot_approve(paths, video_id)

    sim_flags: list[str] = []
    if any_partial:
        sim_flags.append("muse_video_partial")

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            UPDATE muse_storyboards
            SET output_video_id = ?,
                simulation_flags_json = ?,
                status = 'completed',
                error = NULL,
                updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = ?
            """,
            (video_id, json.dumps(sim_flags), int(storyboard_id)),
        )
        record_audit(
            conn,
            actor="muse_storyboard",
            action="muse.assemble_storyboard",
            object_type="muse_storyboard",
            object_id=int(storyboard_id),
            detail=f"video_id={video_id} shots={len(planned_shots)}",
        )
    done = get_storyboard(paths.db_file, storyboard_id)
    assert done is not None
    return done


def run_storyboard_assemble_job(paths: AppPaths, storyboard_id: int) -> str:
    return run_studio_project_job(assemble_storyboard, paths, storyboard_id)


register_muse_downstream_hook(advance_storyboard_on_task)

__all__ = [
    "STORYBOARD_ASSEMBLE_JOB_KIND",
    "advance_storyboard_on_task",
    "assemble_storyboard",
    "create_storyboard",
    "delete_storyboard",
    "get_storyboard",
    "list_storyboards",
    "regenerate_storyboard_segment",
    "run_storyboard_assemble_job",
    "start_storyboard_generation",
    "update_storyboard",
]
