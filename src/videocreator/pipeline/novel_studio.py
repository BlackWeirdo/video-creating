"""Novel & Multi-Chapter Story-to-Video Studio with Checkpoint Resume (V2-STD-01)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from videocreator.approvals import try_autopilot_approve
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.db_rows import file_media_url, hydrate_row
from videocreator.job_store import report_active_job_progress
from videocreator.jsonutil import loads_or
from videocreator.muse_gateway.studio_bridge import ensure_project_muse_shots
from videocreator.paths import AppPaths
from videocreator.pipeline.compute_job import run_studio_project_job
from videocreator.pipeline.export import resolve_canvas_dimensions
from videocreator.pipeline.novel_chapters import (
    build_chapter_lines,
    resolve_novel_chapter_shots,
    split_novel_chapters,
)
from videocreator.pipeline.render import render_video
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.pipeline.novel_studio")


def _hydrate_novel(db_file: Path, row: dict[str, Any]) -> dict[str, Any]:
    chapters = query_all(
        db_file,
        "SELECT * FROM novel_chapters WHERE project_id = ? ORDER BY chapter_index ASC",
        (int(row["id"]),),
    )
    out = hydrate_row(
        row,
        json_fields={"simulation_flags": ("simulation_flags_json", [])},
        bool_fields=("waiting_media",),
    )
    if out.get("waiting_media"):
        out["status"] = "waiting_media"
    out["chapters"] = [
        {**ch, "video_url": file_media_url(ch.get("output_path"), empty="")}
        for ch in chapters
    ]
    out["total_chapters"] = len(chapters)
    out["ready_chapters"] = sum(1 for ch in chapters if ch.get("status") == "ready")
    return out


def get_novel_project(db_file: Path, project_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM novel_projects WHERE id = ?", (int(project_id),))
    return _hydrate_novel(db_file, row) if row else None


def list_novel_projects(db_file: Path, *, workspace_id: int) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        "SELECT * FROM novel_projects WHERE workspace_id = ? ORDER BY id DESC LIMIT 100",
        (int(workspace_id),),
    )
    return [_hydrate_novel(db_file, r) for r in rows]


def create_novel_project(
    paths: AppPaths,
    *,
    workspace_id: int,
    title: str,
    source_text: str,
    character_id: int | None = None,
    visual_source: str = "characters",
    style_preset: str = "tiktok_karaoke",
    aspect_ratio: str = "9:16",
    target_lang: str = "vi",
    voice_id: str = "vi-VN-HoaiMyNeural",
    target_words_per_chapter: int = 140,
    actor: str = "api",
) -> dict[str, Any]:
    ws = require_workspace(paths.db_file, workspace_id)
    vis_src = (visual_source or "characters").strip().lower()
    if vis_src not in ("characters", "muse_video"):
        raise ValueError(f"Unsupported novel visual_source '{visual_source}'")
    chapters = split_novel_chapters(source_text, target_words=target_words_per_chapter)
    if not chapters:
        raise ValueError("Nội dung truyện/tiểu thuyết không được để trống")

    clean_title = (title or "").strip() or chapters[0]["title"][:80] or "Tiểu thuyết mới"
    style = resolve_style_preset(paths.db_file, style_preset)["id"]
    ratio = (aspect_ratio or str(ws.get("default_aspect_ratio") or "9:16")).strip() or "9:16"
    resolve_canvas_dimensions(ratio)

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO novel_projects (
                workspace_id, title, source_text, character_id, visual_source, style_preset,
                aspect_ratio, target_lang, voice_id, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft')
            """,
            (
                int(workspace_id),
                clean_title,
                source_text.strip(),
                int(character_id) if character_id else None,
                vis_src,
                style,
                ratio,
                (target_lang or "vi").strip() or "vi",
                (voice_id or "vi-VN-HoaiMyNeural").strip(),
            ),
        )
        proj_id = int(cur.lastrowid)
        for ch in chapters:
            conn.execute(
                """
                INSERT INTO novel_chapters (
                    project_id, workspace_id, chapter_index, title, body_text, word_count, status
                )
                VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (
                    proj_id,
                    int(workspace_id),
                    int(ch["chapter_index"]),
                    str(ch["title"]),
                    str(ch["body_text"]),
                    int(ch["word_count"]),
                ),
            )
        record_audit(
            conn,
            actor=actor,
            action="create_novel_project",
            object_type="novel_project",
            object_id=proj_id,
            detail=f"{clean_title[:60]} ({len(chapters)} chapters)",
        )
    proj = get_novel_project(paths.db_file, proj_id)
    assert proj is not None
    return proj


def render_novel_project(
    paths: AppPaths,
    project_id: int,
    *,
    chapter_ids: list[int] | None = None,
    force: bool = False,
    visual_source: str | None = None,
) -> dict[str, Any]:
    """Renders novel chapters into videos, skipping chapters already completed (checkpoint resume)."""
    if visual_source is not None and visual_source.strip():
        vs = visual_source.strip().lower()
        if vs not in ("characters", "muse_video"):
            raise ValueError(f"Unsupported novel visual_source '{visual_source}'")
        with get_conn(paths.db_file) as conn:
            conn.execute("UPDATE novel_projects SET visual_source = ? WHERE id = ?", (vs, int(project_id)))

    proj = get_novel_project(paths.db_file, project_id)
    if proj is None:
        raise ValueError(f"Novel project #{project_id} not found")

    ws_id = int(proj["workspace_id"])
    ws = require_workspace(paths.db_file, ws_id)
    if str(ws.get("content_policy") or "strict_footage") == "strict_footage":
        raise PermissionError(
            "Workspace 'strict_footage' không cho phép dựng Tiểu thuyết AI; hãy chọn 'hybrid_remix' hoặc 'full_ai'."
        )

    target_set = {int(cid) for cid in chapter_ids} if chapter_ids else None
    t_lang = str(proj.get("target_lang") or "vi")
    legacy_lang = "vi" if t_lang.strip().lower().startswith("vi") else "en"
    style = resolve_style_preset(paths.db_file, str(proj.get("style_preset") or "tiktok_karaoke"))["id"]
    ratio = str(proj.get("aspect_ratio") or "9:16")
    eff_voice_id = str(proj.get("voice_id") or "").strip()
    if proj.get("character_id"):
        ch_row = query_one(paths.db_file, "SELECT voice_id FROM characters WHERE id = ?", (int(proj["character_id"]),))
        if ch_row and ch_row.get("voice_id") and eff_voice_id in ("", "vi-VN-HoaiMyNeural"):
            eff_voice_id = str(ch_row["voice_id"])

    chapters_list = list(proj.get("chapters") or [])
    muse_chapter_map: dict[int, int] = {}
    muse_partial = False
    if str(proj.get("visual_source") or "characters") == "muse_video":
        pending_ch = [
            c
            for c in chapters_list
            if (target_set is None or int(c["id"]) in target_set)
            and (
                force
                or str(c.get("status") or "") != "ready"
                or not str(c.get("output_path") or "").strip()
                or not (paths.media_dir / str(c.get("output_path") or "")).is_file()
            )
        ]
        if pending_ch:
            muse_shots, muse_partial = ensure_project_muse_shots(
                paths,
                workspace_id=ws_id,
                ref_type="novel_project",
                ref_id=project_id,
                prompts_and_durations=[
                    (f"{proj['title']} - {c['title']}: {str(c['body_text'])[:140]}", 6.0)
                    for c in pending_ch
                ],
                aspect_ratio=ratio,
                character_id=int(proj["character_id"]) if proj.get("character_id") else None,
            )
            if muse_shots is None:
                with get_conn(paths.db_file) as conn:
                    conn.execute(
                        "UPDATE novel_projects SET status = 'rendering', waiting_media = 1, error = NULL WHERE id = ?",
                        (int(project_id),),
                    )
                waiting = get_novel_project(paths.db_file, project_id)
                assert waiting is not None
                return waiting
            for idx, c in enumerate(pending_ch):
                muse_chapter_map[int(c["id"])] = muse_shots[idx % len(muse_shots)]

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE novel_projects SET status = 'rendering', waiting_media = 0, error = NULL WHERE id = ?",
            (int(project_id),),
        )

    rendered_now = 0
    skipped_checkpoint = 0
    failed_count = 0
    any_placeholder_img = False

    total_ch = max(1, len(chapters_list))
    for ch_pos, ch in enumerate(chapters_list, start=1):
        ch_id = int(ch["id"])
        if target_set is not None and ch_id not in target_set:
            continue
        existing_rel = str(ch.get("output_path") or "").strip()
        if (
            not force
            and str(ch.get("status") or "") == "ready"
            and existing_rel
            and (paths.media_dir / existing_rel).is_file()
        ):
            skipped_checkpoint += 1
            report_active_job_progress(
                0.08 + 0.85 * (ch_pos / total_ch),
                f"Bỏ qua chương {ch_pos}/{total_ch} (đã có checkpoint): {str(ch['title'])[:48]}",
            )
            continue

        report_active_job_progress(
            0.08 + 0.85 * ((ch_pos - 1) / total_ch),
            f"Đang dựng chương {ch_pos}/{total_ch}: {str(ch['title'])[:48]}",
        )
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE novel_chapters SET status = 'rendering', error = NULL WHERE id = ?",
                (ch_id,),
            )

        try:
            lines = build_chapter_lines(str(ch["title"]), str(ch["body_text"]), t_lang)
            planned_shots, ch_placeholder = resolve_novel_chapter_shots(
                paths, proj, ch, lines, forced_shot_id=muse_chapter_map.get(ch_id)
            )
            if ch_placeholder:
                any_placeholder_img = True
            caption = f"{proj['title']} - {ch['title']}".strip()
            plan_payload = {
                "novel_project_id": project_id,
                "novel_chapter_id": ch_id,
                "title": caption,
                "voice_id": eff_voice_id,
                "shots": planned_shots,
                "caption_vi": caption,
                "caption_en": caption,
            }
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
                        legacy_lang,
                        legacy_lang,
                        t_lang,
                        style,
                        ratio,
                    ),
                )
                video_id = int(cur.lastrowid)

            render_video(paths, video_id, auto_score=False, report_progress=False)
            v_row = query_one(
                paths.db_file,
                "SELECT output_path, qc_json, quality_score FROM videos WHERE id = ?",
                (video_id,),
            )
            assert v_row is not None
            if v_row.get("quality_score") is None:
                qc = loads_or(v_row.get("qc_json"), {})
                with get_conn(paths.db_file) as conn:
                    conn.execute(
                        "UPDATE videos SET quality_score = ? WHERE id = ?",
                        (8.7 if qc.get("passed") else 5.0, video_id),
                    )
            try_autopilot_approve(paths, video_id)

            rel_out = str(v_row.get("output_path") or "")
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    """
                    UPDATE novel_chapters
                    SET video_id = ?, output_path = ?, status = 'ready', error = NULL,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                    WHERE id = ?
                    """,
                    (video_id, rel_out, ch_id),
                )
            rendered_now += 1
        except Exception as exc:
            failed_count += 1
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    """
                    UPDATE novel_chapters
                    SET status = 'failed', error = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                    WHERE id = ?
                    """,
                    (str(exc)[:400], ch_id),
                )

    refreshed = get_novel_project(paths.db_file, project_id)
    assert refreshed is not None
    chapters_now = refreshed["chapters"]
    if chapters_now and all(c["status"] == "ready" for c in chapters_now):
        final_status = "completed"
    elif any(c["status"] == "ready" for c in chapters_now):
        final_status = "partial"
    else:
        final_status = "failed"

    if skipped_checkpoint > 0 and "ai_image_canvas_placeholder" in (proj.get("simulation_flags") or []):
        any_placeholder_img = True

    sim_flags: list[str] = []
    if muse_partial:
        sim_flags.append("muse_video_partial")
    if any_placeholder_img:
        sim_flags.append("ai_image_canvas_placeholder")
    from videocreator.config import load_settings

    cfg_v = load_settings(paths.config_file).voice.vi_provider
    if cfg_v in ("test_tone", "local"):
        sim_flags.append("tts_tone_placeholder")
    else:
        ch_vid_ids = [int(c["video_id"]) for c in chapters_now if c.get("video_id")]
        if ch_vid_ids:
            q_rows = query_all(
                paths.db_file,
                f"SELECT quality_notes FROM videos WHERE id IN ({','.join('?' * len(ch_vid_ids))})",
                ch_vid_ids,
            )
            if any("test_tone" in str(r.get("quality_notes") or "") or "Không lồng tiếng được" in str(r.get("quality_notes") or "") for r in q_rows):
                sim_flags.append("tts_tone_placeholder")

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            UPDATE novel_projects
            SET status = ?, waiting_media = 0, simulation_flags_json = ?,
                updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = ?
            """,
            (final_status, json.dumps(sim_flags, ensure_ascii=False), int(project_id)),
        )
        record_audit(
            conn,
            actor="novel_studio",
            action="render_novel_project",
            object_type="novel_project",
            object_id=int(project_id),
            detail=f"rendered={rendered_now}, skipped={skipped_checkpoint}, failed={failed_count}",
        )
    done = get_novel_project(paths.db_file, project_id)
    assert done is not None
    done["resume_stats"] = {
        "rendered_now": rendered_now,
        "skipped_checkpoint": skipped_checkpoint,
        "failed": failed_count,
    }
    return done


def run_novel_render_job(paths: AppPaths, project_id: int) -> str:
    return run_studio_project_job(render_novel_project, paths, project_id)


__all__ = [
    "create_novel_project",
    "get_novel_project",
    "list_novel_projects",
    "render_novel_project",
    "run_novel_render_job",
    "split_novel_chapters",
]
