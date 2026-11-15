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
from videocreator.timeutil import local_day_start_utc_iso
from videocreator.db import get_conn, query_all, query_one
from videocreator.paths import AppPaths

logger = logging.getLogger("videocreator.trends.suggest")

DAILY_SUGGESTION_CAP = 3  # FR-TRD-07


class SuggestionCandidateSchema(BaseModel):
    trend_item_id: int
    text: str = Field(description="Mô tả đề xuất 1-2 câu tiếng Việt")
    formula_name: str = Field(default="hook-first")
    recommended_shot_ids: list[int] = Field(default_factory=list)
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
        "SELECT id, description, tags_json, has_product, quality FROM shots ORDER BY (description IS NOT NULL AND description != '') DESC, quality DESC, id ASC",
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


def select_suggestion_candidates(
    db_file: Path, trend_item_ids: list[int] | None = None
) -> list[dict[str, Any]]:
    """Analysed trend items without a suggestion yet, hand-picked (pinned) ones first, at most 6.

    `trend_item_ids` limits the candidates to those items (a pasted link is suggested on its own)."""
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
        SELECT t.*
        FROM trend_items t
        WHERE t.analysis_json IS NOT NULL AND t.analysis_json != ''
          AND NOT EXISTS (
              SELECT 1 FROM suggestions s WHERE s.trend_item_id = t.id
          )
          {id_filter}
        -- Videos the owner picked by hand (pasted links, metrics.pinned) go first: they are
        -- often older, so their score alone would keep them out of the top 6.
        ORDER BY COALESCE(json_extract(t.metrics_json, '$.pinned'), 0) DESC, t.score DESC, t.id ASC
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
    wp = writer_provider or get_provider(paths, "writer")

    trend_blocks = []
    valid_trend_ids = set()
    for it in analysed_items:
        tid = int(it["id"])
        valid_trend_ids.add(tid)
        trend_blocks.append(
            {
                "trend_item_id": tid,
                "source": it["source"],
                "author": it["author"],
                "url": it["url"],
                "score": it["score"],
                "analysis": json.loads(str(it["analysis_json"])),
            }
        )

    prompt = (
        f"Bạn là đạo diễn nội dung video ngắn cho thương hiệu trang sức bạc thủ công.\n"
        f"Dựa trên danh sách phân tích xu hướng bên dưới và KHO SHOT HIỆN CÓ, hãy đề xuất tối đa {max_suggestions} ý tưởng video.\n"
        "- Hãy điều chỉnh cấu trúc/nhịp điệu của xu hướng cho phù hợp với các shot đang có trong `KHO SHOT HIỆN CÓ` và chọn các `shot_id` có thật vào `recommended_shot_ids`.\n"
        "- Chỉ điền `missing_shots` khi kho shot thực sự không đủ cảnh để dựng thành video hoàn chỉnh; nếu đã có đủ shot để dựng (`total_shots > 0` và `recommended_shot_ids` không rỗng) thì để `missing_shots` là chuỗi rỗng `\"\"`.\n\n"
        f"PHÂN TÍCH XU HƯỚNG:\n{json.dumps(trend_blocks, ensure_ascii=False)}\n\n"
        f"TÓM TẮT KHO SHOT HIỆN CÓ:\n{json.dumps(lib_summary, ensure_ascii=False)}"
    )

    batch = wp.generate_json(prompt, SuggestionsBatchSchema)
    created_ids: list[int] = []

    with get_conn(paths.db_file) as conn:
        for cand in batch.suggestions[:max_suggestions]:
            tid = cand.trend_item_id if cand.trend_item_id in valid_trend_ids else next(iter(valid_trend_ids))
            text = cand.text.strip()
            missing = cand.missing_shots.strip()
            if cand.recommended_shot_ids:
                missing = ""
                text = re.sub(r"\s*\(cần quay thêm:[^)]*\)", "", text, flags=re.IGNORECASE).strip()
            elif missing and "cần quay thêm" not in text.lower():
                text = f"{text} (cần quay thêm: {missing})"

            formula_payload = {
                "formula": cand.formula_name.strip() or "hook-first",
                "recommended_shot_ids": cand.recommended_shot_ids,
                "missing_shots": missing,
            }
            cur = conn.execute(
                """
                INSERT INTO suggestions (trend_item_id, text, formula_json, status)
                VALUES (?, ?, ?, 'new')
                """,
                (tid, text, json.dumps(formula_payload, ensure_ascii=False)),
            )
            if cur.lastrowid:
                created_ids.append(int(cur.lastrowid))

    try:
        # Sends now, or leaves them `new` for the periodic flush when it is quiet hours (FR-TG-18).
        from videocreator.tg.notify import flush_deferred_notifications

        flush_deferred_notifications(paths)
    except Exception as tg_exc:
        logger.debug("Trend suggestion Telegram send skipped: %s", tg_exc)

    return created_ids
