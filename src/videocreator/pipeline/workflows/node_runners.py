"""Registry-based workflow DAG node runners."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from videocreator.approvals import try_autopilot_approve
from videocreator.db import get_conn, query_all, query_one
from videocreator.paths import AppPaths
from videocreator.pipeline.assembly import ensure_full_ai_canvas_shot, save_render_cache
from videocreator.pipeline.characters import create_character, generate_ai_image, get_character
from videocreator.pipeline.export import resolve_canvas_dimensions
from videocreator.pipeline.news_studio import extract_article_facts
from videocreator.pipeline.render import finalize_master_export
from videocreator.pipeline.render_steps import concat_segments, cut_shot_segments
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.posting.publish_pack import build_publish_pack_zip
from videocreator.state import transition
from videocreator.tts.synthesizer import TTSUnavailableError, synthesize_speech_segments


@dataclass
class WorkflowExecState:
    paths: AppPaths
    workflow_id: int
    wf: dict[str, Any]
    ws_id: int
    ws: dict[str, Any]
    policy: str
    work_dir: Path
    final_video_id: int | None = None


def _run_character_node(
    st: WorkflowExecState, _nid: str, data: dict[str, Any], _upstream: list[dict[str, Any]]
) -> dict[str, Any]:
    cid = int(data.get("character_id") or 0)
    ch = get_character(st.paths.db_file, cid) if cid > 0 else None
    if ch is None:
        ch = create_character(
            st.paths,
            workspace_id=st.ws_id,
            name=str(data.get("name") or "Workflow Character"),
            appearance_prompt=str(data.get("appearance_prompt") or "Presenter studio"),
            voice_id=str(data.get("voice_id") or "vi-VN-HoaiMyNeural"),
            actor="workflow",
        )
    img = generate_ai_image(
        st.paths,
        workspace_id=st.ws_id,
        character_id=int(ch["id"]),
        prompt=str(data.get("prompt") or ch["appearance_prompt"] or ch["name"]),
        is_product_shot=False,
        animate_to_shot=True,
        actor="workflow",
    )
    return {
        "kind": "character_node",
        "character_id": int(ch["id"]),
        "voice_id": str(ch["voice_id"]),
        "shot_ids": [int(img["motion_shot_id"])] if img.get("motion_shot_id") else [],
        "text": str(data.get("prompt") or f"Xin chào từ {ch['name']}"),
    }


def _run_product_node(
    st: WorkflowExecState, _nid: str, data: dict[str, Any], _upstream: list[dict[str, Any]]
) -> dict[str, Any]:
    pid = int(data.get("product_id") or 0)
    prod = (
        query_one(
            st.paths.db_file,
            "SELECT * FROM products WHERE id = ? AND workspace_id = ?",
            (pid, st.ws_id),
        )
        if pid > 0
        else query_one(
            st.paths.db_file,
            "SELECT * FROM products WHERE workspace_id = ? AND hidden = 0 ORDER BY id ASC LIMIT 1",
            (st.ws_id,),
        )
    )
    if prod is None:
        raise ValueError("product_node could not find an active product in workspace")
    shot_rows = query_all(
        st.paths.db_file,
        """
        SELECT s.id FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        WHERE COALESCE(f.workspace_id, 1) = ?
        ORDER BY s.has_product DESC, s.quality DESC, s.id ASC LIMIT 3
        """,
        (st.ws_id,),
    )
    return {
        "kind": "product_node",
        "product_ids": [int(prod["id"])],
        "shot_ids": [int(r["id"]) for r in shot_rows],
        "text": f"{prod['name']} {prod.get('material') or ''}".strip(),
    }


def _run_news_node(
    _st: WorkflowExecState, _nid: str, data: dict[str, Any], _upstream: list[dict[str, Any]]
) -> dict[str, Any]:
    facts = extract_article_facts(
        "url" if data.get("source_url") else "raw_text",
        source_url=str(data.get("source_url") or ""),
        raw_text=str(data.get("raw_text") or "Tin tức nổi bật hôm nay."),
    )
    return {
        "kind": "news_node",
        "title": str(facts["headline"]),
        "text": ". ".join(facts["sentences"][:2]),
    }


def run_scene_node(
    st: WorkflowExecState, _nid: str, data: dict[str, Any], upstream: list[dict[str, Any]]
) -> dict[str, Any]:
    collected_shots: list[int] = []
    collected_prods: list[int] = []
    voice_id = "vi-VN-HoaiMyNeural"
    texts: list[str] = []
    for up in upstream:
        collected_shots.extend(int(s) for s in (up.get("shot_ids") or []) if int(s) > 0)
        collected_prods.extend(int(p) for p in (up.get("product_ids") or []) if int(p) > 0)
        if up.get("voice_id"):
            voice_id = str(up["voice_id"])
        if up.get("text"):
            texts.append(str(up["text"]))

    if not collected_shots:
        ws_shots = query_all(
            st.paths.db_file,
            """
            SELECT s.id FROM shots s
            LEFT JOIN footage f ON s.footage_id = f.id
            LEFT JOIN assets a ON s.asset_id = a.id
            WHERE COALESCE(f.workspace_id, a.workspace_id, 1) = ?
            ORDER BY s.quality DESC, s.id ASC LIMIT 3
            """,
            (st.ws_id,),
        )
        collected_shots = [int(r["id"]) for r in ws_shots]

    aspect_ratio = str(data.get("aspect_ratio") or st.ws.get("default_aspect_ratio") or "9:16")
    if not collected_shots:
        if st.policy == "strict_footage":
            raise PermissionError(
                "Workspace 'strict_footage' cần ít nhất 1 shot thật hoặc character_node."
            )
        collected_shots = [ensure_full_ai_canvas_shot(st.paths, st.ws_id, aspect_ratio)]

    prompt_txt = str(data.get("prompt") or "").strip()
    if prompt_txt:
        texts.append(prompt_txt)
    combined_line = ". ".join(t for t in texts if t).strip() or "Video Workflow V2"
    planned_shots = [
        {"shot_id": collected_shots[0], "duration_s": 2.6, "text": combined_line[:80]},
        {
            "shot_id": collected_shots[1 % len(collected_shots)],
            "duration_s": 2.6,
            "text": f"Khám phá chi tiết cùng {st.ws['name']}"[:80],
        },
    ]
    return {
        "kind": "scene_node",
        "product_ids": sorted(set(collected_prods)),
        "voice_id": voice_id,
        "aspect_ratio": aspect_ratio,
        "planned_shots": planned_shots,
    }


def _run_voice_node(
    st: WorkflowExecState, nid: str, data: dict[str, Any], upstream: list[dict[str, Any]]
) -> dict[str, Any]:
    scene_up = next(
        (u for u in upstream if "planned_shots" in u), upstream[0] if upstream else {}
    )
    planned_shots = list(scene_up.get("planned_shots") or [])
    if not planned_shots:
        raise ValueError("voice_node requires an upstream scene_node with planned_shots")
    lang = str(data.get("lang") or "vi")
    legacy_lang = "vi" if lang.strip().lower().startswith("vi") else "en"
    voice_id = str(data.get("voice_id") or scene_up.get("voice_id") or "vi-VN-HoaiMyNeural")
    lines = [(str(ps["text"]), float(ps["duration_s"])) for ps in planned_shots]
    try:
        track, _ = synthesize_speech_segments(
            lines,
            lang=legacy_lang,
            voice=voice_id,
            provider_name=str(data.get("provider") or "local"),
            work_dir=st.work_dir / f"tts_{nid}",
        )
    except TTSUnavailableError:
        track, _ = synthesize_speech_segments(
            lines,
            lang=legacy_lang,
            voice=voice_id,
            provider_name="local",
            work_dir=st.work_dir / f"tts_{nid}",
        )
    return {
        **scene_up,
        "kind": "voice_node",
        "lang": lang,
        "legacy_lang": legacy_lang,
        "voice_wav_path": str(track.audio_path),
    }


def _run_render_node(
    st: WorkflowExecState, _nid: str, data: dict[str, Any], upstream: list[dict[str, Any]]
) -> dict[str, Any]:
    ctx: dict[str, Any] = {}
    for u in upstream:
        ctx.update(u)
    planned_shots = list(ctx.get("planned_shots") or [])
    if not planned_shots:
        raise ValueError("render_node requires upstream scene_node/voice_node planned_shots")
    ratio = str(data.get("aspect_ratio") or ctx.get("aspect_ratio") or "9:16")
    style_row = resolve_style_preset(
        st.paths.db_file,
        str(data.get("style_preset") or st.ws.get("style_preset") or "tiktok_karaoke"),
    )
    cw, ch_dim = resolve_canvas_dimensions(ratio)
    seg_files, sub_events, _dur = cut_shot_segments(
        st.paths,
        planned_shots,
        st.work_dir,
        keep_audio=False,
        target_width=cw,
        target_height=ch_dim,
    )
    cut_mp4 = concat_segments(seg_files, st.work_dir)
    voice_wav = (
        Path(ctx["voice_wav_path"])
        if ctx.get("voice_wav_path") and Path(ctx["voice_wav_path"]).exists()
        else None
    )
    legacy_lang = str(ctx.get("legacy_lang") or "vi")
    t_lang = str(ctx.get("lang") or "vi")
    product_ids = list(ctx.get("product_ids") or [])

    with get_conn(st.paths.db_file) as conn:
        v_cur = conn.execute(
            """
            INSERT INTO videos (
                workspace_id, product_ids_json, engine, status, plan_json,
                voice_lang, caption_lang, target_lang, style_preset, aspect_ratio, auto_render
            )
            VALUES (?, ?, 'ffmpeg', 'planned', ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                st.ws_id,
                json.dumps(product_ids),
                json.dumps(
                    {"workflow_id": st.workflow_id, "title": st.wf["name"], "shots": planned_shots},
                    ensure_ascii=False,
                ),
                legacy_lang if voice_wav else "none",
                legacy_lang,
                t_lang,
                style_row["id"],
                ratio,
            ),
        )
        video_id = int(v_cur.lastrowid)

    transition(st.paths.db_file, video_id, "rendering", expected_from="planned")
    rel_out, rel_cover, actual_dur, preflight_map, qc_report = finalize_master_export(
        st.paths,
        video_id=video_id,
        cut_mp4=cut_mp4,
        work_dir=st.work_dir,
        sub_events=sub_events,
        style_row=style_row,
        aspect_ratio=ratio,
        music_path=None,
        voice_path=voice_wav,
    )
    render_cache = save_render_cache(
        st.paths,
        video_id=video_id,
        cut_mp4=cut_mp4,
        voice_path=voice_wav,
        sub_events=sub_events,
        cut_times_s=[],
        music_asset_id=None,
        aspect_ratio=ratio,
        mix_source_audio=False,
    )
    transition(st.paths.db_file, video_id, "rendered", expected_from="rendering")
    transition(st.paths.db_file, video_id, "pending_approval", expected_from="rendered")
    with get_conn(st.paths.db_file) as conn:
        conn.execute(
            """
            UPDATE videos
            SET output_path = ?, cover_path = ?, duration_s = ?,
                preflight_json = ?, qc_json = ?, render_cache_json = ?,
                quality_score = ?, error = NULL
            WHERE id = ?
            """,
            (
                rel_out,
                rel_cover,
                round(actual_dur, 3),
                json.dumps(preflight_map, ensure_ascii=False),
                json.dumps(qc_report, ensure_ascii=False),
                json.dumps(render_cache, ensure_ascii=False),
                8.7 if qc_report.get("passed") else 5.0,
                video_id,
            ),
        )
    st.final_video_id = video_id
    return {
        "kind": "render_node",
        "video_id": video_id,
        "output_path": rel_out,
        "qc_passed": bool(qc_report.get("passed")),
    }


def _run_publish_node(
    st: WorkflowExecState, _nid: str, _data: dict[str, Any], upstream: list[dict[str, Any]]
) -> dict[str, Any]:
    vid_up = next(
        (int(u["video_id"]) for u in upstream if u.get("video_id")), st.final_video_id
    )
    if not vid_up:
        raise ValueError("publish_node requires an upstream render_node output video_id")
    scheduled = try_autopilot_approve(st.paths, int(vid_up))
    pack_path = build_publish_pack_zip(st.paths, int(vid_up), cover_title=st.wf["name"][:60])
    return {
        "kind": "publish_node",
        "video_id": int(vid_up),
        "autopilot_scheduled": scheduled,
        "pack_zip": str(pack_path),
    }


NodeRunner = Callable[
    [WorkflowExecState, str, dict[str, Any], list[dict[str, Any]]], dict[str, Any]
]

NODE_RUNNERS: dict[str, NodeRunner] = {
    "character_node": _run_character_node,
    "product_node": _run_product_node,
    "news_node": _run_news_node,
    "scene_node": run_scene_node,
    "voice_node": _run_voice_node,
    "render_node": _run_render_node,
    "publish_node": _run_publish_node,
}
