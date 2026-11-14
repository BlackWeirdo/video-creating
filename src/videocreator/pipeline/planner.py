"""Remix script planner, product fact-checking, and Jaccard deduplication (Phase 04)."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from videocreator.ai import AIProvider, get_provider
from videocreator.api.routes_products import list_products
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.paths import AppPaths

logger = logging.getLogger("videocreator.pipeline.planner")

DEFAULT_FORMULAS: tuple[str, ...] = (
    "hook-first",
    "craft-process",
    "detail-closeup",
    "story-emotion",
    "collection",
)

PLATFORM_CHAR_LIMITS: dict[str, int] = {
    "facebook": 2200,
    "instagram": 2200,
    "threads": 500,
    "tiktok": 2200,
}

PLATFORM_HASHTAG_LIMITS: dict[str, int] = {
    "facebook": 5,
    "instagram": 8,
    "threads": 1,
    "tiktok": 6,
}


class PlatformCaption(BaseModel):
    text: str = Field(description="Nội dung caption cho nền tảng này")
    hashtags: list[str] = Field(description="Danh sách hashtag (không vượt giới hạn nền tảng)")


class PlatformCaptions(BaseModel):
    facebook: PlatformCaption
    instagram: PlatformCaption
    threads: PlatformCaption
    tiktok: PlatformCaption


class PlannedShot(BaseModel):
    shot_id: int = Field(description="ID của shot có thật trong danh sách được cung cấp")
    start_s: float = Field(description="Mốc bắt đầu trong footage gốc (giây)")
    duration_s: float = Field(description="Thời lượng lấy của shot (giây, >= 0.7)")
    text: str = Field(description="Dòng phụ đề/lời thoại ngắn cho shot này")


class VideoPlanItem(BaseModel):
    formula: str = Field(description="Tên công thức dựng (VD: hook-first, craft-process, detail-closeup)")
    title: str = Field(description="Tiêu đề ngắn gọn của kịch bản")
    shots: list[PlannedShot] = Field(description="Danh sách các shot theo thứ tự xuất hiện")
    captions: PlatformCaptions = Field(description="4 bộ caption riêng cho Facebook, Instagram, Threads, TikTok")


class RemixPlansBatch(BaseModel):
    plans: list[VideoPlanItem]


class FactCheckResult(BaseModel):
    unverified_claims: list[str] = Field(
        description="Danh sách nguyên văn các câu/cụm từ trong lời thoại hoặc caption tự bịa thông số không có trong facts_json; rỗng nếu hoàn toàn hợp lệ"
    )


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
    for platform in ("facebook", "instagram", "threads", "tiktok"):
        cap: PlatformCaption = getattr(captions, platform)
        max_chars = PLATFORM_CHAR_LIMITS[platform]
        max_tags = PLATFORM_HASHTAG_LIMITS[platform]
        clean_text = cap.text.strip()[:max_chars]
        clean_tags: list[str] = []
        for t in cap.hashtags:
            tag = t.strip()
            if not tag:
                continue
            if not tag.startswith("#"):
                tag = f"#{tag}"
            clean_tags.append(tag)
            if len(clean_tags) >= max_tags:
                break
        out[platform] = {"text": clean_text, "hashtags": clean_tags}
    return out


def _is_broll_shot(db_shot: dict[str, Any]) -> bool:
    tags = [str(t).lower() for t in (db_shot.get("tags") or [])]
    if "ai_broll" in tags or "stock_broll" in tags:
        return True
    if db_shot.get("asset_id") and not db_shot.get("footage_id"):
        return True
    return False


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

    for shot_idx, ps in enumerate(item.shots):
        db_shot = shot_map.get(int(ps.shot_id))
        if db_shot is None:
            raise ValueError(f"Hallucinated or unknown shot_id={ps.shot_id} (FR-PLN-03)")

        is_broll = _is_broll_shot(db_shot)
        if is_broll:
            if int(db_shot.get("has_product") or 0) == 1:
                raise ValueError(
                    f"BR-PRD-07 violation: AI/stock B-roll shot #{ps.shot_id} cannot have has_product=1"
                )
            if shot_idx == 0 and not allow_broll_hook:
                raise ValueError(
                    f"BR-PRD-08 violation: B-roll shot #{ps.shot_id} cannot be placed at the opening hook position (index 0)"
                )
            broll_count += 1
            if broll_count > 2:
                raise ValueError(
                    f"BR-PRD-08 violation: Plan contains {broll_count} B-roll shots (maximum allowed is 2 per video)"
                )

        s_start = float(db_shot["start_s"])
        s_end = float(db_shot["end_s"])
        max_avail = round(s_end - s_start, 3)

        # Ensure start_s and duration_s stay within [s_start, s_end]
        req_start = float(ps.start_s)
        if req_start < s_start - 0.05 or req_start >= s_end:
            req_start = s_start
        else:
            req_start = max(s_start, req_start)

        rem_avail = round(s_end - req_start, 3)
        req_dur = min(float(ps.duration_s), rem_avail)
        if req_dur < 0.7:
            req_dur = max_avail
            req_start = s_start
        if req_dur < 0.65:
            raise ValueError(f"Shot #{ps.shot_id} duration {req_dur}s is too short (<0.7s)")

        shot_pids = set(db_shot.get("product_ids") or [])
        plan_product_ids.update(shot_pids)
        if shot_pids:
            shot_product_sets.append(shot_pids)

        # BR-PRD-05: Check that subtitle text does not explicitly name a different product absent from this shot
        text_lower = ps.text.strip().lower()
        if shot_pids and text_lower:
            for other_pid, other_prod in product_map.items():
                if other_pid not in shot_pids:
                    other_name = str(other_prod.get("name") or "").strip().lower()
                    if len(other_name) >= 4 and other_name in text_lower:
                        raise ValueError(
                            f"BR-PRD-05 violation: subtitle mentions product '{other_prod['name']}' "
                            f"on shot #{ps.shot_id} which only contains products {sorted(shot_pids)}"
                        )

        normalized_shots.append(
            {
                "shot_id": int(ps.shot_id),
                "start_s": round(req_start, 3),
                "duration_s": round(req_dur, 3),
                "text": ps.text.strip(),
            }
        )

    # BR-PRD-05: Non-collection formulas must not mix disjoint product shots
    is_collection = "collection" in item.formula.lower() or "suu-tap" in item.formula.lower()
    if not is_collection and len(shot_product_sets) >= 2:
        first_set = shot_product_sets[0]
        for other_set in shot_product_sets[1:]:
            if not (first_set & other_set):
                raise ValueError(
                    f"BR-PRD-05 violation: non-collection formula '{item.formula}' mixes disjoint products "
                    f"{sorted(first_set)} and {sorted(other_set)}"
                )

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


def check_plan_facts(
    paths: AppPaths,
    plan_dict: dict[str, Any],
    products_info: list[dict[str, Any]],
    *,
    checker_provider: AIProvider | None = None,
) -> list[str]:
    """Runs the `checker` AI role (`BR-PRD-06`) to flag any unverified product claims in subtitles/captions."""
    checker = checker_provider or get_provider(paths, "checker")
    facts_summary = []
    for p in products_info:
        facts_summary.append(
            {
                "id": p["id"],
                "name": p["name"],
                "material": p["material"],
                "facts": p["facts"],
            }
        )

    subtitles = [s["text"] for s in plan_dict.get("shots", []) if s.get("text")]
    captions_map = plan_dict.get("captions", {})

    prompt = (
        "Bạn là bộ kiểm chứng thông tin sản phẩm (Fact Checker) cho thương hiệu trang sức bạc thủ công.\n"
        f"Dữ liệu sự thật duy nhất của sản phẩm (facts_json): {json.dumps(facts_summary, ensure_ascii=False)}\n"
        f"Các dòng phụ đề trong kịch bản: {json.dumps(subtitles, ensure_ascii=False)}\n"
        f"4 bộ caption: {json.dumps(captions_map, ensure_ascii=False)}\n\n"
        "Luật kiểm tra (BR-PRD-04 & BR-PRD-06):\n"
        "- Mọi thông số cụ thể về chất liệu, tuổi bạc (VD: S925, S950, S999), loại đá, kích thước, trọng lượng, giá bán "
        "PHẢI khớp với dữ liệu sự thật ở trên.\n"
        "- Nếu dữ liệu sự thật trống hoặc không nêu thông số đó, lời và caption chỉ được nói về cảm xúc, ánh sáng, quy trình thủ công.\n"
        "- Hãy liệt kê nguyên văn các câu/cụm từ vi phạm (tự bịa thông số không có trong facts_json) vào `unverified_claims`. "
        "Nếu không có câu nào vi phạm, trả về mảng rỗng `[]`."
    )
    try:
        res = checker.generate_json(prompt, FactCheckResult)
        return [c.strip() for c in res.unverified_claims if c and c.strip()]
    except Exception as exc:
        logger.warning("Checker role failed (non-fatal): %s", exc)
        return []


def build_planner_prompt(
    *,
    shots: list[dict[str, Any]],
    products: list[dict[str, Any]],
    count: int,
    voice_lang: str,
    caption_lang: str,
    target_duration_s: float,
    formula: dict[str, Any] | str | None = None,
    preset_body: str | None = None,
) -> str:
    shot_lines = []
    for s in shots:
        dur = round(float(s["end_s"]) - float(s["start_s"]), 2)
        shot_lines.append(
            f"- shot_id={s['id']}: start_s={s['start_s']:.2f}, end_s={s['end_s']:.2f} "
            f"(tối đa {dur:.2f}s), products={s['product_ids']}, "
            f"mô tả='{s.get('description') or 'Cảnh quay trang sức'}', tags={s.get('tags', [])}"
        )

    prod_lines = []
    for p in products:
        prod_lines.append(
            f"- Sản phẩm #{p['id']} '{p['name']}': chất liệu='{p['material']}', "
            f"thông số={json.dumps(p['facts'], ensure_ascii=False)}"
        )

    formulas_str = ", ".join(DEFAULT_FORMULAS[: max(1, count)])
    lang_label = "Tiếng Việt" if caption_lang == "vi" else "Tiếng Anh (English)"
    voice_label = (
        "Không lồng tiếng (chỉ phụ đề ngắn trên hình)"
        if voice_lang == "none"
        else ("Tiếng Việt" if voice_lang == "vi" else "Tiếng Anh")
    )

    extra_blocks = ""
    if formula:
        f_str = json.dumps(formula, ensure_ascii=False) if isinstance(formula, dict) else str(formula)
        extra_blocks += f"\nCÔNG THỨC XU HƯỚNG ÁP DỤNG:\n{f_str}\n"
    if preset_body:
        extra_blocks += f"\nGÓI CHỈ DẪN THƯƠNG HIỆU (PRESET):\n{preset_body}\n"

    return (
        f"Hãy lập {count} kịch bản video ngắn 9:16 khác nhau cho thương hiệu trang sức bạc thủ công.\n"
        f"- Thời lượng mục tiêu mỗi kịch bản: khoảng {target_duration_s:.0f} giây.\n"
        f"- Ngôn ngữ phụ đề/lời thoại: {voice_label}.\n"
        f"- Ngôn ngữ 4 bộ caption (Facebook, Instagram, Threads, TikTok): {lang_label}.\n"
        f"- Mỗi kịch bản phải dùng một `formula` khác nhau (gợi ý: {formulas_str}) và chọn tập shot khác nhau "
        "(độ trùng lặp tập shot_id Jaccard <= 70%).\n"
        + extra_blocks
        + "\nDANH SÁCH SHOT CÓ THẬT (CHỈ ĐƯỢC CHỌN shot_id TRONG DANH SÁCH NÀY):\n"
        + "\n".join(shot_lines)
        + "\n\nNGUỒN SỰ THẬT SẢN PHẨM (facts_json):\n"
        + ("\n".join(prod_lines) if prod_lines else "- Không có thông số sản phẩm. Cấm tự bịa chất liệu/đá/kích thước/giá.")
        + "\n\nQUY TẮC BẮT BUỘC (BR-PRD-04..05, BR-CAP-01):\n"
        "1. Chỉ dùng `shot_id` có trong danh sách trên; `start_s` và `duration_s` phải nằm trong phạm vi của shot đó (`duration_s >= 0.7`).\n"
        "2. Tuyệt đối KHÔNG tự bịa tuổi bạc, loại đá, kích thước, trọng lượng, giá tiền hay công dụng nếu không có trong NGUỒN SỰ THẬT SẢN PHẨM.\n"
        "3. Mỗi kịch bản trả về đủ 4 caption riêng biệt: `facebook` (3-5 hashtag), `instagram` (3-8 hashtag), `threads` (<=500 ký tự, tối đa 1 hashtag), `tiktok` (3-6 hashtag)."
    )


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
    clean_ftg_id: int | None = None if use_library else int(footage_id)  # type: ignore[arg-type]

    if not use_library:
        footage = query_one(paths.db_file, "SELECT * FROM footage WHERE id = ?", (clean_ftg_id,))
        if footage is None:
            raise LookupError(f"Footage #{clean_ftg_id} not found")
        raw_shots = query_all(
            paths.db_file,
            "SELECT * FROM shots WHERE footage_id = ? ORDER BY idx ASC",
            (clean_ftg_id,),
        )
        if not raw_shots:
            raise ValueError(f"Footage #{clean_ftg_id} has no shots; run analyse first")
    else:
        raw_shots = query_all(
            paths.db_file,
            "SELECT * FROM shots ORDER BY quality DESC, id ASC",
        )
        if not raw_shots:
            raise ValueError("Kho shot hiện đang trống; hãy nạp và phân tích footage trước")

    all_products = list_products(paths.db_file, include_hidden=True)
    product_map = {p["id"]: p for p in all_products}

    shot_map: dict[int, dict[str, Any]] = {}
    enriched_shots: list[dict[str, Any]] = []
    referenced_pids: set[int] = set()
    for s in raw_shots:
        sid = int(s["id"])
        try:
            pids = [int(x) for x in json.loads(s.get("product_ids_json") or "[]")]
        except Exception:
            pids = []
        try:
            tags = [str(t) for t in json.loads(s.get("tags_json") or "[]")]
        except Exception:
            tags = []
        referenced_pids.update(pids)
        item = {**s, "product_ids": pids, "tags": tags}
        shot_map[sid] = item
        enriched_shots.append(item)

    linked_products = [product_map[pid] for pid in sorted(referenced_pids) if pid in product_map]

    # Load existing shot sets for this footage to enforce Jaccard <= 0.70 deduplication
    existing_sets: list[set[int]] = []
    existing_formulas: set[str] = set()
    existing_videos = query_all(
        paths.db_file,
        "SELECT plan_json FROM videos WHERE status != 'rejected' AND status != 'superseded'",
    )
    for ev in existing_videos:
        try:
            pjson = json.loads(ev.get("plan_json") or "{}")
            s_ids = {int(x["shot_id"]) for x in pjson.get("shots", []) if "shot_id" in x}
            if s_ids & set(shot_map.keys()):
                existing_sets.append(s_ids)
                if pjson.get("formula"):
                    existing_formulas.add(str(pjson["formula"]).lower())
        except Exception:
            continue

    writer = writer_provider or get_provider(paths, "writer")
    prompt = build_planner_prompt(
        shots=enriched_shots,
        products=linked_products,
        count=max(1, count),
        voice_lang=voice_lang,
        caption_lang=caption_lang,
        target_duration_s=target_duration_s,
        formula=formula,
        preset_body=preset_body,
    )
    batch = writer.generate_json(prompt, RemixPlansBatch)

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
            )
        except ValueError as val_err:
            logger.warning("Skipping invalid plan candidate: %s", val_err)
            continue

        candidate_set = {int(s["shot_id"]) for s in normalized["shots"]}
        if any(jaccard_similarity(candidate_set, prev) > 0.70 for prev in existing_sets):
            logger.info(
                "Skipping duplicate plan candidate (Jaccard > 0.70) for source=%s",
                clean_ftg_id or "library",
            )
            continue

        formula_key = normalized["formula"].lower()
        if formula_key in existing_formulas:
            normalized["formula"] = f"{normalized['formula']}-{len(existing_formulas) + 1}"
            formula_key = normalized["formula"].lower()

        unverified = check_plan_facts(
            paths,
            normalized,
            linked_products,
            checker_provider=checker_provider,
        )
        normalized["unverified_claims"] = unverified
        normalized["footage_id"] = clean_ftg_id
        normalized["source"] = "library" if use_library else "footage"

        with get_conn(paths.db_file) as conn:
            if replace_video_id is not None:
                conn.execute(
                    """
                    UPDATE videos
                    SET product_ids_json = ?, plan_json = ?, captions_json = ?, unsupported_claims_json = ?
                    WHERE id = ? AND status = 'planned'
                    """,
                    (
                        json.dumps(normalized["product_ids"]),
                        json.dumps(normalized, ensure_ascii=False),
                        json.dumps(normalized["captions"], ensure_ascii=False),
                        json.dumps(unverified, ensure_ascii=False),
                        replace_video_id,
                    ),
                )
                vid = int(replace_video_id)
            else:
                default_engine = "mpt" if voice_lang in ("vi", "en") else "ffmpeg"
                cur = conn.execute(
                    """
                    INSERT INTO videos (
                        footage_id, product_ids_json, engine, status, plan_json,
                        voice_lang, caption_lang, captions_json, unsupported_claims_json,
                        suggestion_id, auto_render
                    )
                    VALUES (?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        clean_ftg_id,
                        json.dumps(normalized["product_ids"]),
                        default_engine,
                        json.dumps(normalized, ensure_ascii=False),
                        voice_lang,
                        caption_lang,
                        json.dumps(normalized["captions"], ensure_ascii=False),
                        json.dumps(unverified, ensure_ascii=False),
                        suggestion_id,
                        1 if auto_render else 0,
                    ),
                )
                vid = int(cur.lastrowid or 0)
            created_video_ids.append(vid)
            existing_sets.append(candidate_set)
            existing_formulas.add(formula_key)
            record_audit(
                conn,
                actor="worker",
                action="video.planned",
                object_type="video",
                object_id=vid,
                detail=f"footage_id={clean_ftg_id}, formula={normalized['formula']}, unverified={len(unverified)}",
            )

        if auto_render:
            enqueue_job(paths.db_file, "render", ref_id=vid)

    if not created_video_ids:
        if len(enriched_shots) < 6 and existing_sets:
            raise ValueError(
                f"Kho shot có ít hơn 6 shot ({len(enriched_shots)} shots) nên không thể tạo thêm kịch bản mới không trùng lặp (BR-DIV-03)."
            )
        raise ValueError("Không có kịch bản hợp lệ nào được tạo từ phản hồi của AI.")

    return created_video_ids


def replan_video(
    paths: AppPaths,
    video_id: int,
    *,
    writer_provider: AIProvider | None = None,
    checker_provider: AIProvider | None = None,
) -> str:
    """Job handler for `replan` (redo, `FR-APR-05`, `FR-APR-06`): gives the replacement video a new
    script, then queues its render. If no different valid script comes out, the old one is rendered
    again and the reviewer is told so."""
    from videocreator.jobs import enqueue_job

    row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise LookupError(f"Video #{video_id} not found")
    if str(row["status"]) != "planned":
        return f"Video #{video_id} is '{row['status']}', nothing to replan"
    try:
        old_plan = json.loads(row.get("plan_json") or "{}")
    except ValueError:
        old_plan = {}
    formula: dict[str, Any] | None = None
    if row.get("suggestion_id"):
        s_row = query_one(paths.db_file, "SELECT formula_json FROM suggestions WHERE id = ?", (row["suggestion_id"],))
        try:
            formula = json.loads(str((s_row or {}).get("formula_json") or "null"))
        except ValueError:
            formula = None

    note = ""
    try:
        create_remix_plans(
            paths,
            row.get("footage_id"),
            voice_lang=str(row.get("voice_lang") or "none"),  # type: ignore[arg-type]
            caption_lang=str(row.get("caption_lang") or "vi"),  # type: ignore[arg-type]
            target_duration_s=float(old_plan.get("total_duration_s") or 15.0),
            formula=formula,
            suggestion_id=row.get("suggestion_id"),
            writer_provider=writer_provider,
            checker_provider=checker_provider,
            replace_video_id=video_id,
        )
    except (ValueError, LookupError) as exc:
        note = "Làm lại: không tạo được kịch bản khác, dựng lại kịch bản cũ"
        logger.warning("Replan of video #%d kept the old plan: %s", video_id, exc)
        with get_conn(paths.db_file) as conn:
            conn.execute("UPDATE videos SET quality_notes = ? WHERE id = ?", (note, video_id))
    enqueue_job(paths.db_file, "render", ref_id=video_id)
    return note or f"Replanned video #{video_id}"
