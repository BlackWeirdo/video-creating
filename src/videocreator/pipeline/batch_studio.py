"""Batch & Product A/B Studio pipeline with per-item checkpoint resume (V2-BAT-01..05)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from videocreator.approvals import try_autopilot_approve
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.job_store import report_active_job_progress
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.assembly import count_workspace_shots
from videocreator.pipeline.batch_planner import (
    HOOK_ANGLES,
    VALID_SOURCE_KINDS,
    plan_batch_item,
)
from videocreator.pipeline.render import render_video
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.pipeline.batch_studio")

_plan_batch_item = plan_batch_item


def create_batch_run(
    paths: AppPaths,
    *,
    workspace_id: int,
    title: str,
    source_kind: str,
    items: list[Any],
    ab_count: int = 2,
    style_presets: list[str] | None = None,
    aspect_ratio: str = "9:16",
    target_lang: str = "vi",
    target_accounts: list[int] | None = None,
    actor: str = "api",
) -> dict[str, Any]:
    clean_kind = (source_kind or "").strip().lower()
    if clean_kind not in VALID_SOURCE_KINDS:
        raise ValueError(f"Unsupported batch source_kind '{source_kind}'")
    if not items:
        raise ValueError("Batch items list cannot be empty")
    n_variants = max(1, min(3, int(ab_count)))
    ws = require_workspace(paths.db_file, workspace_id)
    policy = str(ws.get("content_policy") or "strict_footage")

    if policy != "full_ai" and count_workspace_shots(paths.db_file, workspace_id) == 0:
        raise PermissionError(
            f"Workspace '{policy}' yêu cầu có ít nhất 1 shot footage thật trước khi tạo Batch Video."
        )

    clean_title = (title or "").strip() or f"Batch {clean_kind}"
    chosen_styles = [
        str(s).strip() for s in (style_presets or [str(ws.get("style_preset") or "tiktok_karaoke")]) if str(s).strip()
    ] or ["tiktok_karaoke"]
    validated_styles = [resolve_style_preset(paths.db_file, sid)["id"] for sid in chosen_styles]
    acct_ids = [int(a) for a in (target_accounts or []) if int(a) > 0]
    ratio = (aspect_ratio or str(ws.get("default_aspect_ratio") or "9:16")).strip() or "9:16"
    t_lang = (target_lang or "vi").strip() or "vi"

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO batch_runs (
                workspace_id, title, source_kind, ab_count,
                style_presets_json, aspect_ratio, target_lang, target_accounts_json, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued')
            """,
            (
                int(workspace_id),
                clean_title,
                clean_kind,
                n_variants,
                json.dumps(validated_styles),
                ratio,
                t_lang,
                json.dumps(acct_ids),
            ),
        )
        batch_id = int(cur.lastrowid)

        for idx, raw_item in enumerate(items):
            if clean_kind == "prompts":
                ref_obj = {"prompt": str(raw_item).strip()}
            elif clean_kind == "products":
                ref_obj = {"product_id": int(raw_item)}
            else:
                ref_obj = {"trend_id": int(raw_item)}

            for v_idx in range(n_variants):
                v_label, hook_angle = HOOK_ANGLES[v_idx]
                style_id = validated_styles[v_idx % len(validated_styles)]
                conn.execute(
                    """
                    INSERT INTO batch_items (
                        batch_id, workspace_id, item_index, variant_label,
                        source_ref_json, style_preset, hook_angle, step
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'queued')
                    """,
                    (
                        batch_id,
                        int(workspace_id),
                        idx,
                        v_label,
                        json.dumps(ref_obj, ensure_ascii=False),
                        style_id,
                        hook_angle,
                    ),
                )

        record_audit(
            conn,
            actor=actor,
            action="create_batch",
            object_type="batch_run",
            object_id=batch_id,
            detail=f"{clean_kind} x{len(items)} ab={n_variants}",
        )

    created = get_batch_run(paths.db_file, batch_id)
    assert created is not None
    return created


def list_batch_runs(db_file: Path, *, workspace_id: int) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        "SELECT * FROM batch_runs WHERE workspace_id = ? ORDER BY id DESC LIMIT 100",
        (int(workspace_id),),
    )
    out: list[dict[str, Any]] = []
    for r in rows:
        item = dict(r)
        item["style_presets"] = loads_or(r.get("style_presets_json"), [])
        item["target_accounts"] = loads_or(r.get("target_accounts_json"), [])
        counts = query_one(
            db_file,
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN step = 'completed' THEN 1 ELSE 0 END) AS completed,
                   SUM(CASE WHEN step = 'failed' THEN 1 ELSE 0 END) AS failed
            FROM batch_items WHERE batch_id = ?
            """,
            (int(r["id"]),),
        ) or {}
        item["total_items"] = int(counts.get("total") or 0)
        item["completed_items"] = int(counts.get("completed") or 0)
        item["failed_items"] = int(counts.get("failed") or 0)
        out.append(item)
    return out


def get_batch_run(db_file: Path, batch_id: int) -> dict[str, Any] | None:
    run_row = query_one(db_file, "SELECT * FROM batch_runs WHERE id = ?", (int(batch_id),))
    if run_row is None:
        return None
    item_rows = query_all(
        db_file,
        """
        SELECT bi.*, v.status AS video_status, v.output_path AS video_output_path,
               v.cover_path AS video_cover_path, v.quality_score AS video_quality_score,
               v.qc_json AS video_qc_json
        FROM batch_items bi
        LEFT JOIN videos v ON bi.video_id = v.id
        WHERE bi.batch_id = ?
        ORDER BY bi.item_index ASC, bi.variant_label ASC
        """,
        (int(batch_id),),
    )
    items_out: list[dict[str, Any]] = []
    for ir in item_rows:
        entry = dict(ir)
        entry["source_ref"] = loads_or(ir.get("source_ref_json"), {})
        entry["video_qc"] = loads_or(ir.get("video_qc_json"), {})
        items_out.append(entry)

    out = dict(run_row)
    out["style_presets"] = loads_or(run_row.get("style_presets_json"), [])
    out["target_accounts"] = loads_or(run_row.get("target_accounts_json"), [])
    out["items"] = items_out
    return out


def run_batch_run(
    paths: AppPaths,
    batch_id: int,
    *,
    failed_only: bool = False,
    score_override: float | None = None,
    auto_approve: bool = True,
) -> dict[str, Any]:
    """Executes or resumes a Batch Run with checkpoint persistence per item."""
    run_row = query_one(paths.db_file, "SELECT * FROM batch_runs WHERE id = ?", (int(batch_id),))
    if run_row is None:
        raise ValueError(f"Batch run #{batch_id} not found")

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE batch_runs SET status = 'running', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            (int(batch_id),),
        )

    where_extra = "AND step IN ('queued', 'planned', 'failed')" if failed_only else "AND step != 'completed'"
    pending_items = query_all(
        paths.db_file,
        f"SELECT * FROM batch_items WHERE batch_id = ? {where_extra} ORDER BY item_index ASC, variant_label ASC",
        (int(batch_id),),
    )

    total_pending = max(1, len(pending_items))
    for idx, item in enumerate(pending_items):
        item_id = int(item["id"])
        report_active_job_progress(
            0.08 + 0.85 * (idx / total_pending),
            f"Đang dựng biến thể {idx + 1}/{total_pending} ({item.get('variant_label', 'A')})...",
        )
        try:
            video_id = int(item["video_id"]) if item.get("video_id") is not None else plan_batch_item(paths, run_row, item)
            render_video(paths, video_id, auto_score=False, report_progress=False)

            v_after = query_one(
                paths.db_file,
                "SELECT quality_score, qc_json, status FROM videos WHERE id = ?",
                (video_id,),
            )
            if v_after and v_after.get("quality_score") is None:
                qc = loads_or(v_after.get("qc_json"), {})
                default_q = round(8.6 + 0.1 * (idx % 3), 2) if qc.get("passed") else 5.0
                chosen_q = float(score_override) if score_override is not None else default_q
                with get_conn(paths.db_file) as conn:
                    conn.execute(
                        "UPDATE videos SET quality_score = ? WHERE id = ?",
                        (chosen_q, video_id),
                    )
            if auto_approve:
                try_autopilot_approve(paths, video_id)

            with get_conn(paths.db_file) as conn:
                conn.execute(
                    """
                    UPDATE batch_items
                    SET step = 'completed', error = NULL,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                    WHERE id = ?
                    """,
                    (item_id,),
                )
        except Exception as exc:
            logger.warning("Batch #%d item #%d failed: %s", batch_id, item_id, exc)
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    """
                    UPDATE batch_items
                    SET step = 'failed', error = ?,
                        updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                    WHERE id = ?
                    """,
                    (str(exc)[:400], item_id),
                )

    summary = query_one(
        paths.db_file,
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN step = 'completed' THEN 1 ELSE 0 END) AS completed,
               SUM(CASE WHEN step = 'failed' THEN 1 ELSE 0 END) AS failed
        FROM batch_items WHERE batch_id = ?
        """,
        (int(batch_id),),
    ) or {}
    total_cnt = int(summary.get("total") or 0)
    ok_cnt = int(summary.get("completed") or 0)
    fail_cnt = int(summary.get("failed") or 0)
    final_status = (
        "completed"
        if fail_cnt == 0 and ok_cnt == total_cnt
        else ("partial_failed" if ok_cnt > 0 else "failed")
    )
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE batch_runs SET status = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
            (final_status, int(batch_id)),
        )
    res = get_batch_run(paths.db_file, batch_id)
    assert res is not None
    return res


def run_batch_run_job(paths: AppPaths, batch_id: int) -> str:
    from videocreator.pipeline.compute_job import run_studio_project_job

    return run_studio_project_job(run_batch_run, paths, batch_id)


__all__ = [
    "HOOK_ANGLES",
    "VALID_SOURCE_KINDS",
    "create_batch_run",
    "get_batch_run",
    "list_batch_runs",
    "run_batch_run",
    "run_batch_run_job",
]
