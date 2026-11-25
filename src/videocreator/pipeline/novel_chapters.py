"""Chapter splitting, syllable-budget line fitting, and shot planning for Novel Studio."""
from __future__ import annotations

import re
from typing import Any

from videocreator.db import query_all
from videocreator.paths import AppPaths
from videocreator.pipeline.assembly import ensure_full_ai_canvas_shot
from videocreator.pipeline.characters import generate_ai_image
from videocreator.tts.syllables import count_syllables, max_syllables_for_duration

_CHAPTER_HEADING_RE = re.compile(
    r"^\s*(?:chương|chuong|chapter|hồi|hoi|part|#)\s*([^\n]+)",
    re.IGNORECASE | re.MULTILINE,
)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\r?\n+")


def split_novel_chapters(source_text: str, *, target_words: int = 140) -> list[dict[str, Any]]:
    """Splits novel/story text into ordered chapters by headings or paragraph word boundaries."""
    raw = (source_text or "").strip()
    if not raw:
        return []

    matches = list(_CHAPTER_HEADING_RE.finditer(raw))
    chapters: list[dict[str, Any]] = []
    if matches:
        preamble = raw[: matches[0].start()].strip()
        idx_cursor = 1
        if preamble and len(preamble.split()) >= 4:
            chapters.append(
                {
                    "chapter_index": idx_cursor,
                    "title": "Mở đầu",
                    "body_text": preamble,
                    "word_count": len(preamble.split()),
                }
            )
            idx_cursor += 1
        for i, m in enumerate(matches):
            body_start = m.end()
            body_end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
            heading = m.group(0).strip().lstrip("#").strip()
            body = raw[body_start:body_end].strip() or heading
            chapters.append(
                {
                    "chapter_index": idx_cursor,
                    "title": heading[:120],
                    "body_text": body,
                    "word_count": len(body.split()),
                }
            )
            idx_cursor += 1
        return chapters

    limit = max(20, int(target_words))
    paragraphs = [p.strip() for p in re.split(r"\r?\n\s*\r?\n|\r?\n", raw) if p.strip()]
    if len(paragraphs) <= 1:
        paragraphs = [s.strip() for s in _SENTENCE_SPLIT_RE.split(raw) if s.strip()]

    buf: list[str] = []
    buf_words = 0
    idx = 1
    for p in paragraphs:
        wc = len(p.split())
        if buf and (buf_words + wc) > limit:
            body = "\n".join(buf).strip()
            chapters.append(
                {
                    "chapter_index": idx,
                    "title": f"Chương {idx}",
                    "body_text": body,
                    "word_count": len(body.split()),
                }
            )
            idx += 1
            buf = [p]
            buf_words = wc
        else:
            buf.append(p)
            buf_words += wc

    if buf:
        body = "\n".join(buf).strip()
        chapters.append(
            {
                "chapter_index": idx,
                "title": f"Chương {idx}",
                "body_text": body,
                "word_count": len(body.split()),
            }
        )
    return chapters


def fit_line_to_budget(text: str, lang: str, duration_s: float) -> str:
    budget = max(5, max_syllables_for_duration(duration_s, lang))
    words = " ".join((text or "").split()).split()
    kept: list[str] = []
    for w in words:
        cand = " ".join([*kept, w])
        if count_syllables(cand, lang) > budget and kept:
            break
        kept.append(w)
    return " ".join(kept) or text[:48]


def build_chapter_lines(chapter_title: str, body_text: str, lang: str) -> list[dict[str, Any]]:
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(body_text) if len(s.strip()) >= 4]
    line1 = fit_line_to_budget(chapter_title, lang, 1.8)
    line2 = fit_line_to_budget(sentences[0] if sentences else body_text, lang, 2.0)
    line3 = fit_line_to_budget(
        sentences[1] if len(sentences) > 1 else (sentences[-1] if sentences else chapter_title),
        lang,
        1.8,
    )
    return [
        {"duration_s": 1.8, "text": line1},
        {"duration_s": 2.0, "text": line2},
        {"duration_s": 1.8, "text": line3},
    ]


def resolve_novel_chapter_shots(
    paths: AppPaths,
    proj: dict[str, Any],
    chapter: dict[str, Any],
    lines: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    ws_id = int(proj["workspace_id"])
    aspect_ratio = str(proj.get("aspect_ratio") or "9:16")
    shot_ids: list[int] = []
    used_placeholder_image = False

    char_id = proj.get("character_id")
    if char_id:
        img = generate_ai_image(
            paths,
            workspace_id=ws_id,
            character_id=int(char_id),
            prompt=f"{proj['title']} - {chapter['title']}"[:120],
            aspect_ratio=aspect_ratio,
            is_product_shot=False,
            animate_to_shot=True,
            actor="novel_studio",
        )
        if "ai_image_canvas_placeholder" in (img.get("simulation_flags") or []):
            used_placeholder_image = True
        if img.get("motion_shot_id"):
            shot_ids.append(int(img["motion_shot_id"]))

    ws_shots = query_all(
        paths.db_file,
        """
        SELECT s.id
        FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        LEFT JOIN assets a ON s.asset_id = a.id
        WHERE COALESCE(f.workspace_id, a.workspace_id, 1) = ?
        ORDER BY s.quality DESC, s.id ASC LIMIT 4
        """,
        (ws_id,),
    )
    shot_ids.extend(int(r["id"]) for r in ws_shots if int(r["id"]) not in shot_ids)

    if not shot_ids:
        shot_ids.append(ensure_full_ai_canvas_shot(paths, ws_id, aspect_ratio))

    planned: list[dict[str, Any]] = []
    for idx, seg in enumerate(lines):
        planned.append(
            {
                "shot_id": shot_ids[idx % len(shot_ids)],
                "duration_s": max(1.6, float(seg["duration_s"])),
                "text": str(seg["text"]),
            }
        )
    return planned, used_placeholder_image


__all__ = [
    "build_chapter_lines",
    "fit_line_to_budget",
    "resolve_novel_chapter_shots",
    "split_novel_chapters",
]
