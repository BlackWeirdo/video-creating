"""VideoGenProvider protocol and per-second cost estimation (Phase 14)."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from videocreator.config import Settings


class VideoGenProvider(Protocol):
    name: str

    def generate_clip(
        self,
        prompt: str,
        seconds: int = 6,
        image: Path | None = None,
    ) -> Path:
        """Generates a 9:16 video clip and returns the local `.mp4` path."""
        ...


def estimate_videogen_cost(
    settings: Settings,
    model_key: str,
    seconds: int,
) -> float:
    """Calculates estimated USD cost (`per_second_usd * seconds`) for `model_key` (`FR-BRL-03`)."""
    clean_key = model_key.replace("gateway_api:", "").replace("_api", "").strip().lower()
    if clean_key in ("manual", "muse", "muse-video"):
        return 0.0
    m_cfg = settings.videogen.models.get(clean_key)
    if m_cfg is not None:
        return round(max(1, int(seconds)) * float(m_cfg.per_second_usd), 4)
    p_cfg = settings.prices.get(clean_key)
    if p_cfg is not None and p_cfg.per_second_usd > 0:
        return round(max(1, int(seconds)) * float(p_cfg.per_second_usd), 4)
    return round(max(1, int(seconds)) * 0.15, 4)
