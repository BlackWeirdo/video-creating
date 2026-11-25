"""Built-in Edge TTS & VieNeu CPU voice catalog shared across API surfaces."""
from __future__ import annotations

AVAILABLE_VOICE_CATALOG: list[dict[str, str]] = [
    {"provider": "edge", "lang": "vi", "voice": "vi-VN-HoaiMyNeural-Female", "label": "Edge TTS: Hoài My (nữ, tiếng Việt)"},
    {"provider": "edge", "lang": "vi", "voice": "vi-VN-NamMinhNeural-Male", "label": "Edge TTS: Nam Minh (nam, tiếng Việt)"},
    {"provider": "vieneu", "lang": "vi", "voice": "Minh Quân", "label": "VieNeu CPU: Minh Quân (nam Bắc, tự nhiên)"},
    {"provider": "vieneu", "lang": "vi", "voice": "Trúc Ly", "label": "VieNeu CPU: Trúc Ly (nữ Bắc, tự nhiên)"},
    {"provider": "vieneu", "lang": "vi", "voice": "Ái Hân", "label": "VieNeu CPU: Ái Hân (nữ miền Nam, tin tức)"},
    {"provider": "vieneu", "lang": "vi", "voice": "Adam", "label": "VieNeu CPU: Adam (nam miền Nam, tự nhiên)"},
    {"provider": "vieneu", "lang": "vi", "voice": "Mỹ Duyên", "label": "VieNeu CPU: Mỹ Duyên (nữ Bắc, kể chuyện)"},
    {"provider": "vieneu", "lang": "vi", "voice": "Đức Trí", "label": "VieNeu CPU: Đức Trí (nam Bắc, đọc truyện)"},
    {"provider": "edge", "lang": "en", "voice": "en-US-JennyNeural-Female", "label": "Edge TTS: Jenny (female, English)"},
    {"provider": "edge", "lang": "en", "voice": "en-US-GuyNeural-Male", "label": "Edge TTS: Guy (male, English)"},
]
