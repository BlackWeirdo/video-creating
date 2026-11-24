"""Speech syllable counting and shot-duration budget estimation for Vietnamese & English scripts."""
from __future__ import annotations

import re
from typing import Any

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)
_EN_VOWEL_GROUP_RE = re.compile(r"[aeiouy]+", re.IGNORECASE)
_CJK_CHAR_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")

_LANG_SYLLABLE_RATE: dict[str, float] = {
    "vi": 3.8,
    "en": 3.2,
    "zh": 4.0,
    "ja": 4.5,
    "ko": 4.0,
}


def _lang_rate(lang: str) -> float:
    code = (lang or "vi").strip().lower().split("-", 1)[0]
    return _LANG_SYLLABLE_RATE.get(code, 3.6)


def count_syllables(text: str, lang: str = "vi") -> int:
    """Estimates spoken syllable count across Vietnamese, English, and CJK languages."""
    raw = (text or "").strip()
    if not raw:
        return 0
    code = (lang or "vi").strip().lower().split("-", 1)[0]
    if code in ("zh", "ja", "ko"):
        cjk_chars = _CJK_CHAR_RE.findall(raw)
        non_cjk = _CJK_CHAR_RE.sub(" ", raw)
        other_words = _WORD_RE.findall(non_cjk)
        return len(cjk_chars) + len(other_words)

    words = _WORD_RE.findall(raw)
    if not words:
        return 0
    if code == "en":
        total = 0
        for w in words:
            cleaned = re.sub(r"(?:es|ed|e)$", "", w.lower()) or w.lower()
            groups = _EN_VOWEL_GROUP_RE.findall(cleaned)
            total += max(1, len(groups))
        return total
    return len(words)


def max_syllables_for_duration(duration_s: float, lang: str = "vi") -> int:
    """Maximum natural spoken syllables fitting in `duration_s`."""
    return int(round(max(0.0, float(duration_s)) * _lang_rate(lang)))


def check_syllable_budget(
    shots: list[dict[str, Any]], lang: str = "vi"
) -> list[dict[str, Any]]:
    """Checks each planned shot's script line against its duration syllable budget."""
    clean_lang = (lang or "vi").strip().lower()
    rate = _lang_rate(clean_lang)
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
