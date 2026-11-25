"""Public facade for Local AI Models management (`videocreator.ai_models`) and ASR/stem helpers."""
from __future__ import annotations

from videocreator.ai_models.catalog import (
    get_local_model,
    get_local_model_by_rowid,
    list_local_models,
)
from videocreator.ai_models.downloader import (
    install_local_model,
    remove_local_model,
    run_download_model_job,
)
from videocreator.ai_models.smoke import verify_model_smoke_test
from videocreator.pipeline.asr import transcribe_media_segments
from videocreator.pipeline.audio_sep import separate_vocals_and_bgm

__all__ = [
    "get_local_model",
    "get_local_model_by_rowid",
    "install_local_model",
    "list_local_models",
    "remove_local_model",
    "run_download_model_job",
    "separate_vocals_and_bgm",
    "transcribe_media_segments",
    "verify_model_smoke_test",
]
