"""Application configuration loaded from and saved to config.toml."""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

import tomli_w
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


class QualityConfig(BaseModel):
    min_score: float = 8.0
    max_retries: int = 2


class ScheduleConfig(BaseModel):
    timezone: str = "Asia/Ho_Chi_Minh"
    auto: bool = True
    slots: list[str] = Field(
        default_factory=lambda: ["08:00", "11:30", "15:00", "19:00", "21:00"]
    )
    daily_report_at: str = "21:30"
    weekly_report_at: str = "MON 09:00"


class TelegramConfig(BaseModel):
    allowed_chat_ids: list[int] = Field(default_factory=list)
    approver_user_ids: list[int] = Field(default_factory=list)
    quiet_hours: str = "22:00-07:00"
    max_trend_msgs_per_day: int = 3
    default_voice_lang: Literal["none", "vi", "en"] = "none"
    default_caption_lang: Literal["vi", "en"] = "vi"


class PlatformLimitConfig(BaseModel):
    min_duration_s: float = 5.0
    max_duration_s: float = 90.0
    max_size_mb: float = 100.0
    aspect_ratio: str = "9:16"
    min_fps: float = 24.0
    max_fps: float = 60.0
    video_codec: str = "h264"
    audio_codec: str = "aac"
    max_caption_chars: int = 2200


def _default_platform_limits() -> dict[str, PlatformLimitConfig]:
    return {
        "facebook": PlatformLimitConfig(min_duration_s=3.0, max_duration_s=90.0, max_caption_chars=2200),
        "instagram": PlatformLimitConfig(min_duration_s=5.0, max_duration_s=90.0, max_caption_chars=2200),
        "threads": PlatformLimitConfig(min_duration_s=5.0, max_duration_s=90.0, max_caption_chars=500),
        "tiktok": PlatformLimitConfig(min_duration_s=5.0, max_duration_s=90.0, max_caption_chars=2200),
    }


def _default_prices() -> dict[str, ModelPriceConfig]:
    return {
        "claude-opus-5-5": ModelPriceConfig(input_per_million_usd=4.0, output_per_million_usd=20.0),
        "claude-sonnet-5-5": ModelPriceConfig(input_per_million_usd=2.0, output_per_million_usd=10.0),
        "claude-haiku-5-5": ModelPriceConfig(input_per_million_usd=0.10, output_per_million_usd=0.50),
        "gemini-2.5-flash": ModelPriceConfig(input_per_million_usd=0.15, output_per_million_usd=0.60),
        "gemini-3.8-flash": ModelPriceConfig(input_per_million_usd=0.15, output_per_million_usd=0.60),
    }


class SafeZoneConfig(BaseModel):
    top: float = 0.15
    bottom: float = 0.25
    right: float = 0.12


class MPTConfig(BaseModel):
    version: str = "v1.3.9"
    port: int = 8080


class VoiceConfig(BaseModel):
    # Only Edge TTS voices were verified through MoneyPrinterTurbo (spike S12).
    vi_provider: str = "edge"
    vi_voice: str = "vi-VN-HoaiMyNeural-Female"
    en_provider: str = "edge"
    en_voice: str = "en-US-JennyNeural-Female"


class TrendsConfig(BaseModel):
    scan_at: str = "07:00"
    ad_library_countries: list[str] = Field(
        default_factory=lambda: ["DE", "FR", "IT", "ES", "NL"]
    )
    lookback_days: int = 30
    download_top_n: int = 5
    reference_keep_days: int = 7


class TikTokConfig(BaseModel):
    mode: Literal["inbox", "direct"] = "inbox"


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



class RetentionConfig(BaseModel):
    output_days: int = 90
    backup_keep: int = 14


class R2Config(BaseModel):
    bucket: str = ""
    public_base: str = ""


class Settings(BaseModel):
    role: Literal["server", "client"] = "server"
    host: str = "127.0.0.1"
    port: int = 8765

    ai: AIConfig = Field(default_factory=AIConfig)
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    prices: dict[str, ModelPriceConfig] = Field(default_factory=_default_prices)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)
    platform_limits: dict[str, PlatformLimitConfig] = Field(
        default_factory=_default_platform_limits
    )
    safe_zone: SafeZoneConfig = Field(default_factory=SafeZoneConfig)
    mpt: MPTConfig = Field(default_factory=MPTConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    trends: TrendsConfig = Field(default_factory=TrendsConfig)
    tiktok: TikTokConfig = Field(default_factory=TikTokConfig)
    studio: StudioConfig = Field(default_factory=StudioConfig)
    videogen: VideoGenConfig = Field(default_factory=VideoGenConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    r2: R2Config = Field(default_factory=R2Config)


def load_settings(config_file: Path) -> Settings:
    if not config_file.exists():
        settings = Settings()
        save_settings(config_file, settings)
        return settings
    with config_file.open("rb") as f:
        raw = tomllib.load(f)
    return Settings.model_validate(raw)


def save_settings(config_file: Path, settings: Settings) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    payload = settings.model_dump(mode="json")
    tmp_path = config_file.with_suffix(".toml.tmp")
    with tmp_path.open("wb") as f:
        tomli_w.dump(payload, f)
    tmp_path.replace(config_file)
