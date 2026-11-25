"""Internal Text-to-Speech synthesis, silence trimming, atempo fitting, and syllable budgets."""
from __future__ import annotations

from videocreator.tts.syllables import (
    check_syllable_budget,
    count_syllables,
    max_syllables_for_duration,
)
from videocreator.tts.synthesizer import (
    SynthesizedTrack,
    TTSUnavailableError,
    WordTiming,
    fit_voice_to_budget,
    synthesize_speech_segments,
    synthesize_with_local_fallback,
    trim_voice_silence,
)

__all__ = [
    "SynthesizedTrack",
    "TTSUnavailableError",
    "WordTiming",
    "check_syllable_budget",
    "count_syllables",
    "fit_voice_to_budget",
    "max_syllables_for_duration",
    "synthesize_speech_segments",
    "synthesize_with_local_fallback",
    "trim_voice_silence",
]
