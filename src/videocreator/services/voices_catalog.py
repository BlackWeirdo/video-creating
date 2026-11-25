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
    {"provider": "muse", "lang": "vi", "voice": "muse:Glad Kite", "label": "Muse Voice: Glad Kite (nữ Việt, điềm tĩnh - mặc định)"},
    {"provider": "muse", "lang": "vi", "voice": "muse:Breathless Rosette", "label": "Muse Voice: Breathless Rosette (nữ Việt, trong trẻo)"},
    {"provider": "muse", "lang": "vi", "voice": "muse:Sparkling Whistle", "label": "Muse Voice: Sparkling Whistle (nữ Việt, tươi sáng)"},
    {"provider": "muse", "lang": "vi", "voice": "muse:Kindhearted Jetty", "label": "Muse Voice: Kindhearted Jetty (nam Việt, tự tin)"},
    {"provider": "muse", "lang": "vi", "voice": "muse:Questioning Satchel", "label": "Muse Voice: Questioning Satchel (nam Việt, dẫn chuyện)"},
    {"provider": "muse", "lang": "vi", "voice": "muse:Tenacious Mooring", "label": "Muse Voice: Tenacious Mooring (nam Việt, dứt khoát)"},
    {"provider": "muse", "lang": "vi", "voice": "muse:Zealous Harbor", "label": "Muse Voice: Zealous Harbor (nam Việt, hào sảng)"},
    {"provider": "edge", "lang": "en", "voice": "en-US-JennyNeural-Female", "label": "Edge TTS: Jenny (female, English)"},
    {"provider": "edge", "lang": "en", "voice": "en-US-GuyNeural-Male", "label": "Edge TTS: Guy (male, English)"},
    {"provider": "muse", "lang": "en", "voice": "muse:Aria", "label": "Muse Voice: Aria (female, American warm)"},
    {"provider": "muse", "lang": "en", "voice": "muse:Helio", "label": "Muse Voice: Helio (male, American friendly)"},
]
