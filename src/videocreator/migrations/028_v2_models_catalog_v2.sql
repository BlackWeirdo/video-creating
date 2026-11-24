-- pragma: foreign_keys=off
-- Migration 028: Verified AI Models Catalog v2 with per-file SHA-256, licenses & smoke-test state (R2).

DROP TABLE IF EXISTS local_models_v2;
CREATE TABLE local_models_v2 (
    model_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('asr', 'audio_sep', 'tts', 'ocr_inpaint', 'vision', 'translation', 'lipsync')),
    size_mb INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'not_installed' CHECK (status IN ('not_installed', 'downloading', 'downloaded', 'ready', 'failed')),
    local_path TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL DEFAULT '',
    download_url TEXT NOT NULL DEFAULT '',
    files_json TEXT NOT NULL DEFAULT '[]',
    license TEXT NOT NULL DEFAULT '',
    requires_python_pkgs TEXT NOT NULL DEFAULT '[]',
    smoke_tested INTEGER NOT NULL DEFAULT 0,
    progress REAL NOT NULL DEFAULT 0.0,
    error TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

DROP TABLE IF EXISTS local_models;
ALTER TABLE local_models_v2 RENAME TO local_models;

INSERT INTO local_models (
    model_id, name, category, size_mb, download_url, files_json, license, requires_python_pkgs
)
VALUES
    (
        'faster_whisper_small',
        'Faster-Whisper Small (Chép lời Trung/Anh/Việt & Word Timestamps)',
        'asr',
        465,
        'https://huggingface.co/Systran/faster-whisper-small/resolve/main/model.bin',
        '[{"filename":"model.bin","url":"https://huggingface.co/Systran/faster-whisper-small/resolve/main/model.bin","sha256":"3e305921506d8872816023e4c273e75d2419fb89b24da97b4fe7bce14170d671","size_bytes":483546902},{"filename":"config.json","url":"https://huggingface.co/Systran/faster-whisper-small/resolve/main/config.json","sha256":"b55496ac7940a7ae47d2c01eab40edfd8701feec1229d9cce3b40014383fb828","size_bytes":2370},{"filename":"tokenizer.json","url":"https://huggingface.co/Systran/faster-whisper-small/resolve/main/tokenizer.json","sha256":"fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab","size_bytes":2203239},{"filename":"vocabulary.txt","url":"https://huggingface.co/Systran/faster-whisper-small/resolve/main/vocabulary.txt","sha256":"34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913","size_bytes":459861}]',
        'MIT',
        '["faster_whisper"]'
    ),
    (
        'faster_whisper_medium',
        'Faster-Whisper Medium (Chép lời độ chính xác cao cho Tiếng Trung)',
        'asr',
        1460,
        'https://huggingface.co/Systran/faster-whisper-medium/resolve/main/model.bin',
        '[{"filename":"model.bin","url":"https://huggingface.co/Systran/faster-whisper-medium/resolve/main/model.bin","sha256":"9b45e1009dcc4ab601eff815b61d80e60ce3fd8c74c1a14f4a282258286b51ae","size_bytes":1527906378},{"filename":"config.json","url":"https://huggingface.co/Systran/faster-whisper-medium/resolve/main/config.json","sha256":"3622a2ddc41ec0e0fd4e68c13c6830f03b90c38d89aaad184de02c8c642cf807","size_bytes":2257},{"filename":"tokenizer.json","url":"https://huggingface.co/Systran/faster-whisper-medium/resolve/main/tokenizer.json","sha256":"fb7b63191e9bb045082c79fd742a3106a12c99513ab30df4a0d47fa6cb6fd0ab","size_bytes":2203239},{"filename":"vocabulary.txt","url":"https://huggingface.co/Systran/faster-whisper-medium/resolve/main/vocabulary.txt","sha256":"34ce3fe1c5041027b3f8d42912270993f986dbc4bb34cf27f951e34a1e453913","size_bytes":459861}]',
        'MIT',
        '["faster_whisper"]'
    ),
    (
        'speaker_embedding_onnx',
        '3D-Speaker CAM++ (Phân biệt người nói Trung/Anh/Đa ngữ trên CPU)',
        'asr',
        27,
        'https://huggingface.co/csukuangfj/speaker-embedding-models/resolve/main/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx',
        '[{"filename":"3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx","url":"https://huggingface.co/csukuangfj/speaker-embedding-models/resolve/main/3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx","sha256":"53cab20ba8f2eb2f6e2d89ecc18e88ef3222169b61b4419cbc13666744a4574b","size_bytes":28281165}]',
        'Apache-2.0',
        '["onnxruntime","kaldi_native_fbank"]'
    ),
    (
        'uvr_mdx_kim_vocal2',
        'UVR MDX-Net Kim Vocal 2 (Tách giọng nói / Giữ nhạc nền BGM)',
        'audio_sep',
        64,
        'https://huggingface.co/seanghay/uvr_models/resolve/main/Kim_Vocal_2.onnx',
        '[{"filename":"Kim_Vocal_2.onnx","url":"https://huggingface.co/seanghay/uvr_models/resolve/main/Kim_Vocal_2.onnx","sha256":"ce74ef3b6a6024ce44211a07be9cf8bc6d87728cc852a68ab34eb8e58cde9c8b","size_bytes":66759214}]',
        'MIT',
        '["onnxruntime","soundfile","scipy"]'
    ),
    (
        'vieneu_tts_vi',
        'VieNeu-TTS v3 Nano ONNX (Nhân bản giọng & Giọng Việt CPU)',
        'tts',
        401,
        'https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Nano/resolve/main/vector_estimator.onnx',
        '[{"filename":"codec_decoder.onnx","url":"https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Nano/resolve/main/codec_decoder.onnx","sha256":"b0ab15e7828a39d53679e25b1ba4ba415a61311307202a6323130b9e1cc3029d","size_bytes":99319941},{"filename":"codec_encoder.onnx","url":"https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Nano/resolve/main/codec_encoder.onnx","sha256":"195418031f190bf1c72dbfbed8490574754b346769180209a423a96c45caab98","size_bytes":56419417},{"filename":"config.json","url":"https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Nano/resolve/main/config.json","sha256":"3762f1716fd8d7a1451ddf2e051c03b0a341e8adda4f1dbd0db0ae9777514e56","size_bytes":2927},{"filename":"constants.npz","url":"https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Nano/resolve/main/constants.npz","sha256":"7c011938effe41687a9af85107a31a040dfcf0fb3d0f048ec10f4fb65c1a8829","size_bytes":53448},{"filename":"denoiser.onnx","url":"https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Nano/resolve/main/denoiser.onnx","sha256":"b7621953291cfe05e695a9c0ff4255aa2f93239fc17c26627e18b7b6b8f72f0b","size_bytes":42661414},{"filename":"duration_predictor.onnx","url":"https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Nano/resolve/main/duration_predictor.onnx","sha256":"20fd7fa60006d0a48ee82e0451b3f920d2052588c083c756cce669f3947c0a68","size_bytes":727809},{"filename":"reference_encoder.onnx","url":"https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Nano/resolve/main/reference_encoder.onnx","sha256":"6746906bfe857969a2b1b6e9091f1d4a19d9f04af4e187844021272dad4dcd3a","size_bytes":10778145},{"filename":"speaker_encoder.onnx","url":"https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Nano/resolve/main/speaker_encoder.onnx","sha256":"a6ac6a63997761ae2997373e2ee1c47040854b4b759ea41ec48e4e42df0f4d73","size_bytes":28303423},{"filename":"text_encoder.onnx","url":"https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Nano/resolve/main/text_encoder.onnx","sha256":"204f02cccae1f16ccb2d3840f05721a37fe250b82cbd456337a0ccb49615e4bf","size_bytes":26519943},{"filename":"vector_estimator.onnx","url":"https://huggingface.co/pnnbao-ump/VieNeu-TTS-v3-Nano/resolve/main/vector_estimator.onnx","sha256":"c6c1d4398ca35d3ad1bd3f0459413d1b975d09e7f2f3a2b4493a7b92bbf6ce93","size_bytes":155132418}]',
        'Apache-2.0',
        '["vieneu","onnxruntime"]'
    ),
    (
        'paddle_lama_inpaint',
        'LaMa ONNX Inpaint (Xóa sạch phụ đề cứng chất lượng cao)',
        'ocr_inpaint',
        199,
        'https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx',
        '[{"filename":"lama_fp32.onnx","url":"https://huggingface.co/Carve/LaMa-ONNX/resolve/main/lama_fp32.onnx","sha256":"1faef5301d78db7dda502fe59966957ec4b79dd64e16f03ed96913c7a4eb68d6","size_bytes":208044816}]',
        'Apache-2.0',
        '["onnxruntime","rapidocr_onnxruntime","cv2"]'
    ),
    (
        'nllb_200_distilled_600m_ct2',
        'NLLB-200 600M Int8 (Dịch máy đa ngữ Offline dự phòng)',
        'translation',
        601,
        'https://huggingface.co/JustFrederik/nllb-200-distilled-600M-ct2-int8/resolve/main/model.bin',
        '[{"filename":"model.bin","url":"https://huggingface.co/JustFrederik/nllb-200-distilled-600M-ct2-int8/resolve/main/model.bin","sha256":"ed1beaf75134de7505315a5223162f56acff397eff6b50638a500d3936fe707b","size_bytes":622595991},{"filename":"sentencepiece.bpe.model","url":"https://huggingface.co/JustFrederik/nllb-200-distilled-600M-ct2-int8/resolve/main/sentencepiece.bpe.model","sha256":"14bb8dfb35c0ffdea7bc01e56cea38b9e3d5efcdcb9c251d6b40538e1aab555a","size_bytes":4852054},{"filename":"shared_vocabulary.txt","url":"https://huggingface.co/JustFrederik/nllb-200-distilled-600M-ct2-int8/resolve/main/shared_vocabulary.txt","sha256":"a132a83330f45514c2476eb81d1d69b3c41762264d16ce0a7ea982e5d6c728e5","size_bytes":2568098},{"filename":"config.json","url":"https://huggingface.co/JustFrederik/nllb-200-distilled-600M-ct2-int8/resolve/main/config.json","sha256":"0c2f6fa2057c7264d052fb4a62ba3476eeae70487acddfa8e779a53a00cbf44c","size_bytes":159}]',
        'CC-BY-NC-4.0',
        '["ctranslate2","sentencepiece"]'
    ),
    (
        'rembg_u2net',
        'Rembg U2Net (Tách nền nhân vật & ảnh PNG)',
        'vision',
        168,
        'https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx',
        '[{"filename":"u2net.onnx","url":"https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx","sha256":"8d10d2f3bb75ae3b6d527c77944fc5e7dcd94b29809d47a739a7a728a912b491","size_bytes":175997641}]',
        'Apache-2.0',
        '["rembg","onnxruntime"]'
    );
