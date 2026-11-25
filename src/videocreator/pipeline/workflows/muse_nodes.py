"""Muse Gateway workflow DAG nodes (`muse_video_node`, `muse_image_node`, `muse_voice_node`)."""
from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

from videocreator.config import load_settings
from videocreator.db import get_conn, query_one
from videocreator.muse_gateway.client import MuseGatewayClient
from videocreator.muse_gateway.store import (
    ACTIVE_MUSE_TASK_STATUSES,
    create_muse_task,
    list_muse_tasks,
    update_muse_task,
)
from videocreator.muse_gateway.studio_bridge import MuseMediaPendingError
from videocreator.pipeline.ai_images import animate_image_to_shot
from videocreator.secrets_store import SecretsStore
from videocreator.tts.muse_engine import synthesize_muse_single

if TYPE_CHECKING:
    from videocreator.pipeline.workflows.node_runners import WorkflowExecState


def run_muse_video_node(
    st: WorkflowExecState, nid: str, data: dict[str, Any], upstream: list[dict[str, Any]]
) -> dict[str, Any]:
    prod_ids = [int(p) for up in upstream for p in (up.get("product_ids") or []) if int(p) > 0]
    if st.policy == "strict_footage" and prod_ids:
        raise PermissionError(
            "Workspace 'strict_footage' cấm nối product_node vào muse_video_node (BR-PRD-01)."
        )
    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        texts = [str(up["text"]) for up in upstream if up.get("text")]
        prompt = ". ".join(texts).strip() or f"Cảnh chuyển động điện ảnh cho {st.ws['name']}"
    seconds = max(4, min(60, int(data.get("duration_sec") or data.get("seconds") or 6)))
    ratio = str(data.get("aspect_ratio") or st.ws.get("default_aspect_ratio") or "9:16")
    if ratio not in ("9:16", "16:9", "1:1", "4:3", "3:4"):
        ratio = "9:16"

    refs: list[dict[str, Any]] = []
    for up in upstream:
        cid = int(up.get("character_id") or 0)
        if cid > 0:
            ch = query_one(
                st.paths.db_file,
                "SELECT cutout_image_path, ref_image_path FROM characters WHERE id = ?",
                (cid,),
            )
            if ch and (ch.get("cutout_image_path") or ch.get("ref_image_path")):
                refs.append({"type": "character", "id": cid})
    for pid in prod_ids[:2]:
        pr = query_one(st.paths.db_file, "SELECT photo_path FROM products WHERE id = ?", (pid,))
        if pr and pr.get("photo_path"):
            refs.append({"type": "product", "id": pid})

    existing = [
        t
        for t in list_muse_tasks(
            st.paths.db_file,
            workspace_id=st.ws_id,
            ref_type="workflow",
            ref_id=st.workflow_id,
            limit=50,
        )
        if (t.get("params") or {}).get("node_id") == nid
        and not (t.get("params") or {}).get("consumed")
    ]
    if not existing:
        cfg = load_settings(st.paths.config_file).muse_gateway
        create_muse_task(
            st.paths.db_file,
            workspace_id=st.ws_id,
            kind="video",
            model=str(data.get("model") or cfg.default_video_model or "muse-video"),
            purpose="workflow",
            ref_type="workflow",
            ref_id=st.workflow_id,
            prompt=prompt,
            params={"duration": seconds, "ratio": ratio, "node_id": nid},
            refs=refs[:16],
            priority=5,
        )
        raise MuseMediaPendingError(f"Đang chờ Muse render clip cho nút {nid}")

    latest = existing[0]
    if latest["status"] in ACTIVE_MUSE_TASK_STATUSES:
        raise MuseMediaPendingError(f"Đang chờ Muse hoàn tất clip cho nút {nid}")
    if latest["status"] != "succeeded" or not latest.get("shot_id"):
        update_muse_task(
            st.paths.db_file,
            int(latest["id"]),
            params={**dict(latest.get("params") or {}), "consumed": True},
        )
        raise RuntimeError(f"Muse video node '{nid}' thất bại: {latest.get('error') or latest['status']}")

    update_muse_task(
        st.paths.db_file,
        int(latest["id"]),
        params={**dict(latest.get("params") or {}), "consumed": True},
    )
    return {
        "kind": "muse_video_node",
        "node_id": nid,
        "shot_ids": [int(latest["shot_id"])],
        "product_ids": prod_ids,
        "text": prompt[:120],
    }


def run_muse_image_node(
    st: WorkflowExecState, nid: str, data: dict[str, Any], upstream: list[dict[str, Any]]
) -> dict[str, Any]:
    is_prod = bool(data.get("is_product_shot")) or any(up.get("product_ids") for up in upstream)
    if st.policy == "strict_footage" and is_prod:
        raise PermissionError(
            "Workspace 'strict_footage' cấm sinh ảnh sản phẩm bằng muse_image_node (BR-PRD-01)."
        )
    prompt = str(data.get("prompt") or "").strip() or f"Bối cảnh studio {st.ws['name']}"
    ratio = str(data.get("aspect_ratio") or st.ws.get("default_aspect_ratio") or "9:16")
    size = "1792x1024" if ratio == "16:9" else ("1024x1024" if ratio == "1:1" else "1024x1792")

    settings = load_settings(st.paths.config_file)
    secrets = SecretsStore(st.paths.secrets_file)
    client = MuseGatewayClient(settings.muse_gateway, secrets, timeout_s=180.0)
    client.verify_ready_and_safe()
    resp = client.generate_images(
        prompt=prompt,
        model=settings.muse_gateway.default_image_model or "muse-image",
        n=1,
        size=size,
        response_format="b64_json",
    )
    items = resp.get("data") if isinstance(resp, dict) else []
    if not items or not isinstance(items[0], dict):
        raise RuntimeError("Muse Gateway trả danh sách ảnh rỗng cho muse_image_node")

    with get_conn(st.paths.db_file) as conn:
        img_id = int(
            conn.execute(
                """
                INSERT INTO ai_images (
                    workspace_id, prompt, seed, aspect_ratio, is_product_shot,
                    provider, simulation_flags_json, status
                )
                VALUES (?, ?, 2400, ?, ?, 'muse_image', '[]', 'ready')
                """,
                (st.ws_id, prompt, ratio, 1 if is_prod else 0),
            ).lastrowid
        )
    rel_png = f"characters/muse_wf_img_{img_id}.png"
    dest_png = st.paths.media_dir / rel_png
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    if items[0].get("b64_json"):
        dest_png.write_bytes(base64.b64decode(str(items[0]["b64_json"])))
    else:
        client.download_media_to_file(str(items[0]["url"]), dest_png)

    with get_conn(st.paths.db_file) as conn:
        conn.execute("UPDATE ai_images SET image_path = ? WHERE id = ?", (rel_png, img_id))

    animated = animate_image_to_shot(st.paths, img_id)
    shot_ids = [int(animated["motion_shot_id"])] if animated.get("motion_shot_id") else []
    return {
        "kind": "muse_image_node",
        "node_id": nid,
        "ai_image_ids": [img_id],
        "shot_ids": shot_ids,
    }


def run_muse_voice_node(
    st: WorkflowExecState, nid: str, data: dict[str, Any], upstream: list[dict[str, Any]]
) -> dict[str, Any]:
    scene_up = next((u for u in upstream if "planned_shots" in u), {})
    text = str(data.get("text") or "").strip()
    if not text:
        if scene_up.get("planned_shots"):
            text = ". ".join(str(ps.get("text") or "") for ps in scene_up["planned_shots"]).strip()
        if not text:
            upstream_texts = [str(up["text"]) for up in upstream if up.get("text")]
            text = ". ".join(upstream_texts).strip() or f"Giới thiệu kênh {st.ws['name']}"
    voice = str(data.get("voice") or "Glad Kite").strip()
    lang = str(data.get("lang") or "vi").strip()
    legacy_lang = "vi" if lang.lower().startswith("vi") else "en"
    track = synthesize_muse_single(
        text,
        work_dir=st.work_dir / f"muse_voice_{nid}",
        voice=voice,
        lang=lang,
        paths=st.paths,
        stem=f"wf_muse_{nid}",
    )
    return {
        **scene_up,
        "kind": "muse_voice_node",
        "node_id": nid,
        "lang": lang,
        "legacy_lang": legacy_lang,
        "voice_path": str(track.audio_path),
        "voice_wav_path": str(track.audio_path),
        "duration_s": track.duration_s,
        "voice_id": f"muse:{voice}" if not voice.startswith("muse:") else voice,
        "text": text,
    }


__all__ = ["run_muse_image_node", "run_muse_video_node", "run_muse_voice_node"]
