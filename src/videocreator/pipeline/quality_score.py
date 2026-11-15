"""Automatic quality score of a rendered video and the redo it may trigger (`FR-APR-05`)."""
from __future__ import annotations

from pydantic import BaseModel, Field

from videocreator.ai import get_provider
from videocreator.ai.base import AIProvider
from videocreator.config import load_settings
from videocreator.db import get_conn, query_one, record_audit
from videocreator.paths import AppPaths
from videocreator.redo import redo_video
from videocreator.state import transition


class VideoQualityScore(BaseModel):
    hook_score: float = Field(ge=1.0, le=10.0, description="Điểm 3 giây đầu (1-10)")
    product_clarity_score: float = Field(ge=1.0, le=10.0, description="Độ rõ nét sản phẩm thật (1-10)")
    safe_zone_score: float = Field(ge=1.0, le=10.0, description="Phụ đề nằm gọn trong vùng an toàn (1-10)")
    audio_sync_score: float = Field(ge=1.0, le=10.0, description="Độ khớp nhịp hình và chữ/lời (1-10)")
    overall_score: float = Field(ge=1.0, le=10.0, description="Điểm tổng kết (1-10)")
    notes: str = Field(description="Nhận xét ngắn gọn tiếng Việt (1-2 câu)")


def score_rendered_video(
    paths: AppPaths,
    video_id: int,
    *,
    provider: AIProvider | None = None,
    score_override: float | None = None,
    notes_override: str | None = None,
) -> tuple[str, int, float]:
    """Evaluates a rendered video on a 10-point rubric (`FR-APR-05`).

    If `score < quality.min_score` (default 8.0) and `auto_retry_count < quality.max_retries` (default 2),
    creates a new video via `redo_video(..., is_auto_retry=True)` and marks `video_id` as `superseded`.
    Otherwise ensures `video_id` is in `pending_approval` with `quality_score` and `quality_notes` saved.

    Returns `(final_status, active_video_id, score)`.
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
        score = float(score_override)
        notes = str(notes_override or "Chấm điểm tự động")
    else:
        out_rel = str(row.get("output_path") or "")
        video_file = paths.media_dir / out_rel if out_rel else None
        plan_str = str(row.get("plan_json") or "{}")
        vis = provider or get_provider(paths, "vision")
        prompt = (
            "Hãy chấm điểm chất lượng video ngắn 9:16 trang sức bạc thủ công này theo thang 10:\n"
            "1. Mở đầu (hook) 2-3 giây đầu có thu hút không?\n"
            "2. Sản phẩm bạc thật có rõ nét, không bị cắt lẹm không?\n"
            "3. Phụ đề/chữ có nằm trong vùng an toàn không?\n"
            "4. Nhịp hình và kịch bản có khớp nhau không?\n"
            f"Kịch bản JSON: {plan_str[:1200]}"
        )
        res = vis.describe_video(
            video_file if (video_file and video_file.exists()) else paths.media_dir,
            prompt,
            VideoQualityScore,
        )
        score = round(float(res.overall_score), 2)
        notes = res.notes.strip()

    existing_notes = str(row.get("quality_notes") or "").strip()
    if existing_notes and notes and existing_notes not in notes:
        combined_notes = f"{existing_notes} | {notes}"
    else:
        combined_notes = notes or existing_notes

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE videos SET quality_score = ?, quality_notes = ? WHERE id = ?",
            (score, combined_notes, video_id),
        )
        record_audit(
            conn,
            actor="auto_quality",
            action="video.scored",
            object_type="video",
            object_id=video_id,
            detail=f"score={score:.1f}/10, notes={combined_notes[:120]}",
        )

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

    if cur_status == "scoring":
        transition(
            paths.db_file,
            video_id,
            "pending_approval",
            expected_from="scoring",
            actor="auto_quality",
        )
    return "pending_approval", video_id, score
