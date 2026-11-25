"""Source item producers for Autopilot rules (RSS, product A/B, suggestions, trend localization)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from videocreator.autopilot.sources import parse_rss_or_atom_items
from videocreator.db import get_conn, query_all, query_one
from videocreator.paths import AppPaths
from videocreator.pipeline.batch_studio import create_batch_run, run_batch_run
from videocreator.pipeline.localize import (
    create_localize_project,
    run_localize_extract,
    run_localize_render,
)
from videocreator.workspaces import require_workspace


@dataclass
class ProducedItem:
    source_key: str
    source_summary: str
    video_id: int | None
    batch_id: int | None = None
    localize_id: int | None = None


def already_processed_key(db_file: Path, rule_id: int, source_key: str) -> bool:
    row = query_one(
        db_file,
        """
        SELECT id FROM autopilot_runs
        WHERE rule_id = ? AND source_key = ? AND status != 'failed'
        LIMIT 1
        """,
        (int(rule_id), source_key),
    )
    return row is not None


def _produce_from_rss(
    paths: AppPaths,
    rule: dict[str, Any],
    *,
    score_override: float | None,
) -> ProducedItem | None:
    rule_id = int(rule["id"])
    ws_id = int(rule["workspace_id"])
    feed_items = parse_rss_or_atom_items(str(rule.get("feed_url") or ""))
    picked = next(
        (
            it
            for it in feed_items
            if not already_processed_key(paths.db_file, rule_id, it["source_key"])
        ),
        None,
    )
    if picked is None:
        return None
    prompt_text = f"{picked['title']}. {picked['summary'][:120]}".strip()
    batch = create_batch_run(
        paths,
        workspace_id=ws_id,
        title=f"Autopilot RSS: {picked['title'][:45]}",
        source_kind="prompts",
        items=[prompt_text],
        ab_count=1,
        style_presets=[str(rule.get("style_preset") or "tiktok_karaoke")],
        aspect_ratio=str(rule.get("aspect_ratio") or "9:16"),
        target_accounts=list(rule.get("target_account_ids") or []),
        actor="autopilot",
    )
    batch_id = int(batch["id"])
    done_batch = run_batch_run(
        paths, batch_id, score_override=score_override, auto_approve=False
    )
    vid = (
        int(done_batch["items"][0]["video_id"])
        if done_batch["items"] and done_batch["items"][0].get("video_id")
        else None
    )
    return ProducedItem(
        source_key=picked["source_key"],
        source_summary=picked["title"][:120],
        video_id=vid,
        batch_id=batch_id,
    )


def _produce_from_products_ab(
    paths: AppPaths,
    rule: dict[str, Any],
    *,
    cur_now: datetime,
    score_override: float | None,
) -> ProducedItem | None:
    rule_id = int(rule["id"])
    ws_id = int(rule["workspace_id"])
    prods = query_all(
        paths.db_file,
        "SELECT id, name FROM products WHERE workspace_id = ? AND hidden = 0 ORDER BY id ASC",
        (ws_id,),
    )
    picked_prod = next(
        (
            p
            for p in prods
            if not already_processed_key(paths.db_file, rule_id, f"prod:{p['id']}")
        ),
        prods[0] if prods else None,
    )
    if picked_prod is None:
        return None
    pid = int(picked_prod["id"])
    source_key = (
        f"prod:{pid}:{cur_now.strftime('%Y%m%d%H%M')}"
        if already_processed_key(paths.db_file, rule_id, f"prod:{pid}")
        else f"prod:{pid}"
    )
    batch = create_batch_run(
        paths,
        workspace_id=ws_id,
        title=f"Autopilot SP: {picked_prod['name']}",
        source_kind="products",
        items=[pid],
        ab_count=1,
        style_presets=[str(rule.get("style_preset") or "tiktok_karaoke")],
        aspect_ratio=str(rule.get("aspect_ratio") or "9:16"),
        target_accounts=list(rule.get("target_account_ids") or []),
        actor="autopilot",
    )
    batch_id = int(batch["id"])
    done_batch = run_batch_run(
        paths, batch_id, score_override=score_override, auto_approve=False
    )
    vid = (
        int(done_batch["items"][0]["video_id"])
        if done_batch["items"] and done_batch["items"][0].get("video_id")
        else None
    )
    return ProducedItem(
        source_key=source_key,
        source_summary=str(picked_prod["name"]),
        video_id=vid,
        batch_id=batch_id,
    )


def _produce_from_suggestions(
    paths: AppPaths,
    rule: dict[str, Any],
    *,
    score_override: float | None,
) -> ProducedItem | None:
    rule_id = int(rule["id"])
    ws_id = int(rule["workspace_id"])
    sugs = query_all(
        paths.db_file,
        "SELECT id, text FROM suggestions WHERE workspace_id = ? AND status IN ('new', 'sent') ORDER BY id ASC LIMIT 20",
        (ws_id,),
    )
    picked_sug = next(
        (
            s
            for s in sugs
            if not already_processed_key(paths.db_file, rule_id, f"sug:{s['id']}")
        ),
        None,
    )
    if picked_sug is None:
        return None
    sid = int(picked_sug["id"])
    batch = create_batch_run(
        paths,
        workspace_id=ws_id,
        title=f"Autopilot Sug #{sid}",
        source_kind="prompts",
        items=[str(picked_sug["text"])],
        ab_count=1,
        style_presets=[str(rule.get("style_preset") or "tiktok_karaoke")],
        aspect_ratio=str(rule.get("aspect_ratio") or "9:16"),
        target_accounts=list(rule.get("target_account_ids") or []),
        actor="autopilot",
    )
    batch_id = int(batch["id"])
    done_batch = run_batch_run(
        paths, batch_id, score_override=score_override, auto_approve=False
    )
    vid = (
        int(done_batch["items"][0]["video_id"])
        if done_batch["items"] and done_batch["items"][0].get("video_id")
        else None
    )
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE suggestions SET status = 'accepted' WHERE id = ?", (sid,))
    return ProducedItem(
        source_key=f"sug:{sid}",
        source_summary=str(picked_sug["text"])[:120],
        video_id=vid,
        batch_id=batch_id,
    )


def _produce_from_localize_trends(
    paths: AppPaths,
    rule: dict[str, Any],
) -> ProducedItem | None:
    rule_id = int(rule["id"])
    ws_id = int(rule["workspace_id"])
    trends = query_all(
        paths.db_file,
        """
        SELECT ti.id, ti.caption, ti.url
        FROM trend_items ti
        JOIN reference_videos rv ON rv.trend_item_id = ti.id
        WHERE ti.workspace_id = ? AND rv.deleted_at IS NULL
        ORDER BY ti.score DESC, ti.id DESC LIMIT 20
        """,
        (ws_id,),
    )
    picked_tr = next(
        (
            t
            for t in trends
            if not already_processed_key(paths.db_file, rule_id, f"trend_loc:{t['id']}")
        ),
        None,
    )
    if picked_tr is None:
        return None
    tid = int(picked_tr["id"])
    ws = require_workspace(paths.db_file, ws_id)
    loc_mode = "reup_vi" if str(ws.get("content_policy")) == "full_ai" else "hybrid_remix"
    source_summary = str(picked_tr.get("caption") or f"Trend #{tid}")[:120]
    proj = create_localize_project(
        paths,
        workspace_id=ws_id,
        title=f"Autopilot Loc: {source_summary[:40]}",
        mode=loc_mode,
        source_url=str(picked_tr.get("url") or ""),
        source_trend_id=tid,
        target_lang="vi",
        style_preset=str(rule.get("style_preset") or "tiktok_karaoke"),
        aspect_ratio=str(rule.get("aspect_ratio") or "9:16"),
        actor="autopilot",
    )
    localize_id = int(proj["id"])
    run_localize_extract(paths, localize_id)
    done_loc = run_localize_render(
        paths,
        localize_id,
        target_accounts=list(rule.get("target_account_ids") or []),
        auto_approve=False,
    )
    vid = int(done_loc["output_video_id"]) if done_loc.get("output_video_id") else None
    return ProducedItem(
        source_key=f"trend_loc:{tid}",
        source_summary=source_summary,
        video_id=vid,
        localize_id=localize_id,
    )


def _produce_from_muse_video(
    paths: AppPaths,
    rule: dict[str, Any],
) -> ProducedItem | None:
    from videocreator.config import load_settings
    from videocreator.muse_gateway.store import create_muse_task

    rule_id = int(rule["id"])
    ws_id = int(rule["workspace_id"])
    ws = require_workspace(paths.db_file, ws_id)
    if str(ws.get("content_policy") or "strict_footage") != "full_ai":
        raise PermissionError("Autopilot muse_video requires full_ai workspace")

    source_key = ""
    prompt_text = ""
    feed_url = str(rule.get("feed_url") or "").strip()
    if feed_url:
        for it in parse_rss_or_atom_items(feed_url):
            if not already_processed_key(paths.db_file, rule_id, f"muse_rss:{it['source_key']}"):
                source_key = f"muse_rss:{it['source_key']}"
                prompt_text = f"{it['title']}. {it['summary'][:140]}".strip()
                break
    if not prompt_text:
        trends = query_all(
            paths.db_file,
            "SELECT id, caption FROM trend_items WHERE workspace_id = ? ORDER BY score DESC, id DESC LIMIT 20",
            (ws_id,),
        )
        for tr in trends:
            cand_key = f"muse_trend:{tr['id']}"
            if not already_processed_key(paths.db_file, rule_id, cand_key):
                source_key = cand_key
                prompt_text = str(tr.get("caption") or f"Cảnh xu hướng #{tr['id']}")[:180]
                break
    if not prompt_text:
        return None

    cfg = load_settings(paths.config_file).muse_gateway
    ratio = str(rule.get("aspect_ratio") or "9:16")
    create_muse_task(
        paths.db_file,
        workspace_id=ws_id,
        kind="video",
        model=cfg.default_video_model or "muse-video",
        purpose="autopilot",
        ref_type="autopilot_rule",
        ref_id=rule_id,
        prompt=prompt_text,
        params={"duration": 8, "ratio": ratio if ratio in ("9:16", "16:9", "1:1") else "9:16"},
        priority=0,
    )
    return ProducedItem(
        source_key=source_key,
        source_summary=prompt_text[:120],
        video_id=None,
    )


def produce_autopilot_item(
    paths: AppPaths,
    rule: dict[str, Any],
    *,
    mode: str,
    cur_now: datetime,
    score_override: float | None,
) -> ProducedItem | None:
    """Dispatch Autopilot generation for `mode` and return the produced item (or `None`)."""
    if mode == "rss_feed":
        return _produce_from_rss(paths, rule, score_override=score_override)
    if mode == "products_ab":
        return _produce_from_products_ab(
            paths, rule, cur_now=cur_now, score_override=score_override
        )
    if mode == "suggestions":
        return _produce_from_suggestions(paths, rule, score_override=score_override)
    if mode == "localize_trends":
        return _produce_from_localize_trends(paths, rule)
    if mode == "muse_video":
        return _produce_from_muse_video(paths, rule)
    return None
