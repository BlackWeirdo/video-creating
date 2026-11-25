"""Canonical registry of known encrypted secret keys and Vietnamese UI labels."""
from __future__ import annotations

KNOWN_SECRET_KEYS: tuple[tuple[str, str], ...] = (
    ("GEMINI_API_KEY", "Gemini API Key (dự phòng vision/writer/TTS)"),
    ("ANTHROPIC_API_KEY", "Anthropic API Key (dự phòng writer/checker/Studio)"),
    ("MUSE_API_KEY", "Meta Model API Key (Muse Spark)"),
    ("MUSE_GATEWAY_API_KEY", "Muse Gateway API Key (/v1/*)"),
    ("MUSE_GATEWAY_WEBHOOK_SECRET", "Muse Gateway Webhook HMAC Secret"),
    ("OPENAI_API_KEY", "OpenAI API Key (TTS dự phòng)"),
    ("TELEGRAM_BOT_TOKEN", "Telegram Bot Token"),
    ("R2_ACCOUNT_ID", "Cloudflare R2 Account ID"),
    ("R2_ACCESS_KEY_ID", "Cloudflare R2 Access Key ID"),
    ("R2_SECRET_ACCESS_KEY", "Cloudflare R2 Secret Access Key"),
    ("YOUTUBE_API_KEY", "YouTube Data API v3 Key"),
    ("GOOGLE_CLIENT_ID", "Google OAuth Client ID (YouTube)"),
    ("GOOGLE_CLIENT_SECRET", "Google OAuth Client Secret (YouTube)"),
    ("APIFY_API_TOKEN", "Apify API Token (Quét TikTok / IG / Ad Library)"),
    ("FAL_API_KEY", "fal.ai API Key (Sinh ảnh / video AI)"),
    ("ELEVENLABS_API_KEY", "ElevenLabs API Key (TTS tuỳ chọn)"),
    ("META_AD_LIBRARY_TOKEN", "Meta Ad Library Access Token"),
    ("THREADS_APP_ID", "Threads App ID (OAuth)"),
    ("THREADS_APP_SECRET", "Threads App Secret (OAuth)"),
    ("TIKTOK_CLIENT_KEY", "TikTok Client Key (OAuth)"),
    ("TIKTOK_CLIENT_SECRET", "TikTok Client Secret (OAuth)"),
    ("UI_PASSWORD", "Mật khẩu giao diện (khi mở ngoài 127.0.0.1)"),
)
