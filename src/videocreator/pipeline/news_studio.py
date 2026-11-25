"""News & Article-to-Video Studio: project CRUD, script summarization & video + zip pack (V2-NWS-01..04)."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from videocreator.approvals import try_autopilot_approve
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.db_rows import hydrate_row
from videocreator.job_store import report_active_job_progress
from videocreator.jsonutil import loads_or
from videocreator.muse_gateway.studio_bridge import ensure_project_muse_shots
from videocreator.paths import AppPaths
from videocreator.pipeline.assembly import ensure_full_ai_canvas_shot
from videocreator.pipeline.characters import generate_ai_image
from videocreator.pipeline.compute_job import run_studio_project_job
from videocreator.pipeline.news_extractor import (
    VALID_NEWS_SOURCE_KINDS,
    extract_article_facts,
    fit_news_line,
)
from videocreator.pipeline.render import render_video
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.posting.publish_pack import build_publish_pack_zip
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.pipeline.news_studio")


def create_news_project(
    paths: AppPaths,
    *,
    workspace_id: int,
    title: str = "",
    source_kind: str = "raw_text",
    source_url: str = "",
    raw_text: str = "",
    character_id: int | None = None,
    visual_source: str = "characters",
    style_preset: str = "tiktok_karaoke",
    aspect_ratio: str = "9:16",
    target_lang: str = "vi",
    voice_id: str = "vi-VN-HoaiMyNeural",
    actor: str = "api",
) -> dict[str, Any]:
    ws = require_workspace(paths.db_file, workspace_id)
    kind = (source_kind or "raw_text").strip().lower()
    if kind not in VALID_NEWS_SOURCE_KINDS:
        raise ValueError(f"Unsupported news source_kind '{source_kind}'")
    vis_src = (visual_source or "characters").strip().lower()
    if vis_src not in ("characters", "muse_video"):
        raise ValueError(f"Unsupported news visual_source '{visual_source}'")
    style = resolve_style_preset(paths.db_file, style_preset)["id"]
    ratio = (aspect_ratio or str(ws.get("default_aspect_ratio") or "9:16")).strip() or "9:16"
    clean_title = (title or "").strip() or (source_url[:60] if source_url else "Bản tin mới")

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO news_projects (
                workspace_id, title, source_kind, source_url, raw_text,
                character_id, visual_source, style_preset, aspect_ratio, target_lang, voice_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(workspace_id),
                clean_title,
                kind,
                source_url.strip(),
                raw_text.strip(),
                int(character_id) if character_id else None,
                vis_src,
                style,
                ratio,
                (target_lang or "vi").strip() or "vi",
                (voice_id or "vi-VN-HoaiMyNeural").strip(),
            ),
        )
        proj_id = int(cur.lastrowid)
        record_audit(
            conn,
            actor=actor,
            action="create_news_project",
            object_type="news_project",
            object_id=proj_id,
            detail=f"{kind}: {clean_title[:60]}",
        )
    proj = get_news_project(paths.db_file, proj_id)
    assert proj is not None
    return proj


def _hydrate_news(row: dict[str, Any]) -> dict[str, Any]:
    out = hydrate_row(
        row,
        json_fields={
            "facts": ("facts_json", {}),
            "script": ("script_json", []),
            "simulation_flags": ("simulation_flags_json", []),
        },
        bool_fields=("waiting_media",),
    )
    if out.get("waiting_media"):
        out["status"] = "waiting_media"
    return out


def get_news_project(db_file: Path, project_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM news_projects WHERE id = ?", (int(project_id),))
    return _hydrate_news(row) if row else None


def list_news_projects(db_file: Path, *, workspace_id: int) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        "SELECT * FROM news_projects WHERE workspace_id = ? ORDER BY id DESC LIMIT 100",
        (int(workspace_id),),
    )
    return [_hydrate_news(r) for r in rows]


def update_news_project(
    paths: AppPaths,
    project_id: int,
    *,
    title: str | None = None,
    script: list[dict[str, Any]] | None = None,
    character_id: int | None = None,
    visual_source: str | None = None,
    style_preset: str | None = None,
    aspect_ratio: str | None = None,
) -> dict[str, Any] | None:
    if get_news_project(paths.db_file, project_id) is None:
        return None
    sets: list[str] = ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: list[Any] = []
    if title is not None and title.strip():
        sets.append("title = ?")
        params.append(title.strip())
    if script is not None:
        sets.append("script_json = ?")
        params.append(json.dumps(script, ensure_ascii=False))
    if character_id is not None:
        sets.append("character_id = ?")
        params.append(int(character_id) if character_id > 0 else None)
    if visual_source is not None and visual_source.strip():
        vs = visual_source.strip().lower()
        if vs not in ("characters", "muse_video"):
            raise ValueError(f"Unsupported news visual_source '{visual_source}'")
        sets.append("visual_source = ?")
        params.append(vs)
    if style_preset is not None and style_preset.strip():
        sets.append("style_preset = ?")
        params.append(resolve_style_preset(paths.db_file, style_preset)["id"])
    if aspect_ratio is not None and aspect_ratio.strip():
        sets.append("aspect_ratio = ?")
        params.append(aspect_ratio.strip())
    params.append(int(project_id))
    with get_conn(paths.db_file) as conn:
        conn.execute(f"UPDATE news_projects SET {', '.join(sets)} WHERE id = ?", params)
    return get_news_project(paths.db_file, project_id)


def summarize_news_to_script(paths: AppPaths, project_id: int) -> dict[str, Any]:
    """Extracts facts + builds 3 factual script segments preserving numbers, dates, and percentages."""
    proj = get_news_project(paths.db_file, project_id)
    if proj is None:
        raise ValueError(f"News project #{project_id} not found")

    facts = extract_article_facts(
        str(proj["source_kind"]),
        source_url=str(proj.get("source_url") or ""),
        raw_text=str(proj.get("raw_text") or ""),
    )
    lang = str(proj.get("target_lang") or "vi")
    headline = str(facts["headline"])
    sentences: list[str] = list(facts.get("sentences") or [])
    tokens: list[str] = list(facts.get("preserved_tokens") or [])

    fact_sentence = next(
        (s for s in sentences[1:] if any(t in s for t in tokens)),
        sentences[1] if len(sentences) > 1 else (sentences[0] if sentences else headline),
    )
    closing_sentence = sentences[2] if len(sentences) > 2 else f"Theo dõi cập nhật tiếp theo về {headline[:36]}"

    l1 = fit_news_line(headline, lang, 2.4)
    l2 = fit_news_line(fact_sentence, lang, 3.2)
    l3 = fit_news_line(closing_sentence, lang, 2.4)

    # Guarantee key numeric tokens from the article are preserved verbatim in the script
    combined_now = f"{l1} {l2} {l3}"
    missing_nums = [tok for tok in tokens[:4] if tok not in combined_now]
    if missing_nums:
        l2 = f"{l2} ({', '.join(missing_nums)})".strip()

    script = [
        {"index": 0, "role": "hook", "duration_s": 2.4, "text": l1},
        {"index": 1, "role": "facts", "duration_s": 3.0, "text": l2},
        {"index": 2, "role": "takeaway", "duration_s": 2.4, "text": l3},
    ]

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            UPDATE news_projects
            SET title = COALESCE(NULLIF(?, ''), title),
                facts_json = ?,
                script_json = ?,
                status = 'summarized',
                error = NULL,
                updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = ?
            """,
            (headline[:90], json.dumps(facts, ensure_ascii=False), json.dumps(script, ensure_ascii=False), int(project_id)),
        )
    updated = get_news_project(paths.db_file, project_id)
    assert updated is not None
    return updated


def _resolve_news_shots(
    paths: AppPaths, proj: dict[str, Any], script: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], bool]:
    ws_id = int(proj["workspace_id"])
    ws = require_workspace(paths.db_file, ws_id)
    policy = str(ws.get("content_policy") or "strict_footage")
    aspect_ratio = str(proj.get("aspect_ratio") or "9:16")

    shot_ids: list[int] = []
    used_placeholder_image = False
    char_id = proj.get("character_id")
    if char_id:
        img = generate_ai_image(
            paths,
            workspace_id=ws_id,
            character_id=int(char_id),
            prompt=f"Ban tin: {proj['title']}",
            aspect_ratio=aspect_ratio,
            is_product_shot=False,
            animate_to_shot=True,
            actor="news_studio",
        )
        if "ai_image_canvas_placeholder" in (img.get("simulation_flags") or []):
            used_placeholder_image = True
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
        if policy == "strict_footage":
            raise PermissionError(
                "Workspace 'strict_footage' cần ít nhất 1 shot footage thật hoặc gắn Nhân vật presenter."
            )
        shot_ids.append(ensure_full_ai_canvas_shot(paths, ws_id, aspect_ratio))

    planned: list[dict[str, Any]] = []
    for idx, seg in enumerate(script):
        planned.append(
            {
                "shot_id": shot_ids[idx % len(shot_ids)],
                "duration_s": max(1.6, float(seg.get("duration_s") or 2.4)),
                "text": str(seg.get("text") or "").strip(),
            }
        )
    return planned, used_placeholder_image


def render_news_project(
    paths: AppPaths,
    project_id: int,
    *,
    build_pack: bool = True,
    visual_source: str | None = None,
) -> dict[str, Any]:
    """Renders News Project MP4 via FFmpeg + QC + optional 5-platform `.zip` publish pack."""
    if visual_source is not None and visual_source.strip():
        update_news_project(paths, project_id, visual_source=visual_source)
    proj = get_news_project(paths.db_file, project_id)
    if proj is None:
        raise ValueError(f"News project #{project_id} not found")

    if not proj.get("script"):
        proj = summarize_news_to_script(paths, project_id)

    ws_id = int(proj["workspace_id"])
    script = list(proj.get("script") or [])
    if not script:
        raise ValueError(f"News project #{project_id} has empty script")

    muse_partial = False
    if str(proj.get("visual_source") or "characters") == "muse_video":
        muse_shots, muse_partial = ensure_project_muse_shots(
            paths,
            workspace_id=ws_id,
            ref_type="news_project",
            ref_id=project_id,
            prompts_and_durations=[
                (f"Bản tin: {seg.get('text') or proj['title']}", max(4.0, float(seg.get("duration_s") or 4.0)))
                for seg in script
            ],
            aspect_ratio=str(proj.get("aspect_ratio") or "9:16"),
            character_id=int(proj["character_id"]) if proj.get("character_id") else None,
        )
        if muse_shots is None:
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    "UPDATE news_projects SET status = 'rendering', waiting_media = 1, error = NULL WHERE id = ?",
                    (int(project_id),),
                )
            waiting = get_news_project(paths.db_file, project_id)
            assert waiting is not None
            return waiting
    else:
        muse_shots = []

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE news_projects SET status = 'rendering', waiting_media = 0, error = NULL WHERE id = ?",
            (int(project_id),),
        )

    try:
        report_active_job_progress(0.15, f"Đang chọn phân cảnh bản tin #{project_id}...")
        if muse_shots:
            planned_shots = [
                {
                    "shot_id": muse_shots[idx % len(muse_shots)],
                    "duration_s": max(1.6, float(seg.get("duration_s") or 2.4)),
                    "text": str(seg.get("text") or "").strip(),
                }
                for idx, seg in enumerate(script)
            ]
            used_placeholder_image = False
        else:
            planned_shots, used_placeholder_image = _resolve_news_shots(paths, proj, script)
        facts = dict(proj.get("facts") or {})
        headline = str(facts.get("headline") or proj["title"])
        summary_caption = ". ".join(str(s.get("text") or "") for s in script).strip()

        eff_voice_id = str(proj.get("voice_id") or "").strip()
        if proj.get("character_id"):
            ch_row = query_one(paths.db_file, "SELECT voice_id FROM characters WHERE id = ?", (int(proj["character_id"]),))
            if ch_row and ch_row.get("voice_id") and eff_voice_id in ("", "vi-VN-HoaiMyNeural"):
                eff_voice_id = str(ch_row["voice_id"])

        t_lang = str(proj.get("target_lang") or "vi")
        legacy_lang = "vi" if t_lang.strip().lower().startswith("vi") else "en"
        plan_payload = {
            "news_project_id": project_id,
            "title": headline,
            "voice_id": eff_voice_id,
            "facts": facts,
            "shots": planned_shots,
            "caption_vi": summary_caption,
            "caption_en": summary_caption,
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
                    str(proj.get("style_preset") or "tiktok_karaoke"),
                    str(proj.get("aspect_ratio") or "9:16"),
                ),
            )
            video_id = int(cur.lastrowid)

        report_active_job_progress(0.45, f"Đang dựng video & lồng tiếng bản tin #{project_id}...")
        render_video(paths, video_id, auto_score=False, report_progress=False)
        v_row = query_one(
            paths.db_file, "SELECT qc_json, quality_score FROM videos WHERE id = ?", (video_id,)
        )
        if v_row and v_row.get("quality_score") is None:
            qc = loads_or(v_row.get("qc_json"), {})
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    "UPDATE videos SET quality_score = ? WHERE id = ?",
                    (8.7 if qc.get("passed") else 5.0, video_id),
                )
        try_autopilot_approve(paths, video_id)

        rel_pack = ""
        if build_pack:
            report_active_job_progress(0.82, "Đang đóng gói bộ đăng 5 nền tảng (.zip)...")
            raw_zip = build_publish_pack_zip(paths, video_id, cover_title=headline[:70])
            dest_zip = paths.output_dir / f"news_pack_{project_id}.zip"
            dest_zip.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(raw_zip, dest_zip)
            rel_pack = f"output/news_pack_{project_id}.zip"

        from videocreator.config import load_settings

        sim_flags: list[str] = []
        if muse_partial:
            sim_flags.append("muse_video_partial")
        if used_placeholder_image:
            sim_flags.append("ai_image_canvas_placeholder")
        cfg_v = load_settings(paths.config_file).voice.vi_provider
        q_row = query_one(paths.db_file, "SELECT quality_notes FROM videos WHERE id = ?", (video_id,))
        q_notes = str((q_row or {}).get("quality_notes") or "")
        if cfg_v in ("test_tone", "local") or "test_tone" in q_notes or "Không lồng tiếng được" in q_notes:
            sim_flags.append("tts_tone_placeholder")

        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                UPDATE news_projects
                SET output_video_id = ?,
                    publish_pack_path = ?,
                    simulation_flags_json = ?,
                    waiting_media = 0,
                    status = 'completed',
                    error = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE id = ?
                """,
                (video_id, rel_pack, json.dumps(sim_flags, ensure_ascii=False), int(project_id)),
            )
            record_audit(
                conn,
                actor="news_studio",
                action="render_news",
                object_type="news_project",
                object_id=int(project_id),
                detail=f"video #{video_id} pack={rel_pack}",
            )

        done = get_news_project(paths.db_file, project_id)
        assert done is not None
        return done
    except Exception as exc:
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE news_projects SET status = 'failed', waiting_media = 0, error = ? WHERE id = ?",
                (str(exc)[:400], int(project_id)),
            )
        raise


def run_news_render_job(paths: AppPaths, project_id: int) -> str:
    return run_studio_project_job(render_news_project, paths, project_id)


__all__ = [
    "VALID_NEWS_SOURCE_KINDS",
    "create_news_project",
    "extract_article_facts",
    "get_news_project",
    "list_news_projects",
    "render_news_project",
    "run_news_render_job",
    "summarize_news_to_script",
    "update_news_project",
]
