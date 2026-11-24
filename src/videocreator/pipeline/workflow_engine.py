"""Visual Workflow Node DAG validation, topological execution & JSON import/export (V2-WFL-01..05)."""
from __future__ import annotations

import json
import logging
import shutil
from collections import deque
from pathlib import Path
from typing import Any

from videocreator.approvals import try_autopilot_approve
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.batch_studio import _ensure_full_ai_canvas_shot
from videocreator.pipeline.characters import create_character, generate_ai_image, get_character
from videocreator.pipeline.export import resolve_canvas_dimensions
from videocreator.pipeline.news_studio import extract_article_facts
from videocreator.pipeline.render import _save_render_cache, finalize_master_export
from videocreator.pipeline.render_steps import concat_segments, cut_shot_segments
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.pipeline.subtitles import SubtitleEvent
from videocreator.posting.publish_pack import build_publish_pack_zip
from videocreator.state import transition
from videocreator.tts.synthesizer import TTSUnavailableError, synthesize_speech_segments
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.pipeline.workflow_engine")

VALID_NODE_KINDS: frozenset[str] = frozenset(
    {
        "character_node",
        "product_node",
        "news_node",
        "scene_node",
        "voice_node",
        "render_node",
        "publish_node",
    }
)


def _node_kind(node: dict[str, Any]) -> str:
    data = node.get("data") or {}
    raw = str(data.get("node_kind") or node.get("type") or "").strip()
    return raw if raw in VALID_NODE_KINDS else "scene_node"


def topological_sort_workflow(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Validates acyclic DAG structure via Kahn's algorithm and returns `(ordered_nodes, parents_map)`."""
    if not nodes:
        raise ValueError("Workflow must contain at least 1 node")

    by_id: dict[str, dict[str, Any]] = {}
    in_degree: dict[str, int] = {}
    children: dict[str, list[str]] = {}
    parents: dict[str, list[str]] = {}

    for node in nodes:
        nid = str(node.get("id") or "").strip()
        if not nid:
            raise ValueError("Every workflow node must have a non-empty id")
        if nid in by_id:
            raise ValueError(f"Duplicate workflow node id '{nid}'")
        by_id[nid] = node
        in_degree[nid] = 0
        children[nid] = []
        parents[nid] = []

    seen_edges: set[tuple[str, str]] = set()
    for edge in edges:
        src = str(edge.get("source") or "").strip()
        dst = str(edge.get("target") or "").strip()
        if src not in by_id or dst not in by_id:
            raise ValueError(f"Workflow edge references unknown node: {src} -> {dst}")
        if src == dst:
            raise ValueError(f"Workflow graph contains a self-loop on node '{src}'")
        if (src, dst) in seen_edges:
            continue
        seen_edges.add((src, dst))
        children[src].append(dst)
        parents[dst].append(src)
        in_degree[dst] += 1

    queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
    ordered: list[dict[str, Any]] = []
    while queue:
        nid = queue.popleft()
        ordered.append(by_id[nid])
        for nxt in children[nid]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if len(ordered) != len(by_id):
        raise ValueError("Workflow graph contains a cycle and cannot be executed as a DAG")

    return ordered, parents


def _hydrate_workflow(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["is_template"] = bool(row.get("is_template", 0))
    out["nodes"] = loads_or(row.get("nodes_json"), [])
    out["edges"] = loads_or(row.get("edges_json"), [])
    return out


def list_workflows(db_file: Path, *, workspace_id: int) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        """
        SELECT * FROM workflows
        WHERE workspace_id = ? OR is_template = 1
        ORDER BY is_template DESC, id DESC
        """,
        (int(workspace_id),),
    )
    return [_hydrate_workflow(r) for r in rows]


def get_workflow(db_file: Path, workflow_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM workflows WHERE id = ?", (int(workflow_id),))
    return _hydrate_workflow(row) if row else None


def create_workflow(
    paths: AppPaths,
    *,
    workspace_id: int,
    name: str,
    description: str = "",
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    is_template: bool = False,
    actor: str = "api",
) -> dict[str, Any]:
    require_workspace(paths.db_file, workspace_id)
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Workflow name is required")
    topological_sort_workflow(nodes, edges)

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO workflows (
                workspace_id, name, description, nodes_json, edges_json, is_template
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(workspace_id),
                clean_name,
                (description or "").strip(),
                json.dumps(nodes, ensure_ascii=False),
                json.dumps(edges, ensure_ascii=False),
                1 if is_template else 0,
            ),
        )
        wf_id = int(cur.lastrowid)
        record_audit(
            conn,
            actor=actor,
            action="create_workflow",
            object_type="workflow",
            object_id=wf_id,
            detail=f"{clean_name} ({len(nodes)} nodes)",
        )
    wf = get_workflow(paths.db_file, wf_id)
    assert wf is not None
    return wf


def update_workflow(
    paths: AppPaths,
    workflow_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    existing = get_workflow(paths.db_file, workflow_id)
    if existing is None:
        return None
    next_nodes = nodes if nodes is not None else existing["nodes"]
    next_edges = edges if edges is not None else existing["edges"]
    topological_sort_workflow(next_nodes, next_edges)

    sets: list[str] = ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: list[Any] = []
    if name is not None and name.strip():
        sets.append("name = ?")
        params.append(name.strip())
    if description is not None:
        sets.append("description = ?")
        params.append(description.strip())
    if nodes is not None:
        sets.append("nodes_json = ?")
        params.append(json.dumps(next_nodes, ensure_ascii=False))
    if edges is not None:
        sets.append("edges_json = ?")
        params.append(json.dumps(next_edges, ensure_ascii=False))
    params.append(int(workflow_id))
    with get_conn(paths.db_file) as conn:
        conn.execute(f"UPDATE workflows SET {', '.join(sets)} WHERE id = ?", params)
    return get_workflow(paths.db_file, workflow_id)


def delete_workflow(paths: AppPaths, workflow_id: int) -> bool:
    existing = get_workflow(paths.db_file, workflow_id)
    if existing is None:
        return False
    with get_conn(paths.db_file) as conn:
        conn.execute("DELETE FROM workflows WHERE id = ?", (int(workflow_id),))
    return True


def export_workflow_json(db_file: Path, workflow_id: int) -> dict[str, Any]:
    wf = get_workflow(db_file, workflow_id)
    if wf is None:
        raise ValueError(f"Workflow #{workflow_id} not found")
    return {
        "schema_version": 2,
        "name": wf["name"],
        "description": wf["description"],
        "nodes": wf["nodes"],
        "edges": wf["edges"],
    }


def import_workflow_json(
    paths: AppPaths, workspace_id: int, payload: dict[str, Any]
) -> dict[str, Any]:
    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("Invalid workflow JSON: 'nodes' and 'edges' must be lists")
    return create_workflow(
        paths,
        workspace_id=workspace_id,
        name=str(payload.get("name") or "Imported Workflow"),
        description=str(payload.get("description") or ""),
        nodes=nodes,
        edges=edges,
        actor="import",
    )


def execute_workflow(
    paths: AppPaths,
    workflow_id: int,
    *,
    workspace_id_override: int | None = None,
) -> dict[str, Any]:
    """Topologically executes a workflow DAG end-to-end and returns the workflow run record."""
    wf = get_workflow(paths.db_file, workflow_id)
    if wf is None:
        raise ValueError(f"Workflow #{workflow_id} not found")

    ws_id = int(workspace_id_override or wf["workspace_id"])
    ws = require_workspace(paths.db_file, ws_id)
    policy = str(ws.get("content_policy") or "strict_footage")
    ordered, parents_map = topological_sort_workflow(wf["nodes"], wf["edges"])

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            "INSERT INTO workflow_runs (workflow_id, workspace_id, status) VALUES (?, ?, 'running')",
            (int(workflow_id), ws_id),
        )
        run_id = int(cur.lastrowid)

    work_dir = paths.work_dir / f"workflow_{workflow_id}_run_{run_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    node_outputs: dict[str, Any] = {}
    final_video_id: int | None = None

    try:
        for node in ordered:
            nid = str(node["id"])
            kind = _node_kind(node)
            data = dict(node.get("data") or {})
            upstream = [node_outputs[p] for p in parents_map[nid] if p in node_outputs]

            if kind == "character_node":
                cid = int(data.get("character_id") or 0)
                ch = get_character(paths.db_file, cid) if cid > 0 else None
                if ch is None:
                    ch = create_character(
                        paths,
                        workspace_id=ws_id,
                        name=str(data.get("name") or "Workflow Character"),
                        appearance_prompt=str(data.get("appearance_prompt") or "Presenter studio"),
                        voice_id=str(data.get("voice_id") or "vi-VN-HoaiMyNeural"),
                        actor="workflow",
                    )
                img = generate_ai_image(
                    paths,
                    workspace_id=ws_id,
                    character_id=int(ch["id"]),
                    prompt=str(data.get("prompt") or ch["appearance_prompt"] or ch["name"]),
                    is_product_shot=False,
                    animate_to_shot=True,
                    actor="workflow",
                )
                node_outputs[nid] = {
                    "kind": kind,
                    "character_id": int(ch["id"]),
                    "voice_id": str(ch["voice_id"]),
                    "shot_ids": [int(img["motion_shot_id"])] if img.get("motion_shot_id") else [],
                    "text": str(data.get("prompt") or f"Xin chào từ {ch['name']}"),
                }

            elif kind == "product_node":
                pid = int(data.get("product_id") or 0)
                prod = (
                    query_one(paths.db_file, "SELECT * FROM products WHERE id = ? AND workspace_id = ?", (pid, ws_id))
                    if pid > 0
                    else query_one(
                        paths.db_file,
                        "SELECT * FROM products WHERE workspace_id = ? AND hidden = 0 ORDER BY id ASC LIMIT 1",
                        (ws_id,),
                    )
                )
                if prod is None:
                    raise ValueError("product_node could not find an active product in workspace")
                shot_rows = query_all(
                    paths.db_file,
                    """
                    SELECT s.id FROM shots s
                    LEFT JOIN footage f ON s.footage_id = f.id
                    WHERE COALESCE(f.workspace_id, 1) = ?
                    ORDER BY s.has_product DESC, s.quality DESC, s.id ASC LIMIT 3
                    """,
                    (ws_id,),
                )
                node_outputs[nid] = {
                    "kind": kind,
                    "product_ids": [int(prod["id"])],
                    "shot_ids": [int(r["id"]) for r in shot_rows],
                    "text": f"{prod['name']} {prod.get('material') or ''}".strip(),
                }

            elif kind == "news_node":
                facts = extract_article_facts(
                    "url" if data.get("source_url") else "raw_text",
                    source_url=str(data.get("source_url") or ""),
                    raw_text=str(data.get("raw_text") or "Tin tức nổi bật hôm nay."),
                )
                node_outputs[nid] = {
                    "kind": kind,
                    "title": str(facts["headline"]),
                    "text": ". ".join(facts["sentences"][:2]),
                }

            elif kind == "scene_node":
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
                        paths.db_file,
                        """
                        SELECT s.id FROM shots s
                        LEFT JOIN footage f ON s.footage_id = f.id
                        LEFT JOIN assets a ON s.asset_id = a.id
                        WHERE COALESCE(f.workspace_id, a.workspace_id, 1) = ?
                        ORDER BY s.quality DESC, s.id ASC LIMIT 3
                        """,
                        (ws_id,),
                    )
                    collected_shots = [int(r["id"]) for r in ws_shots]

                aspect_ratio = str(data.get("aspect_ratio") or ws.get("default_aspect_ratio") or "9:16")
                if not collected_shots:
                    if policy == "strict_footage":
                        raise PermissionError(
                            "Workspace 'strict_footage' cần ít nhất 1 shot thật hoặc character_node."
                        )
                    collected_shots = [_ensure_full_ai_canvas_shot(paths, ws_id, aspect_ratio)]

                prompt_txt = str(data.get("prompt") or "").strip()
                if prompt_txt:
                    texts.append(prompt_txt)
                combined_line = ". ".join(t for t in texts if t).strip() or "Video Workflow V2"
                planned_shots = [
                    {
                        "shot_id": collected_shots[0],
                        "duration_s": 2.6,
                        "text": combined_line[:80],
                    },
                    {
                        "shot_id": collected_shots[1 % len(collected_shots)],
                        "duration_s": 2.6,
                        "text": f"Khám phá chi tiết cùng {ws['name']}"[:80],
                    },
                ]
                node_outputs[nid] = {
                    "kind": kind,
                    "product_ids": sorted(set(collected_prods)),
                    "voice_id": voice_id,
                    "aspect_ratio": aspect_ratio,
                    "planned_shots": planned_shots,
                }

            elif kind == "voice_node":
                scene_up = next((u for u in upstream if "planned_shots" in u), upstream[0] if upstream else {})
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
                        work_dir=work_dir / f"tts_{nid}",
                    )
                except TTSUnavailableError:
                    track, _ = synthesize_speech_segments(
                        lines,
                        lang=legacy_lang,
                        voice=voice_id,
                        provider_name="local",
                        work_dir=work_dir / f"tts_{nid}",
                    )
                node_outputs[nid] = {
                    **scene_up,
                    "kind": kind,
                    "lang": lang,
                    "legacy_lang": legacy_lang,
                    "voice_wav_path": str(track.audio_path),
                }

            elif kind == "render_node":
                ctx: dict[str, Any] = {}
                for u in upstream:
                    ctx.update(u)
                planned_shots = list(ctx.get("planned_shots") or [])
                if not planned_shots:
                    raise ValueError("render_node requires upstream scene_node/voice_node planned_shots")
                ratio = str(data.get("aspect_ratio") or ctx.get("aspect_ratio") or "9:16")
                style_row = resolve_style_preset(
                    paths.db_file, str(data.get("style_preset") or ws.get("style_preset") or "tiktok_karaoke")
                )
                cw, ch_dim = resolve_canvas_dimensions(ratio)
                seg_files, sub_events, _dur = cut_shot_segments(
                    paths,
                    planned_shots,
                    work_dir,
                    keep_audio=False,
                    target_width=cw,
                    target_height=ch_dim,
                )
                cut_mp4 = concat_segments(seg_files, work_dir)
                voice_wav = Path(ctx["voice_wav_path"]) if ctx.get("voice_wav_path") and Path(ctx["voice_wav_path"]).exists() else None
                legacy_lang = str(ctx.get("legacy_lang") or "vi")
                t_lang = str(ctx.get("lang") or "vi")
                product_ids = list(ctx.get("product_ids") or [])

                with get_conn(paths.db_file) as conn:
                    v_cur = conn.execute(
                        """
                        INSERT INTO videos (
                            workspace_id, product_ids_json, engine, status, plan_json,
                            voice_lang, caption_lang, target_lang, style_preset, aspect_ratio, auto_render
                        )
                        VALUES (?, ?, 'ffmpeg', 'planned', ?, ?, ?, ?, ?, ?, 0)
                        """,
                        (
                            ws_id,
                            json.dumps(product_ids),
                            json.dumps({"workflow_id": workflow_id, "title": wf["name"], "shots": planned_shots}, ensure_ascii=False),
                            legacy_lang if voice_wav else "none",
                            legacy_lang,
                            t_lang,
                            style_row["id"],
                            ratio,
                        ),
                    )
                    video_id = int(v_cur.lastrowid)

                transition(paths.db_file, video_id, "rendering", expected_from="planned")
                rel_out, rel_cover, actual_dur, preflight_map, qc_report = finalize_master_export(
                    paths,
                    video_id=video_id,
                    cut_mp4=cut_mp4,
                    work_dir=work_dir,
                    sub_events=sub_events,
                    style_row=style_row,
                    aspect_ratio=ratio,
                    music_path=None,
                    voice_path=voice_wav,
                )
                render_cache = _save_render_cache(
                    paths,
                    video_id=video_id,
                    cut_mp4=cut_mp4,
                    voice_path=voice_wav,
                    sub_events=sub_events,
                    cut_times_s=[],
                    music_asset_id=None,
                    aspect_ratio=ratio,
                    mix_source_audio=False,
                )
                transition(paths.db_file, video_id, "rendered", expected_from="rendering")
                transition(paths.db_file, video_id, "pending_approval", expected_from="rendered")
                with get_conn(paths.db_file) as conn:
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
                final_video_id = video_id
                node_outputs[nid] = {
                    "kind": kind,
                    "video_id": video_id,
                    "output_path": rel_out,
                    "qc_passed": bool(qc_report.get("passed")),
                }

            elif kind == "publish_node":
                vid_up = next((int(u["video_id"]) for u in upstream if u.get("video_id")), final_video_id)
                if not vid_up:
                    raise ValueError("publish_node requires an upstream render_node output video_id")
                scheduled = try_autopilot_approve(paths, int(vid_up))
                pack_path = build_publish_pack_zip(paths, int(vid_up), cover_title=wf["name"][:60])
                node_outputs[nid] = {
                    "kind": kind,
                    "video_id": int(vid_up),
                    "autopilot_scheduled": scheduled,
                    "pack_zip": str(pack_path),
                }

        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                UPDATE workflow_runs
                SET status = 'completed', node_outputs_json = ?, video_id = ?, error = NULL
                WHERE id = ?
                """,
                (json.dumps(node_outputs, ensure_ascii=False), final_video_id, run_id),
            )
            conn.execute(
                "UPDATE workflows SET last_status = 'completed', last_video_id = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
                (final_video_id, int(workflow_id)),
            )
            record_audit(
                conn,
                actor="workflow",
                action="execute_workflow",
                object_type="workflow_run",
                object_id=run_id,
                detail=f"wf #{workflow_id} -> video #{final_video_id}",
            )
        return {
            "id": run_id,
            "workflow_id": int(workflow_id),
            "workspace_id": ws_id,
            "status": "completed",
            "video_id": final_video_id,
            "node_outputs": node_outputs,
        }
    except Exception as exc:
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE workflow_runs SET status = 'failed', error = ? WHERE id = ?",
                (str(exc)[:400], run_id),
            )
            conn.execute(
                "UPDATE workflows SET last_status = 'failed', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
                (int(workflow_id),),
            )
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def run_workflow_job(paths: AppPaths, workflow_id: int) -> str:
    res = execute_workflow(paths, workflow_id)
    return str(res.get("status") or "completed")
