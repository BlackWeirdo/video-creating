"""Remix script planner, product fact-checking, and Jaccard deduplication (Phase 04)."""
from __future__ import annotations

import logging
from typing import Any, Literal

from videocreator.ai import AIProvider, get_provider
from videocreator.db import get_conn, record_audit
from videocreator.paths import AppPaths
from videocreator.pipeline.plan_prompts import build_planner_prompt, check_plan_facts
from videocreator.pipeline.plan_schema import RemixPlansBatch
from videocreator.pipeline.plan_store import (
    existing_plan_index,
    load_source_shots,
    save_plan,
    superseded_chain_index,
    with_parsed_lists,
)
from videocreator.pipeline.plan_validate import (
    is_collection_formula,
    jaccard_similarity,
    validate_and_normalize_plan,
)
from videocreator.products import list_products

logger = logging.getLogger("videocreator.pipeline.planner")


def create_remix_plans(
    paths: AppPaths,
    footage_id: int | None = None,
    *,
    count: int = 3,
    voice_lang: Literal["none", "vi", "en"] = "vi",
    caption_lang: Literal["vi", "en"] = "vi",
    target_duration_s: float = 15.0,
    formula: dict[str, Any] | str | None = None,
    suggestion_id: int | None = None,
    auto_render: bool = False,
    preset_body: str | None = None,
    writer_provider: AIProvider | None = None,
    checker_provider: AIProvider | None = None,
    replace_video_id: int | None = None,
    fix_hint: str | None = None,
) -> list[int]:
    """Generates `count` remix plans for `footage_id` (or the whole shot library when `footage_id` is None/0),
    validates, deduplicates via Jaccard, runs fact-checking (`BR-PRD-06`), and inserts rows into `videos`.

    With `replace_video_id` the single new plan is written into that existing `planned` row instead
    (used by "redo"); rendering is then queued by the caller."""
    if replace_video_id is not None:
        count = 1
        auto_render = False
    from videocreator.jobs import enqueue_job

    use_library = footage_id is None or int(footage_id) <= 0
    source_footage_id: int | None = None if use_library else int(footage_id)  # type: ignore[arg-type]

    formula_dict = formula if isinstance(formula, dict) else {}
    formula_name = str(formula_dict.get("formula") or (formula if isinstance(formula, str) else ""))
    shots = [
        with_parsed_lists(row)
        for row in load_source_shots(
            paths,
            source_footage_id,
            preferred_shot_ids=[int(i) for i in formula_dict.get("recommended_shot_ids") or [] if str(i).isdigit()],
            collection=is_collection_formula(formula_name),
        )
    ]
    shot_map: dict[int, dict[str, Any]] = {int(shot["id"]): shot for shot in shots}
    referenced_product_ids = {pid for shot in shots for pid in shot["product_ids"]}

    product_map = {p["id"]: p for p in list_products(paths.db_file, include_hidden=True)}
    linked_products = [product_map[pid] for pid in sorted(referenced_product_ids) if pid in product_map]

    # Existing shot sets enforce Jaccard <= 0.70 deduplication
    existing_sets, existing_formulas = existing_plan_index(
        paths.db_file, set(shot_map), exclude_video_id=replace_video_id
    )
    if replace_video_id is not None:
        anc_sets, anc_formulas = superseded_chain_index(paths.db_file, replace_video_id)
        existing_sets.extend(anc_sets)
        existing_formulas.update(anc_formulas)

    writer = writer_provider or get_provider(paths, "writer")
    prompt = build_planner_prompt(
        shots=shots,
        products=linked_products,
        count=max(1, count),
        voice_lang=voice_lang,
        caption_lang=caption_lang,
        target_duration_s=target_duration_s,
        formula=formula,
        preset_body=preset_body,
        fix_hint=fix_hint,
    )
    batch = writer.generate_json(prompt, RemixPlansBatch)

    trend_analysis = (
        formula_dict.get("trend_analysis")
        if isinstance(formula_dict.get("trend_analysis"), dict) and formula_dict.get("trend_analysis")
        else None
    )
    ref_cut_pace: float | None = None
    if trend_analysis and trend_analysis.get("cut_pace_s") is not None:
        try:
            ref_cut_pace = float(trend_analysis["cut_pace_s"])
        except (TypeError, ValueError):
            ref_cut_pace = None

    created_video_ids: list[int] = []
    for raw_plan in batch.plans:
        if len(created_video_ids) >= count:
            break
        try:
            normalized = validate_and_normalize_plan(
                raw_plan,
                shot_map=shot_map,
                product_map=product_map,
                voice_lang=voice_lang,
                caption_lang=caption_lang,
                target_duration_s=target_duration_s,
                reference_cut_pace_s=ref_cut_pace,
            )
        except ValueError as val_err:
            logger.warning("Skipping invalid plan candidate: %s", val_err)
            continue

        candidate_set = {int(s["shot_id"]) for s in normalized["shots"]}
        if any(jaccard_similarity(candidate_set, prev) > 0.70 for prev in existing_sets):
            logger.info(
                "Skipping duplicate plan candidate (Jaccard > 0.70) for source=%s",
                source_footage_id or "library",
            )
            continue

        if normalized["formula"].lower() in existing_formulas:
            normalized["formula"] = f"{normalized['formula']}-{len(existing_formulas) + 1}"

        unverified = check_plan_facts(
            paths,
            normalized,
            linked_products,
            checker_provider=checker_provider,
        )
        normalized["unverified_claims"] = unverified
        normalized["footage_id"] = source_footage_id
        normalized["source"] = "library" if use_library else "footage"
        if trend_analysis:
            normalized["trend_analysis"] = trend_analysis

        with get_conn(paths.db_file) as conn:
            video_id = save_plan(
                conn,
                normalized,
                replace_video_id=replace_video_id,
                suggestion_id=suggestion_id,
                auto_render=auto_render,
            )
            created_video_ids.append(video_id)
            existing_sets.append(candidate_set)
            existing_formulas.add(normalized["formula"].lower())
            record_audit(
                conn,
                actor="worker",
                action="video.planned",
                object_type="video",
                object_id=video_id,
                detail=f"footage_id={source_footage_id}, formula={normalized['formula']}, unverified={len(unverified)}",
            )

        if auto_render:
            enqueue_job(paths.db_file, "render", ref_id=video_id)

    if not created_video_ids:
        if len(shots) < 6 and existing_sets:
            raise ValueError(
                f"Kho shot có ít hơn 6 shot ({len(shots)} shots) nên không thể tạo thêm kịch bản mới không trùng lặp (BR-DIV-03)."
            )
        raise ValueError("Không có kịch bản hợp lệ nào được tạo từ phản hồi của AI.")

    return created_video_ids
