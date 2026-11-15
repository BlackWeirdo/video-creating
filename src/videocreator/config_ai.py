"""AI-related sections of `config.toml`: routes, policy, budget, prices, Studio, video generation."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AIRoutesConfig(BaseModel):
    vision: list[str] = Field(
        default_factory=lambda: ["claude_cli", "gemini_api"]
    )
    writer: list[str] = Field(
        default_factory=lambda: ["claude_cli", "muse_api", "claude_api"]
    )
    checker: list[str] = Field(
        default_factory=lambda: ["claude_cli", "claude_api", "gemini_api"]
    )
    studio: list[str] = Field(
        default_factory=lambda: ["claude_cli", "claude_api"]
    )
    videogen: list[str] = Field(
        default_factory=lambda: [
            "manual",
            "gateway_api:kling",
            "gateway_api:seedance",
            "veo_api",
        ]
    )


class AIPolicyConfig(BaseModel):
    api_fallback: Literal["auto", "ask", "never"] = "ask"
    offpeak_hours: str = "23:00-06:00"


class AIConfig(BaseModel):
    routes: AIRoutesConfig = Field(default_factory=AIRoutesConfig)
    policy: AIPolicyConfig = Field(default_factory=AIPolicyConfig)
    gemini_model: str = "gemini-3.8-flash"
    claude_writer_model: str = "claude-opus-5-5"
    claude_checker_model: str = "claude-haiku-5-5"


class BudgetConfig(BaseModel):
    daily_usd: float = 5.0
    generative_daily_usd: float = 15.0
    studio_daily_usd: float = 10.0


class ModelPriceConfig(BaseModel):
    input_per_million_usd: float = 0.0
    output_per_million_usd: float = 0.0
    per_second_usd: float = 0.0


def _default_prices() -> dict[str, ModelPriceConfig]:
    return {
        "claude-opus-5-5": ModelPriceConfig(input_per_million_usd=4.0, output_per_million_usd=20.0),
        "claude-sonnet-5-5": ModelPriceConfig(input_per_million_usd=2.0, output_per_million_usd=10.0),
        "claude-haiku-5-5": ModelPriceConfig(input_per_million_usd=0.10, output_per_million_usd=0.50),
        "gemini-2.5-flash": ModelPriceConfig(input_per_million_usd=0.15, output_per_million_usd=0.60),
        "gemini-3.8-flash": ModelPriceConfig(input_per_million_usd=0.15, output_per_million_usd=0.60),
    }


class StudioConfig(BaseModel):
    model: str = "claude-opus-5-5"
    max_turns: int = 30
    max_session_usd: float = 5.0


class VideoGenModelConfig(BaseModel):
    endpoint: str
    per_second_usd: float = 0.15
    supports_image: bool = True


def _default_videogen_models() -> dict[str, VideoGenModelConfig]:
    return {
        "kling": VideoGenModelConfig(
            endpoint="fal-ai/kling-video/v1.6/pro/image-to-video",
            per_second_usd=0.14,
            supports_image=True,
        ),
        "seedance": VideoGenModelConfig(
            endpoint="fal-ai/bytedance/seedance/v1/pro/text-to-video",
            per_second_usd=0.12,
            supports_image=True,
        ),
        "veo": VideoGenModelConfig(
            endpoint="veo-3.0-generate-preview",
            per_second_usd=0.35,
            supports_image=True,
        ),
    }


class VideoGenConfig(BaseModel):
    gateway_base_url: str = "https://queue.fal.run"
    models: dict[str, VideoGenModelConfig] = Field(
        default_factory=_default_videogen_models
    )
