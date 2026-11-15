"""AI shot description job handler (`describe`) using the `vision` role (Phase 04)."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import BaseModel, Field

from videocreator.ai import AIProvider, get_provider
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.paths import AppPaths

logger = logging.getLogger("videocreator.pipeline.describe")


class ShotDescriptionItem(BaseModel):
    idx: int = Field(description="Số thứ tự shot bắt đầu từ 1")
    description: str = Field(description="Mô tả ngắn bằng tiếng Việt những gì thấy trong cảnh, không đoán chất liệu/giá")
    tags: list[str] = Field(description="Danh sách 2-5 nhãn ngắn tiếng Việt")
    has_product: bool = Field(description="Có thấy món trang sức trong khung hình hay không")
    quality: int = Field(ge=1, le=5, description="Điểm chất lượng khung hình từ 1 đến 5")


class ShotDescriptionsResponse(BaseModel):
    shots: list[ShotDescriptionItem]


def build_describe_prompt(shot_rows: list[dict[str, object]]) -> str:
    lines = [
        "Bạn đang xem các shot của một footage quay trang sức bạc thủ công.",
        "Danh sách các shot theo thứ tự:",
    ]
    for r in shot_rows:
        idx = int(r["idx"])  # type: ignore[arg-type]
        start_s = float(r["start_s"])  # type: ignore[arg-type]
        end_s = float(r["end_s"])  # type: ignore[arg-type]
        lines.append(f"- Shot idx={idx} (ảnh shot_{idx:03d}.jpg): từ {start_s:.2f}s đến {end_s:.2f}s")
    lines.append(
        "\nHãy trả về mô tả ngắn bằng tiếng Việt cho TỪNG shot (đúng số idx), "
        "chỉ mô tả những gì nhìn thấy thật (tay thợ, dụng cụ, góc quay, ánh sáng, kiểu dáng hình học), "
        "TUYỆT ĐỐI KHÔNG tự suy đoán tuổi bạc, loại đá hay giá tiền. "
        "Gắn 2-5 nhãn (tags) và chấm điểm chất lượng hình ảnh 1-5."
    )
    return "\n".join(lines)


def run_describe_footage(
    paths: AppPaths,
    footage_id: int,
    *,
    provider: AIProvider | None = None,
) -> str:
    """Runs `vision` AI description on all shots of `footage_id` and updates `shots` in SQLite."""
    footage = query_one(paths.db_file, "SELECT * FROM footage WHERE id = ?", (footage_id,))
    if footage is None:
        raise LookupError(f"Footage #{footage_id} not found")

    shot_rows = query_all(
        paths.db_file,
        "SELECT * FROM shots WHERE footage_id = ? ORDER BY idx ASC",
        (footage_id,),
    )
    if not shot_rows:
        raise ValueError(f"Footage #{footage_id} has no shots to describe")

    video_path = paths.media_dir / str(footage["path"])
    thumbnails: list[Path] = []
    for s in shot_rows:
        t_rel = str(s.get("thumb_path") or "")
        if t_rel:
            thumbnails.append(paths.media_dir / t_rel)

    vision_provider = provider or get_provider(paths, "vision")
    prompt = build_describe_prompt(shot_rows)
    response = vision_provider.describe_video(
        video_path,
        prompt,
        ShotDescriptionsResponse,
        thumbnails=thumbnails,
    )

    by_idx = {item.idx: item for item in response.shots}
    updated_count = 0
    with get_conn(paths.db_file) as conn:
        for pos, s in enumerate(shot_rows, start=1):
            shot_id = int(s["id"])
            idx = int(s["idx"])
            item = by_idx.get(idx) or (
                response.shots[pos - 1] if pos - 1 < len(response.shots) else None
            )
            if item is None:
                continue
            clean_tags = [t.strip() for t in item.tags if t and t.strip()][:8]
            conn.execute(
                """
                UPDATE shots
                SET description = ?,
                    tags_json = ?,
                    quality = ?
                WHERE id = ?
                """,
                (
                    item.description.strip(),
                    json.dumps(clean_tags, ensure_ascii=False),
                    max(1, min(5, int(item.quality))),
                    shot_id,
                ),
            )
            updated_count += 1

        record_audit(
            conn,
            actor="worker",
            action="footage.described",
            object_type="footage",
            object_id=footage_id,
            detail=f"Updated {updated_count}/{len(shot_rows)} shots",
        )

    try:
        from videocreator.tg.notify import notify_new_footage

        notify_new_footage(
            paths,
            footage_id,
            Path(str(footage["path"])).name,
            len(shot_rows),
        )
    except Exception as tg_exc:
        logger.debug("notify_new_footage hook skipped: %s", tg_exc)

    return f"Described {updated_count}/{len(shot_rows)} shots for footage #{footage_id}"
