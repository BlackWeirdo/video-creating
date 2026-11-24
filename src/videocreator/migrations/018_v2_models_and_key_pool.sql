-- Migration 018: On-demand Local AI Models catalog and Multi-Key API rotation pool (V2-AI-01..03).

CREATE TABLE IF NOT EXISTS local_models (
    model_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('asr', 'audio_sep', 'tts', 'ocr_inpaint', 'vision', 'lipsync')),
    size_mb INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'not_installed' CHECK (status IN ('not_installed', 'downloading', 'ready', 'failed')),
    local_path TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL DEFAULT '',
    download_url TEXT NOT NULL DEFAULT '',
    progress REAL NOT NULL DEFAULT 0.0,
    error TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

INSERT OR IGNORE INTO local_models (model_id, name, category, size_mb, download_url)
VALUES
    (
        'faster_whisper_small',
        'Faster-Whisper Small (ASR & Word Timestamps)',
        'asr',
        480,
        'https://huggingface.co/Systran/faster-whisper-small'
    ),
    (
        'uvr_mdx_kim_vocal2',
        'UVR MDX-Net Kim Vocal 2 (Tách Vocal / Giữ BGM)',
        'audio_sep',
        68,
        'https://huggingface.co/spaces/Victoris/UVR5/resolve/main/Kim_Vocal_2.onnx'
    ),
    (
        'vieneu_tts_vi',
        'VieNeu-TTS Vietnamese (Nhân bản giọng Offline)',
        'tts',
        350,
        'https://huggingface.co/pnnbao-ump/VieNeu-TTS'
    ),
    (
        'paddle_lama_inpaint',
        'PaddleOCR + LaMa Inpaint (Xóa chữ cứng video nguồn)',
        'ocr_inpaint',
        210,
        'https://huggingface.co/smartywu/big-lama/resolve/main/big-lama.onnx'
    ),
    (
        'rembg_u2net',
        'Rembg U2Net (Tách nền nhân vật & sản phẩm)',
        'vision',
        176,
        'https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx'
    ),
    (
        'wav2lip_gan',
        'Wav2Lip GAN (Lip-sync nhép môi AI)',
        'lipsync',
        415,
        'https://huggingface.co/Nekochu/Wav2Lip/resolve/main/wav2lip_gan.pth'
    );

CREATE TABLE IF NOT EXISTS api_key_pool (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL CHECK (provider IN ('gemini', 'claude', 'openai_compat', 'fal', 'elevenlabs', 'muse')),
    label TEXT NOT NULL DEFAULT '',
    secret_key TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    priority INTEGER NOT NULL DEFAULT 0,
    cooldown_until TEXT NOT NULL DEFAULT '',
    use_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT NOT NULL DEFAULT '',
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_api_key_pool_provider
    ON api_key_pool(provider, enabled, priority DESC, use_count ASC);
