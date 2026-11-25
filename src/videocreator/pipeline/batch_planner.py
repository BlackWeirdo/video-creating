"""Per-item shot selection, A/B hook script fitting, and video row planning for Batch Studio."""
from __future__ import annotations

import json
from typing import Any

from videocreator.db import get_conn, query_all, query_one
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.assembly import ensure_full_ai_canvas_shot
from videocreator.tts.syllables import count_syllables, max_syllables_for_duration
from videocreator.workspaces import require_workspace

VALID_SOURCE_KINDS: frozenset[str] = frozenset({"prompts", "products", "trends"})
HOOK_ANGLES: tuple[tuple[str, str], ...] = (
    ("A", "curiosity_problem"),
    ("B", "direct_proof"),
    ("C", "urgency_social"),
)


def pick_shots_for_batch_item(
    paths: AppPaths,
    workspace_id: int,
    product_id: int | None,
    aspect_ratio: str,
    policy: str,
) -> list[dict[str, Any]]:
    rows = query_all(
        paths.db_file,
        """
        SELECT s.id, s.start_s, s.end_s, s.has_product, s.product_ids_json
        FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        LEFT JOIN assets a ON s.asset_id = a.id
        WHERE COALESCE(f.workspace_id, a.workspace_id, 1) = ?
        ORDER BY s.has_product DESC, s.quality DESC, s.id ASC
        """,
        (int(workspace_id),),
    )
    by_id: dict[int, float] = {
        int(r["id"]): max(1.0, float(r.get("end_s") or 2.0) - float(r.get("start_s") or 0.0))
        for r in rows
    }
    chosen_ids: list[int] = []
    if product_id:
        for r in rows:
            pids = [int(x) for x in loads_or(r.get("product_ids_json"), []) if str(x).isdigit()]
            if product_id in pids:
                chosen_ids.append(int(r["id"]))
    if not chosen_ids:
        chosen_ids = [int(r["id"]) for r in rows]

    if not chosen_ids:
        if policy != "full_ai":
            raise PermissionError(
                f"Workspace '{policy}' thiếu footage shot thật để dựng video."
            )
        ai_sid = ensure_full_ai_canvas_shot(paths, workspace_id, aspect_ratio)
        chosen_ids = [ai_sid]
        by_id[ai_sid] = 5.4

    primary = chosen_ids[0]
    secondary = chosen_ids[1] if len(chosen_ids) > 1 else chosen_ids[0]
    if len(chosen_ids) == 1 and by_id.get(primary, 0.0) >= 5.2:
        d1 = 2.6
        d2 = 2.6
    else:
        d1 = round(min(2.6, max(1.6, by_id.get(primary, 2.0))), 2)
        d2 = round(min(2.6, max(1.6, by_id.get(secondary, 2.0))), 2)
    return [
        {"shot_id": primary, "duration_s": d1},
        {"shot_id": secondary, "duration_s": d2},
    ]


def _fit_line(text: str, lang: str, duration_s: float) -> str:
    budget = max(3, max_syllables_for_duration(duration_s, lang))
    words = " ".join((text or "").split()).split()
    kept: list[str] = []
    for w in words:
        cand = " ".join([*kept, w])
        if count_syllables(cand, lang) > budget and kept:
            break
        kept.append(w)
    return " ".join(kept) or (text[:20] if text else "Video")


def build_ab_lines(
    *,
    subject: str,
    detail: str,
    hook_angle: str,
    lang: str,
) -> tuple[str, str]:
    is_vi = lang.strip().lower().startswith("vi")
    if hook_angle == "curiosity_problem":
        line1 = f"Vì sao {subject} luôn nổi bật?" if is_vi else f"Why {subject} stands out?"
    elif hook_angle == "direct_proof":
        line1 = f"Cận cảnh {subject} chuẩn nét" if is_vi else f"Close-up look at {subject}"
    else:
        line1 = f"Đừng bỏ lỡ {subject} hôm nay" if is_vi else f"Don't miss {subject} today"

    line2 = detail or (f"Xem chi tiết {subject} ngay" if is_vi else f"Explore {subject} details")
    return _fit_line(line1, lang, 1.4), _fit_line(line2, lang, 1.4)


def plan_batch_item(
    paths: AppPaths,
    run_row: dict[str, Any],
    item_row: dict[str, Any],
    *,
    forced_shot_ids: list[int] | None = None,
) -> int:
    ws_id = int(run_row["workspace_id"])
    ws = require_workspace(paths.db_file, ws_id)
    policy = str(ws.get("content_policy") or "strict_footage")
    ref = loads_or(item_row.get("source_ref_json"), {})
    source_kind = str(run_row["source_kind"])
    aspect_ratio = str(run_row.get("aspect_ratio") or "9:16")
    t_lang = str(run_row.get("target_lang") or "vi")
    legacy_lang = "vi" if t_lang.strip().lower().startswith("vi") else "en"
    hook_angle = str(item_row.get("hook_angle") or "curiosity_problem")

    product_ids: list[int] = []
    suggestion_id: int | None = None
    subject = "Video"
    detail = ""
    if source_kind == "products":
        pid = int(ref.get("product_id") or 0)
        prod = query_one(paths.db_file, "SELECT * FROM products WHERE id = ?", (pid,))
        if prod is None:
            raise ValueError(f"Product #{pid} not found")
        product_ids = [pid]
        subject = str(prod["name"])
        mat = str(prod.get("material") or "").strip()
        facts = loads_or(prod.get("facts_json"), {})
        detail = f"{mat} {' '.join(str(v) for v in list(facts.values())[:2])}".strip()
    elif source_kind == "trends":
        tid = int(ref.get("trend_id") or 0)
        tr = query_one(paths.db_file, "SELECT * FROM trend_items WHERE id = ?", (tid,))
        if tr is None:
            raise ValueError(f"Trend #{tid} not found")
        subject = str(tr.get("caption") or f"Trend #{tid}")[:40]
        detail = str(tr.get("author") or "Xu hướng nổi bật")
    else:
        prompt = str(ref.get("prompt") or run_row["title"]).strip()
        subject = prompt[:42]
        detail = prompt

    if forced_shot_ids:
        s0 = int(forced_shot_ids[0])
        s1 = int(forced_shot_ids[1]) if len(forced_shot_ids) > 1 else s0
        shots = [
            {"shot_id": s0, "duration_s": 2.6},
            {"shot_id": s1, "duration_s": 2.6},
        ]
    else:
        shots = pick_shots_for_batch_item(
            paths,
            ws_id,
            product_ids[0] if product_ids else None,
            aspect_ratio,
            policy,
        )
    l1, l2 = build_ab_lines(subject=subject, detail=detail, hook_angle=hook_angle, lang=t_lang)
    shots[0]["text"] = l1
    shots[1]["text"] = l2

    plan_payload = {
        "batch_id": int(run_row["id"]),
        "variant": item_row["variant_label"],
        "hook_angle": hook_angle,
        "shots": shots,
        "caption_vi": f"{l1}. {l2}".strip(),
        "caption_en": f"{l1}. {l2}".strip(),
    }

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO videos (
                workspace_id, product_ids_json, engine, status, plan_json,
                voice_lang, caption_lang, target_lang, target_accounts_json,
                style_preset, aspect_ratio, suggestion_id, auto_render
            )
            VALUES (?, ?, 'ffmpeg', 'planned', ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                ws_id,
                json.dumps(product_ids),
                json.dumps(plan_payload, ensure_ascii=False),
                legacy_lang,
                legacy_lang,
                t_lang,
                str(run_row.get("target_accounts_json") or "[]"),
                str(item_row["style_preset"]),
                aspect_ratio,
                suggestion_id,
            ),
        )
        video_id = int(cur.lastrowid)
        conn.execute(
            """
            UPDATE batch_items
            SET video_id = ?, step = 'planned', error = NULL,
                updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
            WHERE id = ?
            """,
            (video_id, int(item_row["id"])),
        )
    return video_id


__all__ = [
    "HOOK_ANGLES",
    "VALID_SOURCE_KINDS",
    "build_ab_lines",
    "pick_shots_for_batch_item",
    "plan_batch_item",
]
