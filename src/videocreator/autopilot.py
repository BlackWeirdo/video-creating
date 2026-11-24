"""Channel Autopilot Engine: scheduled content generation, RSS/Trends ingestion & auto-publish (V2-AUT-01..04)."""
from __future__ import annotations

import hashlib
import html
import json
import logging
import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from videocreator.approvals import try_autopilot_approve
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.batch_studio import (
    _count_workspace_shots,
    create_batch_run,
    run_batch_run,
)
from videocreator.pipeline.localize import (
    create_localize_project,
    run_localize_extract,
    run_localize_render,
)
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.timeutil import UTC_ISO_FORMAT, utc_now
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.autopilot")

VALID_AUTOPILOT_MODES: frozenset[str] = frozenset(
    {"suggestions", "products_ab", "rss_feed", "localize_trends"}
)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(raw: str) -> str:
    txt = html.unescape(raw or "")
    txt = _TAG_RE.sub(" ", txt)
    return " ".join(txt.split()).strip()


def validate_autopilot_policy(
    db_file: Path, workspace_id: int, source_mode: str
) -> dict[str, Any]:
    clean_mode = (source_mode or "").strip().lower()
    if clean_mode not in VALID_AUTOPILOT_MODES:
        raise ValueError(f"Unsupported autopilot source_mode '{source_mode}'")

    ws = require_workspace(db_file, workspace_id)
    policy = str(ws.get("content_policy") or "strict_footage")
    if policy == "strict_footage" and clean_mode == "localize_trends":
        raise PermissionError(
            "Workspace 'strict_footage' không cho phép Autopilot chế độ 'localize_trends'."
        )
    if policy == "strict_footage" and clean_mode == "rss_feed" and _count_workspace_shots(db_file, workspace_id) == 0:
        raise PermissionError(
            "Workspace 'strict_footage' cần ít nhất 1 shot footage thật để chạy Autopilot 'rss_feed'."
        )
    return ws


def _hydrate_rule(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["enabled"] = bool(row.get("enabled", 1))
    out["target_account_ids"] = [
        int(x) for x in loads_or(row.get("target_account_ids_json"), []) if str(x).isdigit()
    ]
    return out


def list_autopilot_rules(
    db_file: Path, *, workspace_id: int | None = None
) -> list[dict[str, Any]]:
    if workspace_id is not None:
        rows = query_all(
            db_file,
            "SELECT * FROM autopilot_rules WHERE workspace_id = ? ORDER BY id DESC",
            (int(workspace_id),),
        )
    else:
        rows = query_all(db_file, "SELECT * FROM autopilot_rules ORDER BY workspace_id ASC, id DESC")
    return [_hydrate_rule(r) for r in rows]


def get_autopilot_rule(db_file: Path, rule_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM autopilot_rules WHERE id = ?", (int(rule_id),))
    return _hydrate_rule(row) if row else None


def list_autopilot_runs(
    db_file: Path,
    *,
    workspace_id: int | None = None,
    rule_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if workspace_id is not None:
        clauses.append("workspace_id = ?")
        params.append(int(workspace_id))
    if rule_id is not None:
        clauses.append("rule_id = ?")
        params.append(int(rule_id))
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    params.append(max(1, min(300, int(limit))))
    return query_all(
        db_file,
        f"SELECT * FROM autopilot_runs {where} ORDER BY id DESC LIMIT ?",
        params,
    )


def create_autopilot_rule(
    paths: AppPaths,
    *,
    workspace_id: int,
    name: str,
    source_mode: str,
    feed_url: str = "",
    target_account_ids: list[int] | None = None,
    daily_cap: int = 3,
    min_quality_score: float = 8.0,
    style_preset: str = "tiktok_karaoke",
    aspect_ratio: str = "9:16",
    interval_minutes: int = 60,
    enabled: bool = True,
    actor: str = "api",
) -> dict[str, Any]:
    validate_autopilot_policy(paths.db_file, workspace_id, source_mode)
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Autopilot rule name is required")
    if source_mode == "rss_feed" and not (feed_url or "").strip():
        raise ValueError("RSS/Atom feed URL or local file path is required for 'rss_feed' mode")

    cap = max(1, min(20, int(daily_cap)))
    interval_m = max(1, int(interval_minutes))
    style = resolve_style_preset(paths.db_file, style_preset)["id"]
    acct_ids = [int(a) for a in (target_account_ids or []) if int(a) > 0]

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO autopilot_rules (
                workspace_id, name, enabled, source_mode, feed_url,
                target_account_ids_json, daily_cap, min_quality_score,
                style_preset, aspect_ratio, interval_minutes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(workspace_id),
                clean_name,
                1 if enabled else 0,
                source_mode.strip().lower(),
                feed_url.strip(),
                json.dumps(acct_ids),
                cap,
                float(min_quality_score),
                style,
                (aspect_ratio or "9:16").strip() or "9:16",
                interval_m,
            ),
        )
        rule_id = int(cur.lastrowid)
        record_audit(
            conn,
            actor=actor,
            action="create_autopilot_rule",
            object_type="autopilot_rule",
            object_id=rule_id,
            detail=f"{clean_name} ({source_mode}, cap={cap})",
        )
    rule = get_autopilot_rule(paths.db_file, rule_id)
    assert rule is not None
    return rule


def update_autopilot_rule(
    paths: AppPaths,
    rule_id: int,
    *,
    name: str | None = None,
    enabled: bool | None = None,
    feed_url: str | None = None,
    target_account_ids: list[int] | None = None,
    daily_cap: int | None = None,
    min_quality_score: float | None = None,
    style_preset: str | None = None,
    aspect_ratio: str | None = None,
    interval_minutes: int | None = None,
) -> dict[str, Any] | None:
    existing = get_autopilot_rule(paths.db_file, rule_id)
    if existing is None:
        return None
    sets: list[str] = []
    params: list[Any] = []
    if name is not None and name.strip():
        sets.append("name = ?")
        params.append(name.strip())
    if enabled is not None:
        sets.append("enabled = ?")
        params.append(1 if enabled else 0)
    if feed_url is not None:
        sets.append("feed_url = ?")
        params.append(feed_url.strip())
    if target_account_ids is not None:
        sets.append("target_account_ids_json = ?")
        params.append(json.dumps([int(a) for a in target_account_ids if int(a) > 0]))
    if daily_cap is not None:
        sets.append("daily_cap = ?")
        params.append(max(1, min(20, int(daily_cap))))
    if min_quality_score is not None:
        sets.append("min_quality_score = ?")
        params.append(float(min_quality_score))
    if style_preset is not None and style_preset.strip():
        style = resolve_style_preset(paths.db_file, style_preset)["id"]
        sets.append("style_preset = ?")
        params.append(style)
    if aspect_ratio is not None and aspect_ratio.strip():
        sets.append("aspect_ratio = ?")
        params.append(aspect_ratio.strip())
    if interval_minutes is not None:
        sets.append("interval_minutes = ?")
        params.append(max(1, int(interval_minutes)))

    if sets:
        params.append(int(rule_id))
        with get_conn(paths.db_file) as conn:
            conn.execute(
                f"UPDATE autopilot_rules SET {', '.join(sets)} WHERE id = ?",
                params,
            )
    return get_autopilot_rule(paths.db_file, rule_id)


def delete_autopilot_rule(paths: AppPaths, rule_id: int) -> bool:
    existing = get_autopilot_rule(paths.db_file, rule_id)
    if existing is None:
        return False
    with get_conn(paths.db_file) as conn:
        conn.execute("DELETE FROM autopilot_rules WHERE id = ?", (int(rule_id),))
        record_audit(
            conn,
            actor="autopilot",
            action="delete_autopilot_rule",
            object_type="autopilot_rule",
            object_id=int(rule_id),
        )
    return True


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1].lower() if tag else ""


def parse_rss_or_atom_items(feed_url_or_path: str) -> list[dict[str, str]]:
    """Parses RSS 2.0 or Atom XML from HTTP URL, `file://` URI, or local XML file path."""
    raw_src = (feed_url_or_path or "").strip()
    if not raw_src:
        return []

    xml_bytes: bytes
    if raw_src.lower().startswith("file://"):
        parsed_uri = urlsplit(raw_src)
        local_path = Path(urllib.request.url2pathname(parsed_uri.path))
        xml_bytes = local_path.read_bytes()
    elif Path(raw_src).is_file():
        xml_bytes = Path(raw_src).read_bytes()
    else:
        req = urllib.request.Request(raw_src, headers={"User-Agent": "VideoCreator/2.0"})
        with urllib.request.urlopen(req, timeout=20.0) as resp:
            xml_bytes = resp.read()

    root = ET.fromstring(xml_bytes)
    items: list[dict[str, str]] = []
    for elem in root.iter():
        ltag = _local_tag(elem.tag)
        if ltag not in ("item", "entry"):
            continue
        title = ""
        summary = ""
        link = ""
        guid = ""
        for child in elem:
            ctag = _local_tag(child.tag)
            ctext = (child.text or "").strip()
            if ctag == "title" and not title:
                title = _strip_html(ctext)
            elif ctag in ("description", "summary", "content") and not summary:
                summary = _strip_html(ctext)
            elif ctag == "guid" and not guid:
                guid = ctext
            elif ctag == "id" and not guid:
                guid = ctext
            elif ctag == "link" and not link:
                href = str(child.attrib.get("href") or "").strip()
                link = href or ctext

        ident = guid or link or title
        if not ident:
            continue
        key_hash = hashlib.sha1(ident.encode("utf-8")).hexdigest()[:12]
        items.append(
            {
                "source_key": f"rss:{key_hash}",
                "title": title or link or ident,
                "summary": summary,
                "link": link,
            }
        )
    return items


def _already_processed_key(db_file: Path, rule_id: int, source_key: str) -> bool:
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


def _count_today_runs(db_file: Path, rule_id: int, now_dt: datetime) -> int:
    day_start = now_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    row = query_one(
        db_file,
        """
        SELECT COUNT(*) AS c FROM autopilot_runs
        WHERE rule_id = ?
          AND created_at >= ?
          AND status IN ('scheduled', 'pending_review', 'completed')
        """,
        (int(rule_id), day_start),
    )
    return int(row["c"]) if row else 0


def _interval_due(rule: dict[str, Any], now_dt: datetime) -> bool:
    last_raw = str(rule.get("last_run_at") or "").strip()
    if not last_raw:
        return True
    try:
        last_dt = datetime.strptime(last_raw, UTC_ISO_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    elapsed_s = (now_dt.astimezone(timezone.utc) - last_dt).total_seconds()
    return elapsed_s >= max(1, int(rule.get("interval_minutes") or 60)) * 60


def _record_rule_result(
    db_file: Path,
    rule_id: int,
    *,
    now_iso: str,
    status: str,
    error: str | None = None,
    inc_generated: bool = False,
) -> None:
    inc_sql = ", total_generated = total_generated + 1" if inc_generated else ""
    with get_conn(db_file) as conn:
        conn.execute(
            f"""
            UPDATE autopilot_rules
            SET last_run_at = ?, last_status = ?, last_error = ? {inc_sql}
            WHERE id = ?
            """,
            (now_iso, status, error, int(rule_id)),
        )


def _execute_single_rule(
    paths: AppPaths,
    rule: dict[str, Any],
    *,
    force: bool = False,
    score_override: float | None = None,
    now_dt: datetime | None = None,
) -> dict[str, Any]:
    rule_id = int(rule["id"])
    ws_id = int(rule["workspace_id"])
    cur_now = utc_now(now_dt)
    now_iso = cur_now.strftime(UTC_ISO_FORMAT)

    if not force and not _interval_due(rule, cur_now):
        return {"rule_id": rule_id, "status": "cooldown", "video_id": None}

    if _count_today_runs(paths.db_file, rule_id, cur_now) >= int(rule["daily_cap"]):
        _record_rule_result(paths.db_file, rule_id, now_iso=now_iso, status="daily_cap_reached")
        return {"rule_id": rule_id, "status": "daily_cap_reached", "video_id": None}

    mode = str(rule["source_mode"])
    validate_autopilot_policy(paths.db_file, ws_id, mode)
    target_accts = list(rule.get("target_account_ids") or [])
    style_preset = str(rule.get("style_preset") or "tiktok_karaoke")
    aspect_ratio = str(rule.get("aspect_ratio") or "9:16")

    source_key = ""
    source_summary = ""
    video_id: int | None = None
    batch_id: int | None = None
    localize_id: int | None = None

    try:
        if mode == "rss_feed":
            feed_items = parse_rss_or_atom_items(str(rule.get("feed_url") or ""))
            picked = next(
                (it for it in feed_items if not _already_processed_key(paths.db_file, rule_id, it["source_key"])),
                None,
            )
            if picked is None:
                _record_rule_result(paths.db_file, rule_id, now_iso=now_iso, status="no_new_items")
                return {"rule_id": rule_id, "status": "no_new_items", "video_id": None}
            source_key = picked["source_key"]
            source_summary = picked["title"][:120]
            prompt_text = f"{picked['title']}. {picked['summary'][:120]}".strip()
            batch = create_batch_run(
                paths,
                workspace_id=ws_id,
                title=f"Autopilot RSS: {picked['title'][:45]}",
                source_kind="prompts",
                items=[prompt_text],
                ab_count=1,
                style_presets=[style_preset],
                aspect_ratio=aspect_ratio,
                target_accounts=target_accts,
                actor="autopilot",
            )
            batch_id = int(batch["id"])
            done_batch = run_batch_run(
                paths, batch_id, score_override=score_override, auto_approve=False
            )
            if done_batch["items"] and done_batch["items"][0].get("video_id"):
                video_id = int(done_batch["items"][0]["video_id"])

        elif mode == "products_ab":
            prods = query_all(
                paths.db_file,
                "SELECT id, name FROM products WHERE workspace_id = ? AND hidden = 0 ORDER BY id ASC",
                (ws_id,),
            )
            picked_prod = next(
                (p for p in prods if not _already_processed_key(paths.db_file, rule_id, f"prod:{p['id']}")),
                prods[0] if prods else None,
            )
            if picked_prod is None:
                _record_rule_result(paths.db_file, rule_id, now_iso=now_iso, status="no_new_items")
                return {"rule_id": rule_id, "status": "no_new_items", "video_id": None}
            pid = int(picked_prod["id"])
            source_key = f"prod:{pid}:{cur_now.strftime('%Y%m%d%H%M')}" if _already_processed_key(paths.db_file, rule_id, f"prod:{pid}") else f"prod:{pid}"
            source_summary = str(picked_prod["name"])
            batch = create_batch_run(
                paths,
                workspace_id=ws_id,
                title=f"Autopilot SP: {picked_prod['name']}",
                source_kind="products",
                items=[pid],
                ab_count=1,
                style_presets=[style_preset],
                aspect_ratio=aspect_ratio,
                target_accounts=target_accts,
                actor="autopilot",
            )
            batch_id = int(batch["id"])
            done_batch = run_batch_run(
                paths, batch_id, score_override=score_override, auto_approve=False
            )
            if done_batch["items"] and done_batch["items"][0].get("video_id"):
                video_id = int(done_batch["items"][0]["video_id"])

        elif mode == "suggestions":
            sugs = query_all(
                paths.db_file,
                "SELECT id, text FROM suggestions WHERE workspace_id = ? AND status IN ('new', 'sent') ORDER BY id ASC LIMIT 20",
                (ws_id,),
            )
            picked_sug = next(
                (s for s in sugs if not _already_processed_key(paths.db_file, rule_id, f"sug:{s['id']}")),
                None,
            )
            if picked_sug is None:
                _record_rule_result(paths.db_file, rule_id, now_iso=now_iso, status="no_new_items")
                return {"rule_id": rule_id, "status": "no_new_items", "video_id": None}
            sid = int(picked_sug["id"])
            source_key = f"sug:{sid}"
            source_summary = str(picked_sug["text"])[:120]
            batch = create_batch_run(
                paths,
                workspace_id=ws_id,
                title=f"Autopilot Sug #{sid}",
                source_kind="prompts",
                items=[str(picked_sug["text"])],
                ab_count=1,
                style_presets=[style_preset],
                aspect_ratio=aspect_ratio,
                target_accounts=target_accts,
                actor="autopilot",
            )
            batch_id = int(batch["id"])
            done_batch = run_batch_run(
                paths, batch_id, score_override=score_override, auto_approve=False
            )
            if done_batch["items"] and done_batch["items"][0].get("video_id"):
                video_id = int(done_batch["items"][0]["video_id"])
            with get_conn(paths.db_file) as conn:
                conn.execute("UPDATE suggestions SET status = 'accepted' WHERE id = ?", (sid,))

        elif mode == "localize_trends":
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
                (t for t in trends if not _already_processed_key(paths.db_file, rule_id, f"trend_loc:{t['id']}")),
                None,
            )
            if picked_tr is None:
                _record_rule_result(paths.db_file, rule_id, now_iso=now_iso, status="no_new_items")
                return {"rule_id": rule_id, "status": "no_new_items", "video_id": None}
            tid = int(picked_tr["id"])
            ws = require_workspace(paths.db_file, ws_id)
            loc_mode = "reup_vi" if str(ws.get("content_policy")) == "full_ai" else "hybrid_remix"
            source_key = f"trend_loc:{tid}"
            source_summary = str(picked_tr.get("caption") or f"Trend #{tid}")[:120]
            proj = create_localize_project(
                paths,
                workspace_id=ws_id,
                title=f"Autopilot Loc: {source_summary[:40]}",
                mode=loc_mode,
                source_url=str(picked_tr.get("url") or ""),
                source_trend_id=tid,
                target_lang="vi",
                style_preset=style_preset,
                aspect_ratio=aspect_ratio,
                actor="autopilot",
            )
            localize_id = int(proj["id"])
            run_localize_extract(paths, localize_id)
            done_loc = run_localize_render(
                paths, localize_id, target_accounts=target_accts, auto_approve=False
            )
            if done_loc.get("output_video_id"):
                video_id = int(done_loc["output_video_id"])

        if video_id is None:
            raise RuntimeError("Autopilot generation produced no video output")

        v_row = query_one(
            paths.db_file,
            "SELECT quality_score, qc_json, status FROM videos WHERE id = ?",
            (video_id,),
        )
        assert v_row is not None
        qc = loads_or(v_row.get("qc_json"), {})
        if score_override is not None:
            eff_score = float(score_override)
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    "UPDATE videos SET quality_score = ? WHERE id = ?",
                    (eff_score, video_id),
                )
        else:
            eff_score = float(v_row.get("quality_score") or 0.0)

        scheduled = False
        min_req = float(rule.get("min_quality_score") or 8.0)
        if bool(qc.get("passed")) and eff_score >= min_req:
            scheduled = try_autopilot_approve(paths, video_id, now_dt=cur_now)

        run_status = "scheduled" if scheduled else "pending_review"
        detail = (
            f"video #{video_id} score={eff_score:.2f} (rule_min={min_req:.2f}) -> {run_status}"
        )
        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                INSERT INTO autopilot_runs (
                    rule_id, workspace_id, source_key, source_summary,
                    video_id, batch_id, localize_id, status, detail
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule_id,
                    ws_id,
                    source_key,
                    source_summary,
                    video_id,
                    batch_id,
                    localize_id,
                    run_status,
                    detail,
                ),
            )
        _record_rule_result(
            paths.db_file,
            rule_id,
            now_iso=now_iso,
            status=run_status,
            error=None,
            inc_generated=True,
        )
        return {
            "rule_id": rule_id,
            "status": run_status,
            "video_id": video_id,
            "scheduled": scheduled,
            "quality_score": eff_score,
            "detail": detail,
        }
    except Exception as exc:
        logger.warning("Autopilot rule #%d failed: %s", rule_id, exc)
        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                INSERT INTO autopilot_runs (
                    rule_id, workspace_id, source_key, source_summary,
                    video_id, batch_id, localize_id, status, detail
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'failed', ?)
                """,
                (
                    rule_id,
                    ws_id,
                    source_key,
                    source_summary,
                    video_id,
                    batch_id,
                    localize_id,
                    str(exc)[:400],
                ),
            )
        _record_rule_result(
            paths.db_file,
            rule_id,
            now_iso=now_iso,
            status="failed",
            error=str(exc)[:400],
        )
        return {"rule_id": rule_id, "status": "failed", "video_id": video_id, "error": str(exc)}


def run_autopilot_tick(
    paths: AppPaths,
    *,
    rule_id: int | None = None,
    force: bool = False,
    score_override: float | None = None,
    now_dt: datetime | None = None,
) -> list[dict[str, Any]]:
    """Executes one Autopilot tick for a single rule (`rule_id`) or all enabled rules."""
    if rule_id is not None:
        rule = get_autopilot_rule(paths.db_file, rule_id)
        if rule is None:
            raise ValueError(f"Autopilot rule #{rule_id} not found")
        if not rule["enabled"] and not force:
            return [{"rule_id": rule_id, "status": "disabled", "video_id": None}]
        return [
            _execute_single_rule(
                paths,
                rule,
                force=force,
                score_override=score_override,
                now_dt=now_dt,
            )
        ]

    rules = [
        _hydrate_rule(r)
        for r in query_all(
            paths.db_file, "SELECT * FROM autopilot_rules WHERE enabled = 1 ORDER BY id ASC"
        )
    ]
    results: list[dict[str, Any]] = []
    for r in rules:
        results.append(
            _execute_single_rule(
                paths,
                r,
                force=force,
                score_override=score_override,
                now_dt=now_dt,
            )
        )
    return results
