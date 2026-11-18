"""Rows enriched for the page templates (parsed JSON columns, names, derived flags)."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from videocreator.approval_queue import video_display_fields
from videocreator.db import query_all
from videocreator.jsonutil import loads_or, parse_int_list


def enrich_footage_rows(
    db_file: Path, rows: list[dict[str, Any]], product_map: dict[int, str]
) -> list[dict[str, Any]]:
    shot_counts: dict[int, int] = {}
    for r in query_all(
        db_file,
        "SELECT footage_id, COUNT(*) AS cnt FROM shots WHERE footage_id IS NOT NULL GROUP BY footage_id",
    ):
        shot_counts[int(r["footage_id"])] = int(r["cnt"])

    job_logs: dict[int, str] = {}
    for j in query_all(
        db_file,
        "SELECT ref_id, log_tail, error FROM jobs WHERE kind = 'analyse' AND ref_id IS NOT NULL ORDER BY id DESC",
    ):
        fid = int(j["ref_id"])
        if fid not in job_logs and (j.get("log_tail") or j.get("error")):
            job_logs[fid] = str(j.get("error") or j.get("log_tail") or "")[-600:]

    result: list[dict[str, Any]] = []
    for r in rows:
        fid = int(r["id"])
        pids = parse_int_list(r.get("product_ids_json"))
        try:
            crop = json.loads(r["crop_json"]) if r.get("crop_json") else None
        except Exception:
            crop = None
        w = int(r.get("width") or 0)
        h = int(r.get("height") or 0)
        result.append(
            {
                **r,
                "product_ids": pids,
                "product_names": [product_map.get(pid, f"#{pid}") for pid in pids],
                "shot_count": shot_counts.get(fid, 0),
                "is_landscape": str(r.get("orientation")) == "landscape",
                "is_low_res": min(w, h) < 1080 if (w > 0 and h > 0) else False,
                "crop": crop or {"mode": "blur_pad", "x_offset_ratio": 0.5},
                "job_log_tail": job_logs.get(fid, ""),
            }
        )
    return result


def enrich_video_row(
    row: dict[str, Any],
    product_map: dict[int, str],
) -> dict[str, Any]:
    item = video_display_fields(row, product_map)
    plan = item["plan"]
    plan_caps = plan.get("captions") if isinstance(plan.get("captions"), dict) else {}
    override_caps = loads_or(row.get("captions_json"), {})
    if not isinstance(override_caps, dict):
        override_caps = {}
    return {
        **item,
        "mode": row.get("engine") or "ffmpeg",
        "shots": plan.get("shots") or [],
        "captions": {**plan_caps, **override_caps},
        "unverified_claims": plan.get("unverified_claims") or [],
    }
