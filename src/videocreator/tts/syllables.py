"""Speech syllable counting and shot-duration budget estimation for Vietnamese & English scripts."""
from __future__ import annotations

import re
from typing import Any

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_EN_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+", re.IGNORECASE)


def count_syllables(text: str, lang: str = "vi") -> int:
    """Estimates spoken syllable count for Vietnamese (1 word ~= 1 syllable) or English."""
    words = _WORD_RE.findall((text or "").strip())
    if not words:
        return 0
    if (lang or "vi").strip().lower() == "en":
        total = 0
        for w in words:
            cleaned = re.sub(r"(?:es|ed|e)$", "", w.lower()) or w.lower()
            groups = _EN_VOWEL_GROUP_RE.findall(cleaned)
            total += max(1, len(groups))
        return total
    return len(words)


def max_syllables_for_duration(duration_s: float, lang: str = "vi") -> int:
    """Maximum natural spoken syllables fitting in `duration_s` (`~3.8 syl/s` vi, `~3.2 syl/s` en)."""
    rate = 3.2 if (lang or "vi").strip().lower() == "en" else 3.8
    return int(round(max(0.0, float(duration_s)) * rate))


def check_syllable_budget(
    shots: list[dict[str, Any]], lang: str = "vi"
) -> list[dict[str, Any]]:
    """Checks each planned shot's script line against its duration syllable budget."""
    clean_lang = (lang or "vi").strip().lower()
    rate = 3.2 if clean_lang == "en" else 3.8
    report: list[dict[str, Any]] = []
    for idx, shot in enumerate(shots):
        dur = max(0.5, float(shot.get("duration_s") or 0.5))
        text = str(shot.get("text") or "").strip()
        syllables = count_syllables(text, clean_lang)
        budget = max_syllables_for_duration(dur, clean_lang)
        est_dur = round(syllables / rate, 2) if syllables > 0 else 0.0
        over_budget = syllables > budget and budget > 0
        rec_atempo = (
            round(min(1.35, max(1.0, est_dur / max(0.3, dur))), 2)
            if over_budget
            else 1.0
        )
        report.append(
            {
                "shot_index": idx,
                "shot_id": int(shot.get("shot_id") or 0),
                "duration_s": round(dur, 2),
                "text": text,
                "syllables": syllables,
                "max_syllables": budget,
                "over_budget": over_budget,
                "estimated_duration_s": est_dur,
                "recommended_atempo": rec_atempo,
            }
        )
    return report
