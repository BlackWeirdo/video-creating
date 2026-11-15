"""Automatic quality score of a rendered video and the redo it may trigger (`FR-APR-05`).

The vision model sees the hook frames plus one frame per shot (or the whole video for a video
model), answers per criterion with evidence first, and the overall score is computed here. A
video that could not really be judged is never redone automatically, and when the redo budget is
used up the best-scored attempt of the chain goes to approval, not the last one.
"""
from __future__ import annotations

import logging
import shutil
from statistics import mean
from typing import Any

from pydantic import BaseModel, Field

from videocreator.ai import get_provider
from videocreator.ai.base import AIProvider, BudgetExceeded
from videocreator.config import load_settings
from videocreator.db import get_conn, query_one, record_audit
from videocreator.jobs import QuotaWaitRequested
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.probe import probe_video
from videocreator.pipeline.quality_frames import extract_score_frames, frame_times
from videocreator.redo import redo_video
from videocreator.state import transition

logger = logging.getLogger("videocreator.pipeline.quality")

MIN_FRAMES = 3
UNJUDGED_PREFIX = "Chưa chấm được"


class CriterionScore(BaseModel):
    evidence: str = Field(description="Thời điểm (giây) và điều nhìn thấy trong ảnh làm căn cứ, viết trước khi cho điểm")
    score: int = Field(ge=1, le=10, description="Điểm 1-10 theo thang mốc trong đề bài")


class VideoQualityScore(BaseModel):
    can_judge: bool = Field(description="false nếu ảnh/video không đủ để chấm (đen, mờ, thiếu)")
    cannot_judge_reason: str = Field(default="", description="Lý do khi can_judge = false")
    hook: CriterionScore
    product_clarity: CriterionScore
    text_safe_zone: CriterionScore
    pacing_sync: CriterionScore
    notes: str = Field(description="Nhận xét ngắn gọn tiếng Việt (1-2 câu)")


CRITERIA: tuple[tuple[str, str], ...] = (
    ("hook", "Mở đầu"),
    ("product_clarity", "Độ rõ sản phẩm"),
    ("text_safe_zone", "Chữ trong vùng an toàn"),
    ("pacing_sync", "Khớp hình và lời"),
)

RUBRIC = (
    "Thang điểm có mốc cho từng tiêu chí:\n"
    "1. Mở đầu (ảnh 0.3s, 1.3s, 2.3s): 2 = không thấy sản phẩm, hình tối/mờ; 5 = có sản phẩm nhưng xa hoặc chậm; "
    "8 = sản phẩm rõ ngay trong 2 giây đầu; 10 = sản phẩm rõ và có chuyển động hoặc chữ gây tò mò ngay ảnh đầu.\n"
    "2. Độ rõ sản phẩm: 2 = mờ, cháy sáng, bị cắt mất; 5 = thấy được nhưng nhỏ hoặc nhiễu; "
    "8 = nét, đủ khung, thấy chi tiết chế tác; 10 = nét, ánh bạc thật, chi tiết rõ ở mọi cảnh có sản phẩm.\n"
    "3. Chữ trong vùng an toàn (không chạm 15% trên, 25% dưới, 12% mép phải): 2 = chữ bị che/cắt; "
    "5 = sát mép; 8 = gọn trong vùng an toàn; 10 = gọn và dễ đọc. Không có chữ thì cho 8.\n"
    "4. Khớp hình và lời: 2 = lời nói về thứ không có trong hình; 5 = khớp một phần; 8 = lời khớp cảnh; "
    "10 = lời và nhịp cảnh khớp hoàn toàn.\n"
    "Với mỗi tiêu chí, ghi `evidence` (giây + điều thấy được) TRƯỚC rồi mới cho `score`. "
    "Nếu ảnh/video không đủ để chấm thì đặt can_judge = false và ghi lý do."
)


def overall_from(res: VideoQualityScore) -> float:
    """Overall score computed from the four criteria (the model's own total is not trusted)."""
    return round(mean(getattr(res, key).score for key, _ in CRITERIA), 2)


def weakest_hint(res: VideoQualityScore) -> str:
    """The lowest criterion with its evidence, e.g. "Mở đầu 5/10: 0-2s chưa thấy sản phẩm"."""
    key, label = min(CRITERIA, key=lambda kv: getattr(res, kv[0]).score)
    crit: CriterionScore = getattr(res, key)
    return f"{label} {crit.score}/10: {crit.evidence.strip()[:200]}"


def _shot_summary(plan: dict[str, Any]) -> str:
    lines, cursor = [], 0.0
    for shot in plan.get("shots") or []:
        dur = float(shot.get("duration_s") or 0.0)
        lines.append(f"- {cursor:.1f}-{cursor + dur:.1f}s: {str(shot.get('text') or '').strip()[:120]}")
        cursor += dur
    return "\n".join(lines) or "- (không có lời)"


def build_score_prompt(plan: dict[str, Any], times: list[float]) -> str:
    frame_list = "\n".join(
        f"Ảnh {i} = {t:.1f}s" + (" (mở đầu)" if t < 3.0 else "") for i, t in enumerate(times, start=1)
    )
    return (
        "Hãy chấm điểm video ngắn 9:16 trang sức bạc thủ công theo 4 tiêu chí.\n"
        f"Các ảnh trích từ video theo thứ tự thời gian:\n{frame_list}\n"
        f"Lời/phụ đề theo kịch bản:\n{_shot_summary(plan)}\n\n{RUBRIC}"
    )


def _save_score(paths: AppPaths, video_id: int, row: dict[str, Any], score: float | None, notes: str) -> None:
    existing = str(row.get("quality_notes") or "").strip()
    combined = f"{existing} | {notes}" if existing and notes and existing not in notes else (notes or existing)
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE videos SET quality_score = ?, quality_notes = ? WHERE id = ?",
            (score, combined, video_id),
        )
        record_audit(
            conn,
            actor="auto_quality",
            action="video.scored",
            object_type="video",
            object_id=video_id,
            detail=f"score={'-' if score is None else f'{score:.1f}/10'}, notes={combined[:120]}",
        )


def _to_pending(paths: AppPaths, video_id: int, cur_status: str) -> None:
    if cur_status == "scoring":
        transition(paths.db_file, video_id, "pending_approval", expected_from="scoring", actor="auto_quality")


_CHAIN_SQL = (
    "SELECT id, status, quality_score, output_path, supersedes_id, auto_retry_count, redo_count "
    "FROM videos WHERE id = ?"
)


def best_in_chain(paths: AppPaths, video_id: int) -> int:
    """The highest-scored attempt among `video_id` and the attempts automatic scoring replaced
    before it, whose master file still exists; `video_id` itself on a tie.

    The walk back stops at an attempt a person redid ("Làm lại"): what a reviewer turned down
    is never sent back to approval."""
    best_id, best_score = video_id, None
    row = query_one(paths.db_file, _CHAIN_SQL, (video_id,))
    seen: set[int] = set()
    while row is not None and int(row["id"]) not in seen:
        seen.add(int(row["id"]))
        usable = (
            row.get("quality_score") is not None
            and row.get("output_path")
            and (paths.media_dir / str(row["output_path"])).exists()
            and (int(row["id"]) == video_id or str(row["status"]) == "superseded")
        )
        if usable and (best_score is None or float(row["quality_score"]) > best_score):
            best_id, best_score = int(row["id"]), float(row["quality_score"])
        if not row.get("supersedes_id"):
            break
        parent = query_one(paths.db_file, _CHAIN_SQL, (int(row["supersedes_id"]),))
        # `redo_video` raises auto_retry_count for an automatic redo and redo_count for a human one
        auto_redo = parent is not None and (
            int(row.get("auto_retry_count") or 0) > int(parent.get("auto_retry_count") or 0)
            and int(row.get("redo_count") or 0) == int(parent.get("redo_count") or 0)
        )
        row = parent if auto_redo else None
    return best_id


def promote_best_attempt(paths: AppPaths, current_id: int, best_id: int) -> bool:
    """Sends the better earlier attempt to approval instead of the current one. Returns False
    (and changes nothing) when the current attempt was already moved on by someone else."""
    with get_conn(paths.db_file) as conn:
        if not transition(conn, current_id, "superseded", expected_from="scoring", actor="auto_quality"):
            return False
        if not transition(conn, best_id, "pending_approval", expected_from="superseded", actor="auto_quality"):
            raise RuntimeError(f"Video #{best_id} could not be restored for approval")  # rolls back both
        record_audit(
            conn,
            actor="auto_quality",
            action="video.best_attempt_restored",
            object_type="video",
            object_id=best_id,
            detail=f"kept over #{current_id}",
        )
    return True


def _judge(
    paths: AppPaths, video_id: int, row: dict[str, Any], provider: AIProvider | None
) -> tuple[float | None, str, str]:
    """Returns `(score, notes, fix_hint)`; `score` is None when the video could not really be judged."""
    out_rel = str(row.get("output_path") or "")
    video_file = paths.media_dir / out_rel if out_rel else None
    if video_file is None or not video_file.is_file():
        return None, f"{UNJUDGED_PREFIX}: không tìm thấy file video", ""
    plan = loads_or(row.get("plan_json"), {})
    work_dir = paths.work_dir / f"score_{video_id}"
    try:
        frames = extract_score_frames(video_file, frame_times(plan, probe_video(video_file).duration_s), work_dir)
        if len(frames) < MIN_FRAMES:
            return None, f"{UNJUDGED_PREFIX}: chỉ trích được {len(frames)} khung hình", ""
        vis = provider or get_provider(paths, "vision")
        try:
            res = vis.describe_video(
                video_file,
                build_score_prompt(plan, [t for t, _ in frames]),
                VideoQualityScore,
                thumbnails=[p for _, p in frames],
            )
        except (QuotaWaitRequested, BudgetExceeded) as exc:
            # Out of quota or budget: the render is kept and goes to approval unscored, never redone.
            return None, f"{UNJUDGED_PREFIX}: hết hạn mức AI ({str(exc)[:120]})", ""
        except Exception as exc:
            logger.warning("Quality scoring of video #%d failed: %s", video_id, exc)
            return None, f"{UNJUDGED_PREFIX}: {str(exc)[:160]}", ""
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    if not res.can_judge:
        return None, f"{UNJUDGED_PREFIX}: {res.cannot_judge_reason.strip()[:160] or 'mô hình không chấm được'}", ""
    hint = weakest_hint(res)
    return overall_from(res), f"{hint} | {res.notes.strip()}", hint


def score_rendered_video(
    paths: AppPaths,
    video_id: int,
    *,
    provider: AIProvider | None = None,
    score_override: float | None = None,
    notes_override: str | None = None,
) -> tuple[str, int, float | None]:
    """Scores a rendered video on a 10-point rubric (`FR-APR-05`).

    - Below `quality.min_score` with auto retries left: `redo_video(..., is_auto_retry=True)`,
      the video becomes `superseded` and a new script is written using the weakest criterion.
    - Not judged (no file, too few frames, provider error, model says it cannot judge): no redo;
      it goes to approval with `quality_score` NULL and the reason in the notes.
    - Otherwise the best-scored attempt of the redo chain goes to `pending_approval`.

    Returns `(final_status_of_video_id, video_id_now_waiting_or_replacing, score)`.
    """
    row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if row is None:
        raise LookupError(f"Video #{video_id} not found")

    cur_status = str(row["status"])
    if cur_status == "rendered":
        transition(paths.db_file, video_id, "scoring", expected_from="rendered", actor="auto_quality")
        cur_status = "scoring"

    settings = load_settings(paths.config_file)
    if score_override is not None:
        score: float | None = float(score_override)
        notes = str(notes_override or "Chấm điểm tự động")
    else:
        score, notes, _hint = _judge(paths, video_id, row, provider)

    _save_score(paths, video_id, row, score, notes)
    if score is None:
        _to_pending(paths, video_id, cur_status)
        return "pending_approval", video_id, None

    auto_retries = int(row.get("auto_retry_count") or 0)
    if score < settings.quality.min_score and auto_retries < settings.quality.max_retries:
        new_vid = redo_video(
            paths.db_file,
            video_id,
            by="auto_quality",
            is_auto_retry=True,
            max_retries=settings.quality.max_retries,
        )
        if new_vid is not None:
            return "superseded", new_vid, score

    best_id = best_in_chain(paths, video_id) if cur_status == "scoring" else video_id
    if best_id != video_id and promote_best_attempt(paths, video_id, best_id):
        return "superseded", best_id, score
    _to_pending(paths, video_id, cur_status)
    return "pending_approval", video_id, score
