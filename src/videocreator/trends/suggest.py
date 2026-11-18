"""Trend remix suggestion generator, shot-library matcher, and atomic accept/dismiss workflow (Phase 13)."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from videocreator.ai import AIProvider, get_provider
from videocreator.ai.budget import app_timezone
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one
from videocreator.paths import AppPaths
from videocreator.timeutil import local_day_start_utc_iso

logger = logging.getLogger("videocreator.trends.suggest")

DAILY_SUGGESTION_CAP = 3  # FR-TRD-07


class BeatShotMapping(BaseModel):
    beat_index: int = Field(default=0, ge=0, description="Chỉ số nhịp (beat) trong structure bắt đầu từ 0")
    shot_id: int = Field(description="ID của shot trong kho khớp với nhịp này")
    role: str = Field(default="closeup", description="Vai trò của nhịp (hook, process, closeup, wearing, cta)")


class SuggestionCandidateSchema(BaseModel):
    trend_item_id: int
    text: str = Field(description="Mô tả đề xuất 1-2 câu tiếng Việt")
    formula_name: str = Field(default="hook-first")
    recommended_shot_ids: list[int] = Field(default_factory=list)
    beat_shot_map: list[BeatShotMapping] = Field(default_factory=list)
    missing_shots: str = Field(
        default="",
        description="Ghi rõ loại cảnh cần quay thêm nếu kho shot hiện thiếu; để rỗng nếu kho đã đủ",
    )


class SuggestionsBatchSchema(BaseModel):
    suggestions: list[SuggestionCandidateSchema] = Field(default_factory=list)


def summarize_shot_library(db_file: Path) -> dict[str, Any]:
    """Summarizes available shots in `shots` table by tag, product presence, and IDs."""
    rows = query_all(
        db_file,
        "SELECT id, description, tags_json, has_product, quality, ROUND(end_s - start_s, 2) AS dur_s FROM shots ORDER BY (description IS NOT NULL AND description != '') DESC, quality DESC, id ASC",
    )
    tag_counts: dict[str, int] = {}
    shot_summaries: list[dict[str, Any]] = []
    product_shot_count = 0

    for r in rows:
        if int(r.get("has_product") or 0) == 1:
            product_shot_count += 1
        tags: list[str] = []
        if r.get("tags_json"):
            try:
                tags = [str(t) for t in json.loads(str(r["tags_json"]))]
            except Exception:
                tags = []
        for t in tags:
            tag_counts[t] = tag_counts.get(t, 0) + 1
        shot_summaries.append(
            {
                "id": int(r["id"]),
                "has_product": bool(r.get("has_product")),
                "duration_s": float(r.get("dur_s") or 0.0),
                "tags": tags,
                "description": str(r.get("description") or "")[:120],
            }
        )

    return {
        "total_shots": len(rows),
        "product_shots": product_shot_count,
        "broll_shots": len(rows) - product_shot_count,
        "tag_counts": tag_counts,
        "shots": shot_summaries[:60],
    }


def winning_formulas_summary(db_file: Path) -> list[dict[str, Any]]:
    """Aggregates real `72h` post performance by `plan_json.formula` to close the feedback loop."""
    rows = query_all(
        db_file,
        """
        SELECT json_extract(v.plan_json, '$.formula') AS formula,
               COUNT(*) AS post_count,
               ROUND(AVG(COALESCE(m.views, 0) + 20 * COALESCE(m.shares, 0) + 5 * COALESCE(m.likes, 0)), 1) AS avg_engagement
        FROM post_metrics m
        JOIN posts p ON p.id = m.post_id
        JOIN videos v ON v.id = p.video_id
        WHERE m.checkpoint = '72h' AND p.status = 'posted'
          AND json_extract(v.plan_json, '$.formula') IS NOT NULL
        GROUP BY formula
        ORDER BY avg_engagement DESC
        LIMIT 5
        """,
    )
    return [
        {
            "formula": str(r["formula"]),
            "posts": int(r["post_count"] or 0),
            "avg_engagement_72h": float(r["avg_engagement"] or 0.0),
        }
        for r in rows
        if r.get("formula")
    ]


def select_suggestion_candidates(
    db_file: Path, trend_item_ids: list[int] | None = None
) -> list[dict[str, Any]]:
    """Analysed trend items without a suggestion yet, balanced across sources (top #1 of each source first).

    Pinned items (hand-picked links) always go first, followed by video-analysed items ranked within
    their own source so sources with larger numeric scales (`ad_library`) never drown out social trends."""
    id_filter = ""
    params: tuple[Any, ...] = ()
    if trend_item_ids is not None:
        if not trend_item_ids:
            return []
        id_filter = f"AND t.id IN ({','.join('?' for _ in trend_item_ids)})"
        params = tuple(int(i) for i in trend_item_ids)
    return query_all(
        db_file,
        f"""
        WITH eligible AS (
            SELECT t.*,
                   COALESCE(json_extract(t.metrics_json, '$.pinned'), 0) AS is_pinned,
                   CASE WHEN COALESCE(json_extract(t.analysis_json, '$.analysis_mode'), 'video') = 'metadata_only' THEN 0 ELSE 1 END AS has_video_analysis,
                   ROW_NUMBER() OVER (
                       PARTITION BY t.source
                       ORDER BY t.score DESC, t.id ASC
                   ) AS src_rank
            FROM trend_items t
            WHERE t.analysis_json IS NOT NULL AND t.analysis_json != ''
              AND NOT EXISTS (
                  SELECT 1 FROM suggestions s WHERE s.trend_item_id = t.id
              )
              {id_filter}
        )
        SELECT *
        FROM eligible
        ORDER BY is_pinned DESC, has_video_analysis DESC, src_rank ASC, score DESC, id ASC
        LIMIT 6
        """,
        params,
    )


def make_suggestions(
    paths: AppPaths,
    *,
    writer_provider: AIProvider | None = None,
    max_suggestions: int = 3,
    trend_item_ids: list[int] | None = None,
) -> list[int]:
    """Generates up to `max_suggestions` remix suggestions from analysed `trend_items` and the shot library (`FR-TRD-07`)."""
    analysed_items = select_suggestion_candidates(paths.db_file, trend_item_ids)
    if not analysed_items:
        return []
    made_today = query_one(
        paths.db_file,
        "SELECT COUNT(*) AS c FROM suggestions WHERE created_at >= ?",
        (local_day_start_utc_iso(app_timezone(paths.db_file)),),
    )
    max_suggestions = min(max_suggestions, DAILY_SUGGESTION_CAP - int((made_today or {}).get("c") or 0))
    if max_suggestions <= 0:
        return []  # FR-TRD-07: at most 3 suggestions per day, however many scans run

    lib_summary = summarize_shot_library(paths.db_file)
    past_winners = winning_formulas_summary(paths.db_file)
    wp = writer_provider or get_provider(paths, "writer")

    trend_blocks = []
    analysis_by_tid: dict[int, dict[str, Any]] = {}
    for it in analysed_items:
        tid = int(it["id"])
        parsed_analysis = json.loads(str(it["analysis_json"]))
        analysis_by_tid[tid] = parsed_analysis if isinstance(parsed_analysis, dict) else {}
        trend_blocks.append(
            {
                "trend_item_id": tid,
                "source": it["source"],
                "author": it["author"],
                "url": it["url"],
                "score": it["score"],
                "analysis": analysis_by_tid[tid],
            }
        )
    valid_trend_ids = set(analysis_by_tid)
    valid_shot_ids = {int(s["id"]) for s in lib_summary["shots"]}

    perf_block = (
        f"\nHIỆU SUẤT THỰC TẾ 72H TRÊN KÊNH (ưu tiên công thức đã chứng minh hiệu quả):\n{json.dumps(past_winners, ensure_ascii=False)}\n"
        if past_winners
        else ""
    )
    prompt = (
        f"Bạn là đạo diễn nội dung video ngắn cho thương hiệu trang sức bạc thủ công.\n"
        f"Dựa trên danh sách phân tích xu hướng bên dưới và KHO SHOT HIỆN CÓ, hãy đề xuất tối đa {max_suggestions} ý tưởng video bám sát cấu trúc xu hướng nhất.\n"
        "- Hãy ánh xạ từng nhịp (beat) của xu hướng vào các `shot_id` có thật trong `KHO SHOT HIỆN CÓ` (`recommended_shot_ids` và `beat_shot_map`).\n"
        "- Chỉ điền `missing_shots` khi kho shot thực sự không đủ cảnh để dựng thành video hoàn chỉnh; nếu đã có đủ shot để dựng (`total_shots > 0` và `recommended_shot_ids` không rỗng) thì để `missing_shots` là chuỗi rỗng `\"\"`.\n\n"
        f"PHÂN TÍCH XU HƯỚNG:\n{json.dumps(trend_blocks, ensure_ascii=False)}\n"
        f"{perf_block}\n"
        f"TÓM TẮT KHO SHOT HIỆN CÓ:\n{json.dumps(lib_summary, ensure_ascii=False)}"
    )

    batch = wp.generate_json(prompt, SuggestionsBatchSchema)
    created_ids: list[int] = []
    auto_eligible_ids: list[int] = []

    with get_conn(paths.db_file) as conn:
        for cand in batch.suggestions[:max_suggestions]:
            tid = cand.trend_item_id if cand.trend_item_id in valid_trend_ids else next(iter(valid_trend_ids))
            rec_shots = [int(sid) for sid in cand.recommended_shot_ids if not valid_shot_ids or int(sid) in valid_shot_ids]
            beat_map = [
                {"beat_index": int(bm.beat_index), "shot_id": int(bm.shot_id), "role": bm.role.strip() or "closeup"}
                for bm in cand.beat_shot_map
                if not valid_shot_ids or int(bm.shot_id) in valid_shot_ids
            ]
            if not rec_shots and beat_map:
                rec_shots = list(dict.fromkeys(bm["shot_id"] for bm in beat_map))

            text = cand.text.strip()
            missing = cand.missing_shots.strip()
            if rec_shots:
                missing = ""
                text = re.sub(r"\s*\(cần quay thêm:[^)]*\)", "", text, flags=re.IGNORECASE).strip()
            elif missing and "cần quay thêm" not in text.lower():
                text = f"{text} (cần quay thêm: {missing})"

            formula_payload: dict[str, Any] = {
                "formula": cand.formula_name.strip() or "hook-first",
                "recommended_shot_ids": rec_shots,
                "missing_shots": missing,
            }
            if beat_map:
                formula_payload["beat_shot_map"] = beat_map

            cur = conn.execute(
                """
                INSERT INTO suggestions (trend_item_id, text, formula_json, status)
                VALUES (?, ?, ?, 'new')
                """,
                (tid, text, json.dumps(formula_payload, ensure_ascii=False)),
            )
            if cur.lastrowid:
                sid = int(cur.lastrowid)
                created_ids.append(sid)
                t_mode = str(analysis_by_tid.get(tid, {}).get("analysis_mode") or "video")
                if t_mode == "video" and not missing and lib_summary["total_shots"] > 0:
                    auto_eligible_ids.append(sid)

    settings = load_settings(paths.config_file)
    if settings.trends.auto_produce_top_n > 0 and auto_eligible_ids:
        from videocreator.trends.suggestion_actions import accept_suggestion

        for sid in auto_eligible_ids[: settings.trends.auto_produce_top_n]:
            try:
                accept_suggestion(paths, sid, count=1, auto_render=True, actor="auto_trend")
            except Exception as auto_exc:
                logger.warning("Auto-produce suggestion #%d skipped: %s", sid, auto_exc)

    try:
        # Sends remaining `new` suggestions now, or leaves them `new` during quiet hours (FR-TG-18).
        from videocreator.tg.notify import flush_deferred_notifications

        flush_deferred_notifications(paths)
    except Exception as tg_exc:
        logger.debug("Trend suggestion Telegram send skipped: %s", tg_exc)

    return created_ids
