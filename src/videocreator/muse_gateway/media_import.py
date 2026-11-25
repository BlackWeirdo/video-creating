"""Media downloader & library importer for finished `muse_tasks` (`video`, `image`, `audio`)."""
from __future__ import annotations

import json
import logging
import shutil
from typing import Any

from videocreator.ai.budget import record_usage
from videocreator.db import get_conn, record_audit
from videocreator.muse_gateway.client import MuseGatewayClient
from videocreator.muse_gateway.errors import MuseGatewayError
from videocreator.muse_gateway.store import update_muse_task
from videocreator.paths import AppPaths
from videocreator.pipeline.broll import normalize_broll_clip
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_duration, probe_video
from videocreator.timeutil import utc_now_iso

logger = logging.getLogger("videocreator.muse_gateway.media_import")


def _select_best_media_entries(
    remote_task: dict[str, Any], kind: str
) -> list[dict[str, Any]]:
    raw_media = remote_task.get("media")
    items = [m for m in (raw_media or []) if isinstance(m, dict) and m.get("url")]
    if not items and remote_task.get("url"):
        items = [
            {
                "url": str(remote_task["url"]),
                "kind": kind,
                "duration_sec": remote_task.get("duration_sec"),
            }
        ]
    if kind == "video" and len(items) > 1:
        videos = [m for m in items if str(m.get("kind") or "video") == "video"]
        if videos:
            best = max(videos, key=lambda x: float(x.get("duration_sec") or 0.0))
            return [best]
    return items


def import_completed_muse_task(
    paths: AppPaths,
    client: MuseGatewayClient,
    task_row: dict[str, Any],
    remote_task: dict[str, Any],
) -> dict[str, Any]:
    """Downloads finished Muse media immediately into `media/` and registers `assets`/`shots`/`ai_images`."""
    task_id = int(task_row["id"])
    ws_id = int(task_row["workspace_id"])
    kind = str(task_row["kind"])
    model = str(task_row["model"])
    prompt = str(task_row["prompt"])
    partial = bool(remote_task.get("partial"))
    thread_url = str(remote_task.get("thread_url") or task_row.get("thread_url") or "") or None
    account_id = str(remote_task.get("account_id") or task_row.get("account_id") or "") or None
    result_text = str(remote_task.get("text") or "")

    if kind == "chat":
        record_usage(
            paths.db_file,
            provider="muse_gateway",
            model=model,
            kind="writer",
            route="subscription",
            units_in=len(prompt),
            units_out=len(result_text),
            cost_usd=0.0,
        )
        updated = update_muse_task(
            paths.db_file,
            task_id,
            status="succeeded",
            result_text=result_text,
            thread_url=thread_url,
            account_id=account_id,
            finished_at=utc_now_iso(),
            error=None,
        )
        assert updated is not None
        return updated

    entries = _select_best_media_entries(remote_task, kind)
    if not entries:
        raise MuseGatewayError(f"Muse Gateway trả task #{task_id} succeeded nhưng không có URL media")

    if kind == "video":
        raw_dl = paths.work_dir / f"muse_dl_{task_id}.mp4"
        client.download_media_to_file(str(entries[0]["url"]), raw_dl)
        rel_mp4 = f"assets/muse_vid_{task_id}.mp4"
        dest_mp4 = paths.media_dir / rel_mp4
        dest_mp4.parent.mkdir(parents=True, exist_ok=True)
        try:
            info = probe_video(raw_dl)
            if info.width > 0 and info.height > 0:
                shutil.copy2(raw_dl, dest_mp4)
                dur_s = float(info.duration_s)
            else:
                dur_s = normalize_broll_clip(raw_dl, dest_mp4)
        finally:
            raw_dl.unlink(missing_ok=True)

        meta = {
            "source": "muse",
            "muse_task_id": task_id,
            "model": model,
            "prompt": prompt[:300],
            "partial": partial,
        }
        with get_conn(paths.db_file) as conn:
            a_id = int(
                conn.execute(
                    "INSERT INTO assets (workspace_id, kind, path, duration_s, meta_json) VALUES (?, 'broll', ?, ?, ?)",
                    (ws_id, rel_mp4, round(dur_s, 3), json.dumps(meta, ensure_ascii=False)),
                ).lastrowid
            )
            s_id = int(
                conn.execute(
                    """
                    INSERT INTO shots (
                        footage_id, asset_id, idx, start_s, end_s,
                        description, tags_json, has_product, product_ids_json, quality
                    )
                    VALUES (NULL, ?, 0, 0.0, ?, ?, '["muse_video"]', 0, '[]', 4)
                    """,
                    (a_id, round(dur_s, 3), prompt[:160]),
                ).lastrowid
            )
            record_audit(
                conn,
                actor="muse_dispatcher",
                action="muse.video_imported",
                object_type="shot",
                object_id=s_id,
                detail=f"task={task_id} dur={dur_s:.2f}s partial={partial}",
            )

        record_usage(
            paths.db_file,
            provider="muse_gateway",
            model=model,
            kind="videogen",
            route="subscription",
            units_in=1,
            units_out=max(1, int(round(dur_s))),
            cost_usd=0.0,
        )
        updated = update_muse_task(
            paths.db_file,
            task_id,
            status="succeeded",
            local_path=rel_mp4,
            asset_id=a_id,
            shot_id=s_id,
            partial=partial,
            duration_sec=round(dur_s, 3),
            result_text=result_text,
            thread_url=thread_url,
            account_id=account_id,
            finished_at=utc_now_iso(),
            error=None,
        )
        assert updated is not None
        return updated

    if kind == "image":
        params = task_row.get("params") or {}
        ratio = str(params.get("ratio") or "9:16")
        first_img_id: int | None = None
        first_rel = ""
        for idx, entry in enumerate(entries[:4]):
            rel_png = f"characters/muse_img_{task_id}_{idx + 1}.png"
            dest_png = paths.media_dir / rel_png
            client.download_media_to_file(str(entry["url"]), dest_png)
            with get_conn(paths.db_file) as conn:
                img_id = int(
                    conn.execute(
                        """
                        INSERT INTO ai_images (
                            workspace_id, prompt, seed, aspect_ratio, image_path,
                            is_product_shot, provider, simulation_flags_json, status
                        )
                        VALUES (?, ?, ?, ?, ?, 0, 'muse_image', '[]', 'ready')
                        """,
                        (ws_id, prompt, 1000 + task_id + idx, ratio, rel_png),
                    ).lastrowid
                )
            if first_img_id is None:
                first_img_id = img_id
                first_rel = rel_png

        record_usage(
            paths.db_file,
            provider="muse_gateway",
            model=model,
            kind="videogen",
            route="subscription",
            units_in=1,
            units_out=len(entries[:4]),
            cost_usd=0.0,
        )
        updated = update_muse_task(
            paths.db_file,
            task_id,
            status="succeeded",
            local_path=first_rel,
            ai_image_id=first_img_id,
            result_text=result_text,
            thread_url=thread_url,
            account_id=account_id,
            finished_at=utc_now_iso(),
            error=None,
        )
        assert updated is not None
        return updated

    # kind == 'audio'
    raw_mp3 = paths.work_dir / f"muse_voice_{task_id}.mp3"
    client.download_media_to_file(str(entries[0]["url"]), raw_mp3)
    rel_wav = f"assets/muse_voice_{task_id}.wav"
    dest_wav = paths.media_dir / rel_wav
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    try:
        run_ffmpeg(
            [
                "-i",
                str(raw_mp3.resolve()),
                "-ar",
                "48000",
                "-ac",
                "1",
                "-c:a",
                "pcm_s16le",
                str(dest_wav.resolve()),
            ]
        )
    finally:
        raw_mp3.unlink(missing_ok=True)
    dur_s = round(probe_duration(dest_wav), 3)
    with get_conn(paths.db_file) as conn:
        a_id = int(
            conn.execute(
                "INSERT INTO assets (workspace_id, kind, path, duration_s, meta_json) VALUES (?, 'sfx', ?, ?, ?)",
                (ws_id, rel_wav, dur_s, json.dumps({"source": "muse_voice", "muse_task_id": task_id})),
            ).lastrowid
        )
    record_usage(
        paths.db_file,
        provider="muse_gateway",
        model=model,
        kind="tts",
        route="subscription",
        units_in=len(prompt),
        units_out=max(1, int(round(dur_s))),
        cost_usd=0.0,
    )
    updated = update_muse_task(
        paths.db_file,
        task_id,
        status="succeeded",
        local_path=rel_wav,
        asset_id=a_id,
        duration_sec=dur_s,
        result_text=result_text,
        thread_url=thread_url,
        account_id=account_id,
        finished_at=utc_now_iso(),
        error=None,
    )
    assert updated is not None
    return updated


__all__ = ["import_completed_muse_task"]
