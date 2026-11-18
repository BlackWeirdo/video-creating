"""Application configuration loaded from and saved to config.toml."""
from __future__ import annotations

import threading
import tomllib
from pathlib import Path
from typing import Literal

import tomli_w
from pydantic import BaseModel, Field

from videocreator.config_ai import (
    AIConfig,
    BudgetConfig,
    ModelPriceConfig,
    StudioConfig,
    VideoGenConfig,
    _default_prices,
)


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


class SafeZoneConfig(BaseModel):
    top: float = 0.15
    bottom: float = 0.25
    right: float = 0.12


class MPTConfig(BaseModel):
    version: str = "v1.3.9"
    port: int = 8080


class RenderConfig(BaseModel):
    # Keep the footage's own sound (tapping, filing, polishing silver), mixed low under voice/music.
    keep_original_audio: bool = False


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
    # Unanalysed trend items per source queued for AI structure analysis after each scan.
    # Kept small: each analysis can run rea-video for many minutes on the single job worker.
    auto_analyse_top_n: int = 3
    reference_keep_days: int = 7
    # Apify (third-party scrapers) for TikTok / Instagram / Facebook Reels / Meta Ad Library,
    # used when APIFY_API_TOKEN is in the secrets store. Owner decision 2026-11-14: free $5 first,
    # raise to at most $20/month if it proves useful.
    apify_monthly_usd: float = 5.0
    apify_results_per_item: int = 10
    ads_country: str = "VN"
    # 0 = ask 1-tap approval on suggestions (default); 1..3 = auto-accept & produce top N daily.
    auto_produce_top_n: int = Field(default=0, ge=0, le=3)
    render_mode: Literal["studio_preferred", "studio_only", "ffmpeg_enhanced"] = "studio_preferred"


class TikTokConfig(BaseModel):
    mode: Literal["inbox", "direct"] = "inbox"


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
    render: RenderConfig = Field(default_factory=RenderConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)
    trends: TrendsConfig = Field(default_factory=TrendsConfig)
    tiktok: TikTokConfig = Field(default_factory=TikTokConfig)
    studio: StudioConfig = Field(default_factory=StudioConfig)
    videogen: VideoGenConfig = Field(default_factory=VideoGenConfig)
    retention: RetentionConfig = Field(default_factory=RetentionConfig)
    r2: R2Config = Field(default_factory=R2Config)


# Parsed settings per config file, valid while the file's (mtime, size) signature is unchanged.
_settings_cache: dict[Path, tuple[tuple[int, int], Settings]] = {}
_settings_cache_lock = threading.Lock()


def _file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def load_settings(config_file: Path) -> Settings:
    """Settings of `config.toml` (created with defaults when missing).

    The file is parsed once and re-read only when it changes on disk; every caller gets its own
    copy, so changing the returned object never leaks into other callers."""
    try:
        signature = _file_signature(config_file)
    except FileNotFoundError:
        settings = Settings()
        save_settings(config_file, settings)
        return settings
    with _settings_cache_lock:
        cached = _settings_cache.get(config_file)
    if cached is not None and cached[0] == signature:
        return cached[1].model_copy(deep=True)
    with config_file.open("rb") as f:
        raw = tomllib.load(f)
    settings = Settings.model_validate(raw)
    with _settings_cache_lock:
        _settings_cache[config_file] = (signature, settings)
    return settings.model_copy(deep=True)


def save_settings(config_file: Path, settings: Settings) -> None:
    config_file.parent.mkdir(parents=True, exist_ok=True)
    payload = settings.model_dump(mode="json")
    tmp_path = config_file.with_suffix(".toml.tmp")
    with tmp_path.open("wb") as f:
        tomli_w.dump(payload, f)
    tmp_path.replace(config_file)
    with _settings_cache_lock:
        _settings_cache.pop(config_file, None)
