"""Validation of AI-written plans: shot bounds, B-roll rules, product consistency, caption limits."""
from __future__ import annotations

from typing import Any, Literal

from videocreator.pipeline.caption_limits import CAPTION_PLATFORMS, clean_caption
from videocreator.pipeline.plan_schema import PlannedShot, PlatformCaption, PlatformCaptions, VideoPlanItem


def jaccard_similarity(set_a: set[int], set_b: set[int]) -> float:
    """Computes Jaccard similarity `|A ∩ B| / |A ∪ B|` between two shot ID sets."""
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    if not union:
        return 0.0
    return len(set_a & set_b) / len(union)


def sanitize_captions(captions: PlatformCaptions) -> dict[str, dict[str, Any]]:
    """Enforces per-platform character and hashtag limits (`BR-CAP-01`)."""
    out: dict[str, dict[str, Any]] = {}
    for platform in CAPTION_PLATFORMS:
        cap: PlatformCaption = getattr(captions, platform)
        out[platform] = clean_caption(platform, cap.text, cap.hashtags)
    return out


def _is_broll_shot(db_shot: dict[str, Any]) -> bool:
    tags = [str(t).lower() for t in (db_shot.get("tags") or [])]
    if "ai_broll" in tags or "stock_broll" in tags:
        return True
    if db_shot.get("asset_id") and not db_shot.get("footage_id"):
        return True
    return False


def _check_broll_rules(db_shot: dict[str, Any], shot_id: int, *, is_opening: bool, broll_count: int) -> None:
    """`BR-PRD-07..08` for one B-roll shot; `broll_count` already includes it."""
    if int(db_shot.get("has_product") or 0) == 1:
        raise ValueError(
            f"BR-PRD-07 violation: AI/stock B-roll shot #{shot_id} cannot have has_product=1"
        )
    if is_opening:
        raise ValueError(
            f"BR-PRD-08 violation: B-roll shot #{shot_id} cannot be placed at the opening hook position (index 0)"
        )
    if broll_count > 2:
        raise ValueError(
            f"BR-PRD-08 violation: Plan contains {broll_count} B-roll shots (maximum allowed is 2 per video)"
        )


def _clamp_to_shot(db_shot: dict[str, Any], planned: PlannedShot) -> tuple[float, float]:
    """Keeps `(start_s, duration_s)` inside the shot; a window that is too short becomes the whole shot."""
    shot_start = float(db_shot["start_s"])
    shot_end = float(db_shot["end_s"])

    start_s = float(planned.start_s)
    if start_s < shot_start - 0.05 or start_s >= shot_end:
        start_s = shot_start
    else:
        start_s = max(shot_start, start_s)

    duration_s = min(float(planned.duration_s), round(shot_end - start_s, 3))
    if duration_s < 0.7:
        duration_s = round(shot_end - shot_start, 3)
        start_s = shot_start
    if duration_s < 0.65:
        raise ValueError(f"Shot #{planned.shot_id} duration {duration_s}s is too short (<0.7s)")
    return start_s, duration_s


def _check_subtitle_products(
    text: str, shot_id: int, shot_product_ids: set[int], product_map: dict[int, dict[str, Any]]
) -> None:
    """`BR-PRD-05`: the subtitle must not name a product that is absent from this shot."""
    text_lower = text.strip().lower()
    if not shot_product_ids or not text_lower:
        return
    for other_id, other_product in product_map.items():
        if other_id in shot_product_ids:
            continue
        other_name = str(other_product.get("name") or "").strip().lower()
        if len(other_name) >= 4 and other_name in text_lower:
            raise ValueError(
                f"BR-PRD-05 violation: subtitle mentions product '{other_product['name']}' "
                f"on shot #{shot_id} which only contains products {sorted(shot_product_ids)}"
            )


def _check_products_not_mixed(formula: str, shot_product_sets: list[set[int]]) -> None:
    """`BR-PRD-05`: non-collection formulas must not mix shots of disjoint products."""
    is_collection = "collection" in formula.lower() or "suu-tap" in formula.lower()
    if is_collection or len(shot_product_sets) < 2:
        return
    first_set = shot_product_sets[0]
    for other_set in shot_product_sets[1:]:
        if not (first_set & other_set):
            raise ValueError(
                f"BR-PRD-05 violation: non-collection formula '{formula}' mixes disjoint products "
                f"{sorted(first_set)} and {sorted(other_set)}"
            )


def validate_and_normalize_plan(
    item: VideoPlanItem,
    *,
    shot_map: dict[int, dict[str, Any]],
    product_map: dict[int, dict[str, Any]],
    voice_lang: Literal["none", "vi", "en"],
    caption_lang: Literal["vi", "en"],
    target_duration_s: float,
    allow_broll_hook: bool = False,
) -> dict[str, Any]:
    """Validates `shot_id` existence, clamps/checks time bounds, B-roll rules (`BR-PRD-07..08`), and product-shot consistency (`BR-PRD-05`)."""
    if not item.shots:
        raise ValueError("Plan contains no shots")

    normalized_shots: list[dict[str, Any]] = []
    plan_product_ids: set[int] = set()
    shot_product_sets: list[set[int]] = []
    broll_count = 0

    for shot_idx, planned in enumerate(item.shots):
        shot_id = int(planned.shot_id)
        db_shot = shot_map.get(shot_id)
        if db_shot is None:
            raise ValueError(f"Hallucinated or unknown shot_id={planned.shot_id} (FR-PLN-03)")

        if _is_broll_shot(db_shot):
            broll_count += 1
            _check_broll_rules(
                db_shot,
                shot_id,
                is_opening=shot_idx == 0 and not allow_broll_hook,
                broll_count=broll_count,
            )

        start_s, duration_s = _clamp_to_shot(db_shot, planned)

        shot_product_ids = set(db_shot.get("product_ids") or [])
        plan_product_ids.update(shot_product_ids)
        if shot_product_ids:
            shot_product_sets.append(shot_product_ids)
        _check_subtitle_products(planned.text, shot_id, shot_product_ids, product_map)

        normalized_shots.append(
            {
                "shot_id": shot_id,
                "start_s": round(start_s, 3),
                "duration_s": round(duration_s, 3),
                "text": planned.text.strip(),
            }
        )

    _check_products_not_mixed(item.formula, shot_product_sets)

    total_dur = round(sum(s["duration_s"] for s in normalized_shots), 2)
    if total_dur < 2.0 or total_dur > max(45.0, target_duration_s * 2.0):
        raise ValueError(f"Total plan duration {total_dur}s out of bounds for target {target_duration_s}s")

    return {
        "formula": item.formula.strip() or "hook-first",
        "title": item.title.strip() or "Video trang sức bạc",
        "voice_lang": voice_lang,
        "caption_lang": caption_lang,
        "product_ids": sorted(plan_product_ids),
        "total_duration_s": total_dur,
        "shots": normalized_shots,
        "captions": sanitize_captions(item.captions),
        "unverified_claims": [],
    }
