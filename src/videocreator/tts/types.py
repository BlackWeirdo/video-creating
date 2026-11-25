"""Core TTS data structures and error types."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WordTiming:
    word: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class SynthesizedTrack:
    audio_path: Path
    duration_s: float
    word_timings: list[WordTiming]
    applied_atempo: float = 1.0
    provider: str = "edge"


class TTSUnavailableError(RuntimeError):
    """Raised when the configured TTS provider is offline or unavailable."""
