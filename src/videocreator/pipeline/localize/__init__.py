"""Localize, Reup, Hybrid Remix & Internationalize Studio package (`project`, `extract`, `translate`, `voice`, `render`)."""
from __future__ import annotations

from videocreator.pipeline.localize.extract import (
    run_localize_extract,
    run_localize_extract_job,
)
from videocreator.pipeline.localize.project import (
    VALID_HARDSUB_MODES,
    VALID_LOCALIZE_MODES,
    VALID_TRANSLATION_STYLES,
    VALID_WHISPER_SIZES,
    create_localize_project,
    get_localize_project,
    hydrate_project,
    list_localize_projects,
    normalize_hardsub_mode,
    pick_workspace_product_shots,
    resolve_source_media,
    set_project_status,
    update_localize_project,
    validate_localize_policy,
)
from videocreator.pipeline.localize.render import (
    run_localize_render,
    run_localize_render_job,
)
from videocreator.pipeline.localize.translate import (
    NUM_TOKEN_RE,
    TranslatedBatchSchema,
    TranslatedItemSchema,
    detect_script_lang,
    translate_localize_segments,
)
from videocreator.pipeline.localize.voice import (
    preview_localize_segment_audio,
    resolve_segment_voice_spec,
)

__all__ = [
    "NUM_TOKEN_RE",
    "TranslatedBatchSchema",
    "TranslatedItemSchema",
    "VALID_HARDSUB_MODES",
    "VALID_LOCALIZE_MODES",
    "VALID_TRANSLATION_STYLES",
    "VALID_WHISPER_SIZES",
    "create_localize_project",
    "detect_script_lang",
    "get_localize_project",
    "hydrate_project",
    "list_localize_projects",
    "normalize_hardsub_mode",
    "pick_workspace_product_shots",
    "preview_localize_segment_audio",
    "resolve_segment_voice_spec",
    "resolve_source_media",
    "run_localize_extract",
    "run_localize_extract_job",
    "run_localize_render",
    "run_localize_render_job",
    "set_project_status",
    "translate_localize_segments",
    "update_localize_project",
    "validate_localize_policy",
]
