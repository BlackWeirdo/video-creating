"""B-roll idea schema and the cleaning that turns AI answers into generation prompts."""
from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("videocreator.pipeline.broll_suggest")

# Appended by code to every prompt. Positive wording only: text-to-video models tend to ignore
# negations, and naming "jewelry" in a "no jewelry" clause can pull jewelry into the clip.
# The product ban lives in the writer prompt and in `normalize_broll_ideas`.
BROLL_PROMPT_GUARD = "cảnh quay thật chân thực bằng máy quay, khung dọc 9:16"

BROLL_PROMPT_GUARD_EN = "photorealistic live-action footage shot on a real camera, vertical 9:16 frame"

# English prompts go to the paid generators; drop an idea whose English prompt names jewelry.
JEWELRY_WORDS_EN = re.compile(
    # "ring light" is a lighting tool (rea-video's look report suggests one), not jewelry.
    r"\b(jewel(?:ry|lery|s)?|rings?(?!\s+lights?\b)|earrings?|necklaces?|pendants?|bracelets?|bangles?|"
    r"charms?|chains?|brooch(?:es)?|cufflinks?)\b",
    re.IGNORECASE,
)

MIN_PRODUCT_NAME_LEN = 4

# Real prompts and looks run to 150+ characters. The CLI once returned a schema-valid placeholder
# batch ("test prompt", "test look vi"), so anything this short is treated as junk.
MIN_PROMPT_CHARS = 40

MIN_LOOK_CHARS = 40
MAX_FIELD_CHARS = 400
MIN_SECONDS = 4
MAX_SECONDS = 10
DEFAULT_IDEA_COUNT = 5


class BrollIdeaSchema(BaseModel):
    label: str = Field(description="Tên ngắn tiếng Việt cho ý tưởng, tối đa 8 từ")
    prompt: str = Field(
        description=(
            "Cảnh phụ bằng tiếng Việt: chủ thể, hành động, cỡ cảnh, góc máy, chuyển động máy theo video mẫu. "
            "Câu khẳng định. KHÔNG nhắc trang sức/sản phẩm; KHÔNG lặp ánh sáng/màu/tương phản (đã ở look_vi)"
        )
    )
    prompt_en: str = Field(
        description="Cùng cảnh đó bằng tiếng Anh tự nhiên cho máy sinh video (Kling, Seedance, Veo); cùng luật như `prompt`"
    )
    seconds: int = Field(default=6, description="Thời lượng 4-10 giây, khớp nhịp cắt của video xu hướng")
    placement: str = Field(description="Đặt ở đâu trong video (không bao giờ là cảnh mở đầu)")
    reason: str = Field(description="Vì sao cảnh này hợp: dựa trên phân tích xu hướng nào, bù chỗ thiếu nào của kho footage")
    trend_item_id: int = Field(default=0, description="ID video xu hướng làm căn cứ, 0 nếu không có")


class BrollIdeasBatchSchema(BaseModel):
    look_vi: str = Field(
        description=(
            "Một đoạn mô tả look CHUNG cho mọi cảnh phụ, tiếng Việt, lấy từ số đo `look` của video mẫu: "
            "kiểu ánh sáng và hướng sáng, nhiệt độ màu, màu sắc/độ bão hòa, độ tương phản và vùng tối, "
            "độ sâu trường ảnh/hậu cảnh, kiểu giữ máy. Câu khẳng định"
        )
    )
    look_en: str = Field(description="Cùng đoạn look đó bằng tiếng Anh cho máy sinh video")
    ideas: list[BrollIdeaSchema] = Field(default_factory=list)


def collapse_whitespace(text: str) -> str:
    return text.strip().rstrip(" .,;")


def _join_prompt_parts(*parts: str) -> str:
    return ", ".join(p for p in (collapse_whitespace(x) for x in parts) if p)


def normalize_broll_ideas(
    ideas: list[BrollIdeaSchema],
    *,
    look_vi: str = "",
    look_en: str = "",
    valid_trend_ids: set[int],
    product_names: list[str],
    count: int = DEFAULT_IDEA_COUNT,
) -> list[dict[str, Any]]:
    """Applies the B-roll rules in code instead of trusting the model output.

    Every kept idea gets the same look and the same realism/format guard, so all clips match.
    """
    # Very short names ("Bạc") would drop allowed ideas such as raw silver stock, so skip them.
    lowered_names = [
        n.strip().lower() for n in product_names if len(n.strip()) >= MIN_PRODUCT_NAME_LEN
    ]
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idea in ideas:
        body = collapse_whitespace(idea.prompt)
        body_en = collapse_whitespace(idea.prompt_en)
        if len(body) < MIN_PROMPT_CHARS or len(body_en) < MIN_PROMPT_CHARS:
            continue
        both_lower = f"{body}\n{body_en}".lower()
        if any(name in both_lower for name in lowered_names):
            logger.info("Dropped B-roll idea naming a real product: %s", idea.label)
            continue
        if JEWELRY_WORDS_EN.search(body_en):
            logger.info("Dropped B-roll idea whose English prompt names jewelry: %s", idea.label)
            continue
        if body.lower() in seen:
            continue
        seen.add(body.lower())
        out.append(
            {
                "label": idea.label.strip()[:80] or "Cảnh phụ",
                "prompt": _join_prompt_parts(body, look_vi, BROLL_PROMPT_GUARD),
                "prompt_en": _join_prompt_parts(body_en, look_en, BROLL_PROMPT_GUARD_EN),
                "seconds": max(MIN_SECONDS, min(MAX_SECONDS, int(idea.seconds))),
                "placement": idea.placement.strip(),
                "reason": idea.reason.strip(),
                "trend_item_id": idea.trend_item_id if idea.trend_item_id in valid_trend_ids else 0,
            }
        )
        if len(out) >= count:
            break
    return out
