"""Novel & Multi-Chapter Story-to-Video Studio with Checkpoint Resume (V2-STD-01)."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from videocreator.approvals import try_autopilot_approve
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.batch_studio import _ensure_full_ai_canvas_shot
from videocreator.pipeline.characters import generate_ai_image
from videocreator.pipeline.export import resolve_canvas_dimensions
from videocreator.pipeline.render import render_video
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.tts.syllables import count_syllables, max_syllables_for_duration
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.pipeline.novel_studio")

_CHAPTER_HEADING_RE = re.compile(
    r"^\s*(?:chương|chuong|chapter|hồi|hoi|part|#)\s*([^\n]+)",
    re.IGNORECASE | re.MULTILINE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\r?\n+")


def split_novel_chapters(source_text: str, *, target_words: int = 140) -> list[dict[str, Any]]:
    """Splits novel/story text into ordered chapters by headings or paragraph word boundaries."""
    raw = (source_text or "").strip()
    if not raw:
        return []

    matches = list(_CHAPTER_HEADING_RE.finditer(raw))
    chapters: list[dict[str, Any]] = []
    if matches:
        # Preserve optional prologue before first explicit chapter heading
        preamble = raw[: matches[0].start()].strip()
        idx_cursor = 1
        if preamble and len(preamble.split()) >= 4:
            chapters.append(
                {
                    "chapter_index": idx_cursor,
                    "title": "Mở đầu",
                    "body_text": preamble,
                    "word_count": len(preamble.split()),
                }
            )
            idx_cursor += 1
        for i, m in enumerate(matches):
            body_start = m.end()
            body_end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
            heading = m.group(0).strip().lstrip("#").strip()
            body = raw[body_start:body_end].strip() or heading
            chapters.append(
                {
                    "chapter_index": idx_cursor,
                    "title": heading[:120],
                    "body_text": body,
                    "word_count": len(body.split()),
                }
            )
            idx_cursor += 1
        return chapters

    limit = max(20, int(target_words))
    paragraphs = [p.strip() for p in re.split(r"\r?\n\s*\r?\n|\r?\n", raw) if p.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [s.strip() for s in _SENTENCE_SPLIT_RE.split(raw) if s.strip()]

    buf: list[str] = []
    buf_words = 0
    idx = 1
    for p in paragraphs:
        wc = len(p.split())
        if buf and (buf_words + wc) > limit:
            body = "\n".join(buf).strip()
            chapters.append(
                {
                    "chapter_index": idx,
                    "title": f"Chương {idx}",
                    "body_text": body,
                    "word_count": len(body.split()),
                }
            )
            idx += 1
            buf = [p]
            buf_words = wc
        else:
            buf.append(p)
            buf_words += wc

    if buf:
        body = "\n".join(buf).strip()
        chapters.append(
            {
                "chapter_index": idx,
                "title": f"Chương {idx}",
                "body_text": body,
                "word_count": len(body.split()),
            }
        )
    return chapters


def _hydrate_novel(db_file: Path, row: dict[str, Any]) -> dict[str, Any]:
    chapters = query_all(
        db_file,
        "SELECT * FROM novel_chapters WHERE project_id = ? ORDER BY chapter_index ASC",
        (int(row["id"]),),
    )
    out = dict(row)
    out["chapters"] = [
        {
            **ch,
            "video_url": f"/files/{str(ch['output_path']).lstrip('/')}"
            if ch.get("output_path")
            else "",
        }
        for ch in chapters
    ]
    out["total_chapters"] = len(chapters)
    out["ready_chapters"] = sum(1 for ch in chapters if ch.get("status") == "ready")
    out["simulation_flags"] = loads_or(row.get("simulation_flags_json"), [])
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
    style_preset: str = "tiktok_karaoke",
    aspect_ratio: str = "9:16",
    target_lang: str = "vi",
    voice_id: str = "vi-VN-HoaiMyNeural",
    target_words_per_chapter: int = 140,
    actor: str = "api",
) -> dict[str, Any]:
    ws = require_workspace(paths.db_file, workspace_id)
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
                workspace_id, title, source_text, character_id, style_preset,
                aspect_ratio, target_lang, voice_id, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft')
            """,
            (
                int(workspace_id),
                clean_title,
                source_text.strip(),
                int(character_id) if character_id else None,
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


def _fit_line_to_budget(text: str, lang: str, duration_s: float) -> str:
    budget = max(5, max_syllables_for_duration(duration_s, lang))
    words = " ".join((text or "").split()).split()
    kept: list[str] = []
    for w in words:
        cand = " ".join([*kept, w])
        if count_syllables(cand, lang) > budget and kept:
            break
        kept.append(w)
    return " ".join(kept) or text[:48]


def _build_chapter_lines(chapter_title: str, body_text: str, lang: str) -> list[dict[str, Any]]:
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(body_text) if len(s.strip()) >= 4]
    line1 = _fit_line_to_budget(chapter_title, lang, 1.8)
    line2 = _fit_line_to_budget(sentences[0] if sentences else body_text, lang, 2.0)
    line3 = _fit_line_to_budget(
        sentences[1] if len(sentences) > 1 else (sentences[-1] if sentences else chapter_title),
        lang,
        1.8,
    )
    return [
        {"duration_s": 1.8, "text": line1},
        {"duration_s": 2.0, "text": line2},
        {"duration_s": 1.8, "text": line3},
    ]


def _resolve_novel_chapter_shots(
    paths: AppPaths,
    proj: dict[str, Any],
    chapter: dict[str, Any],
    lines: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    ws_id = int(proj["workspace_id"])
    aspect_ratio = str(proj.get("aspect_ratio") or "9:16")
    shot_ids: list[int] = []

    char_id = proj.get("character_id")
    if char_id:
        img = generate_ai_image(
            paths,
            workspace_id=ws_id,
            character_id=int(char_id),
            prompt=f"{proj['title']} - {chapter['title']}"[:120],
            aspect_ratio=aspect_ratio,
            is_product_shot=False,
            animate_to_shot=True,
            actor="novel_studio",
        )
        if img.get("motion_shot_id"):
            shot_ids.append(int(img["motion_shot_id"]))

    ws_shots = query_all(
        paths.db_file,
        """
        SELECT s.id
        FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        LEFT JOIN assets a ON s.asset_id = a.id
        WHERE COALESCE(f.workspace_id, a.workspace_id, 1) = ?
        ORDER BY s.quality DESC, s.id ASC LIMIT 4
        """,
        (ws_id,),
    )
    shot_ids.extend(int(r["id"]) for r in ws_shots if int(r["id"]) not in shot_ids)

    if not shot_ids:
        shot_ids.append(_ensure_full_ai_canvas_shot(paths, ws_id, aspect_ratio))

    planned: list[dict[str, Any]] = []
    for idx, seg in enumerate(lines):
        planned.append(
            {
                "shot_id": shot_ids[idx % len(shot_ids)],
                "duration_s": max(1.6, float(seg["duration_s"])),
                "text": str(seg["text"]),
            }
        )
    return planned


def render_novel_project(
    paths: AppPaths,
    project_id: int,
    *,
    chapter_ids: list[int] | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Renders novel chapters into videos, skipping chapters already completed (checkpoint resume)."""
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

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE novel_projects SET status = 'rendering', error = NULL WHERE id = ?",
            (int(project_id),),
        )

    rendered_now = 0
    skipped_checkpoint = 0
    failed_count = 0

    for ch in proj.get("chapters") or []:
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
            continue

        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE novel_chapters SET status = 'rendering', error = NULL WHERE id = ?",
                (ch_id,),
            )

        try:
            lines = _build_chapter_lines(str(ch["title"]), str(ch["body_text"]), t_lang)
            planned_shots = _resolve_novel_chapter_shots(paths, proj, ch, lines)
            caption = f"{proj['title']} - {ch['title']}".strip()
            plan_payload = {
                "novel_project_id": project_id,
                "novel_chapter_id": ch_id,
                "title": caption,
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

            render_video(paths, video_id, auto_score=False)
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

    sim_flags: list[str] = []
    if proj.get("character_id"):
        sim_flags.append("ai_image_canvas_placeholder")
    from videocreator.config import load_settings
    import shutil as _shutil

    cfg_v = load_settings(paths.config_file).voice.vi_provider
    if cfg_v in ("test_tone", "local") or (cfg_v == "edge" and not _shutil.which("edge-tts")):
        sim_flags.append("tts_tone_placeholder")

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            UPDATE novel_projects
            SET status = ?, simulation_flags_json = ?,
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
    res = render_novel_project(paths, project_id)
    return str(res.get("status") or "completed")
