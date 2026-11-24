"""Vietnamese & multilingual segment translation via AI `translator` role + NLLB-200 CPU fallback (Stage R3)."""
from __future__ import annotations

import gc
import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from videocreator.ai.router import RoutedProvider
from videocreator.models_manager import get_local_model
from videocreator.paths import AppPaths
from videocreator.tts.syllables import count_syllables, max_syllables_for_duration

logger = logging.getLogger("videocreator.pipeline.translate_vi")

# Same numeric/fact token pattern as News Studio (Plan item 3.6)
NUM_TOKEN_RE = re.compile(r"\d+(?:[.,:/-]\d+)*(?:%|k|K|m|M|B|\b)")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_JA_RE = re.compile(r"[\u3040-\u30ff]")
_KO_RE = re.compile(r"[\uac00-\ud7af]")
_VI_DIACRITIC_RE = re.compile(r"[ăâđêôơưĂÂĐÊÔƠƯáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]")

_NLLB_LANG_MAP: dict[str, str] = {
    "vi": "vie_Latn",
    "en": "eng_Latn",
    "zh": "zho_Hans",
    "zh-cn": "zho_Hans",
    "zh-tw": "zho_Hant",
    "ja": "jpn_Jpan",
    "ko": "kor_Hang",
    "fr": "fra_Latn",
    "de": "deu_Latn",
    "es": "spa_Latn",
    "th": "tha_Thai",
}

_LANG_NAMES: dict[str, str] = {
    "vi": "Tiếng Việt (Vietnamese)",
    "en": "English",
    "zh": "Simplified Chinese (简体中文)",
    "ja": "Japanese (日本語)",
    "ko": "Korean (한국어)",
}


class TranslatedItemSchema(BaseModel):
    index: int
    translated_text: str


class TranslatedBatchSchema(BaseModel):
    segments: list[TranslatedItemSchema] = Field(default_factory=list)


def detect_script_lang(texts: list[str], declared_lang: str = "auto") -> str:
    clean = (declared_lang or "auto").strip().lower()
    if clean and clean != "auto":
        return clean.split("-")[0]
    joined = " ".join(texts)
    if _JA_RE.search(joined):
        return "ja"
    if _KO_RE.search(joined):
        return "ko"
    if _CJK_RE.search(joined):
        return "zh"
    if _VI_DIACRITIC_RE.search(joined):
        return "vi"
    return "en"


def extract_numeric_tokens(text: str) -> list[str]:
    seen: list[str] = []
    for tok in NUM_TOKEN_RE.findall(text or ""):
        if tok and tok not in seen:
            seen.append(tok)
    return seen


def enforce_numbers_and_budget(
    source_text: str,
    translated_text: str,
    *,
    target_lang: str,
    duration_s: float,
    strict_budget: bool = True,
) -> str:
    """Normalizes spacing around `%`, ensures key numeric tokens survive translation, and trims softly if far over budget."""
    txt = re.sub(r"(\d)\s+%", r"\1%", " ".join((translated_text or "").split())).strip()
    if not txt:
        txt = " ".join((source_text or "").split()).strip()

    src_nums = extract_numeric_tokens(source_text)
    missing = [tok for tok in src_nums if tok not in txt]
    if missing:
        txt = f"{txt} ({', '.join(missing[:3])})".strip()

    if not strict_budget:
        return txt

    # Allow 1.30x buffer because `fit_voice_to_budget` handles up to 1.35x atempo cleanly without chopping meaning
    soft_budget = max(4, int(round(max_syllables_for_duration(duration_s, target_lang) * 1.30)))
    if count_syllables(txt, target_lang) <= soft_budget:
        return txt

    words = txt.split()
    if len(words) <= 2:
        return txt
    kept: list[str] = []
    for w in words:
        cand = " ".join([*kept, w])
        if count_syllables(cand, target_lang) > soft_budget and kept:
            break
        kept.append(w)
    trimmed = " ".join(kept)
    # Never drop a numeric token during budget trimming
    still_missing = [tok for tok in src_nums if tok not in trimmed]
    if still_missing:
        trimmed = f"{trimmed} {' '.join(still_missing[:2])}".strip()
    return trimmed


def _build_translator_prompt(
    segments: list[dict[str, Any]],
    *,
    source_lang: str,
    target_lang: str,
    style: str,
) -> str:
    target_name = _LANG_NAMES.get(target_lang, target_lang)
    if style == "literal":
        style_guide = (
            "Phong cách DỊCH SÁT NGHĨA (literal): dịch trung thực, đầy đủ ý gốc, câu văn rõ ràng, "
            "nhưng vẫn đủ gọn để đọc kịp thời lượng mỗi đoạn."
        )
    else:
        style_guide = (
            "Phong cách PHIÊN DỊCH TỰ NHIÊN TIKTOK (natural_tiktok): diễn đạt theo văn nói đời thường tự nhiên, "
            "cuốn hút của creator Việt Nam trên TikTok/Reels, thoát ý mượt mà, KHÔNG dịch word-by-word cứng nhắc, "
            "và BẮT BUỘC khớp ngân sách âm tiết `max_syllables` của từng đoạn để lồng tiếng vừa khít hình."
        )

    payload_rows = []
    for idx, seg in enumerate(segments):
        dur = max(0.5, float(seg.get("end_s", 1.5)) - float(seg.get("start_s", 0.0)))
        payload_rows.append(
            {
                "index": idx,
                "duration_s": round(dur, 2),
                "max_syllables": max(3, max_syllables_for_duration(dur, target_lang)),
                "speaker_id": str(seg.get("speaker_id") or "SPK_1"),
                "source_text": str(seg.get("source_text") or ""),
                "must_preserve_numbers": extract_numeric_tokens(str(seg.get("source_text") or "")),
            }
        )

    return (
        f"Bạn là biên dịch viên lồng tiếng video ngắn chuyên nghiệp từ '{source_lang}' sang '{target_name}'.\n"
        f"{style_guide}\n"
        "QUY TẮC BẮT BUỘC:\n"
        "1. Giữ nguyên CHÍNH XÁC 100% mọi con số, phần trăm (%), đơn vị đo lường, mã sản phẩm (VD: 925, 50%, 2026) và tên riêng.\n"
        "2. Số âm tiết (từ đơn tiếng Việt) của `translated_text` phải xấp xỉ hoặc không vượt quá `max_syllables`.\n"
        "3. Trả về đúng số lượng phần tử `segments` theo `index` từ 0..N-1.\n\n"
        f"DỮ LIỆU ĐẦU VÀO:\n{json.dumps(payload_rows, ensure_ascii=False, indent=2)}"
    )


def _translate_via_nllb_local(
    paths: AppPaths,
    segments: list[dict[str, Any]],
    *,
    src_lang_iso: str,
    tgt_lang_iso: str,
) -> list[str] | None:
    model_info = get_local_model(paths, "nllb_200_distilled_600m_ct2")
    if not (model_info and model_info.get("status") == "ready" and model_info.get("installed_on_disk")):
        return None

    src_code = _NLLB_LANG_MAP.get(src_lang_iso, "eng_Latn")
    tgt_code = _NLLB_LANG_MAP.get(tgt_lang_iso, "vie_Latn")
    if src_code == tgt_code:
        return [str(s.get("source_text") or "") for s in segments]

    model_dir = Path(str(model_info["local_path"]))
    if model_dir.is_file():
        model_dir = model_dir.parent

    import ctranslate2
    import sentencepiece as spm

    sp = spm.SentencePieceProcessor(str(model_dir / "sentencepiece.bpe.model"))
    translator = ctranslate2.Translator(
        str(model_dir),
        device="cpu",
        compute_type="int8",
        inter_threads=1,
        intra_threads=4,
    )
    try:
        tokenized_batch: list[list[str]] = []
        for seg in segments:
            raw = str(seg.get("source_text") or "").strip()
            pieces = sp.encode(raw, out_type=str) if raw else []
            tokenized_batch.append([src_code, *pieces, "</s>"])

        results = translator.translate_batch(
            tokenized_batch,
            target_prefix=[[tgt_code]] * len(tokenized_batch),
            beam_size=2,
            max_batch_size=16,
            max_decoding_length=128,
            repetition_penalty=1.15,
        )
        decoded: list[str] = []
        for res in results:
            hyp = list(res.hypotheses[0]) if res.hypotheses else []
            if hyp and hyp[0] == tgt_code:
                hyp = hyp[1:]
            if hyp and hyp[-1] == "</s>":
                hyp = hyp[:-1]
            decoded.append(sp.decode(hyp).strip())
        return decoded
    finally:
        del translator
        gc.collect()


def translate_localize_segments(
    paths: AppPaths,
    segments: list[dict[str, Any]],
    *,
    source_lang: str = "auto",
    target_lang: str = "vi",
    translation_style: str = "natural_tiktok",
    provider_overrides: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Translates `segments` using AI `translator` role first, then offline `NLLB-200`, else marks `pending`.

    Returns `(updated_segments, engine_used)` where `engine_used` is one of:
    `'same_lang' | 'ai_translator' | 'nllb_offline' | 'pending'`.
    """
    if not segments:
        return [], "same_lang"

    if all(str(s.get("source_text") or "").startswith("Segment ") for s in segments):
        out_p = []
        for idx, seg in enumerate(segments):
            dur = max(0.5, float(seg["end_s"]) - float(seg["start_s"]))
            txt = str(seg.get("source_text") or "")
            out_p.append(
                {
                    **seg,
                    "index": idx,
                    "translated_text": txt,
                    "syllable_count": count_syllables(txt, target_lang),
                    "syllable_budget": max_syllables_for_duration(dur, target_lang),
                }
            )
        return out_p, "pending"

    src_iso = detect_script_lang([str(s.get("source_text") or "") for s in segments], source_lang)
    tgt_iso = (target_lang or "vi").strip().lower().split("-")[0]
    clean_style = "literal" if translation_style == "literal" else "natural_tiktok"

    if src_iso == tgt_iso:
        same_out: list[dict[str, Any]] = []
        for idx, seg in enumerate(segments):
            dur = max(0.5, float(seg["end_s"]) - float(seg["start_s"]))
            fitted = enforce_numbers_and_budget(
                str(seg.get("source_text") or ""),
                str(seg.get("source_text") or ""),
                target_lang=tgt_iso,
                duration_s=dur,
                strict_budget=(clean_style != "literal"),
            )
            same_out.append(
                {
                    **seg,
                    "index": idx,
                    "translated_text": fitted,
                    "syllable_count": count_syllables(fitted, tgt_iso),
                    "syllable_budget": max_syllables_for_duration(dur, tgt_iso),
                }
            )
        return same_out, "same_lang"

    # 1. Primary: Subscription-first AI Router (`role="translator"`)
    raw_translations: list[str] | None = None
    engine_used = "pending"
    try:
        router = RoutedProvider(
            paths,
            role="translator",
            provider_overrides=provider_overrides,
        )
        prompt = _build_translator_prompt(
            segments,
            source_lang=src_iso,
            target_lang=tgt_iso,
            style=clean_style,
        )
        ai_out = router.generate_json(prompt, TranslatedBatchSchema)
        by_idx = {int(it.index): str(it.translated_text).strip() for it in ai_out.segments}
        if by_idx:
            raw_translations = [
                by_idx.get(i) or str(segments[i].get("source_text") or "")
                for i in range(len(segments))
            ]
            engine_used = "ai_translator"
    except Exception as exc:
        logger.info("AI translator unavailable (%s); checking offline NLLB-200 fallback.", exc)

    # 2. Secondary: Local CPU NLLB-200 Distilled 600M Int8 (`CC-BY-NC-4.0`)
    if raw_translations is None:
        try:
            nllb_out = _translate_via_nllb_local(
                paths,
                segments,
                src_lang_iso=src_iso,
                tgt_lang_iso=tgt_iso,
            )
            if nllb_out and len(nllb_out) == len(segments):
                raw_translations = nllb_out
                engine_used = "nllb_offline"
        except Exception as exc:
            logger.warning("Offline NLLB-200 fallback failed: %s", exc)

    # 3. Final assembly with numeric preservation & syllable budget metadata
    final_segments: list[dict[str, Any]] = []
    for idx, seg in enumerate(segments):
        dur = max(0.5, float(seg["end_s"]) - float(seg["start_s"]))
        src_txt = str(seg.get("source_text") or "")
        cand_txt = raw_translations[idx] if raw_translations is not None else src_txt
        fitted = enforce_numbers_and_budget(
            src_txt,
            cand_txt,
            target_lang=tgt_iso,
            duration_s=dur,
            strict_budget=(clean_style != "literal"),
        )
        final_segments.append(
            {
                **seg,
                "index": idx,
                "translated_text": fitted,
                "syllable_count": count_syllables(fitted, tgt_iso),
                "syllable_budget": max_syllables_for_duration(dur, tgt_iso),
            }
        )

    return final_segments, engine_used
