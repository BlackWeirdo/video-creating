"""Unit tests for Wave 2 shared backend blocks (`safe_paths`, `db_rows`, `compute_job`, `services`, `uploads`)."""
from __future__ import annotations

from pathlib import Path

import pytest

from videocreator.db_rows import file_media_url, hydrate_row, parse_json_list
from videocreator.pipeline.compute_job import compute_job_scope, run_studio_project_job
from videocreator.safe_paths import (
    UnsafePathError,
    is_strictly_within,
    resolve_within,
    safe_upload_stem,
    validated_extension,
)
from videocreator.services import (
    ALLOWED_AUDIO_EXTENSIONS,
    AVAILABLE_VOICE_CATALOG,
    KNOWN_SECRET_KEYS,
)

pytestmark = pytest.mark.local


def test_safe_paths_blocks_traversal_and_validates_extensions(tmp_path: Path) -> None:
    root = tmp_path / "media"
    (root / "sub").mkdir(parents=True)
    ok_file = root / "sub" / "clip.mp4"
    ok_file.write_bytes(b"ok")

    assert resolve_within(root, "sub/clip.mp4") == ok_file.resolve()
    assert resolve_within(root, "/sub/clip.mp4") == ok_file.resolve()
    assert is_strictly_within(root, ok_file) is True
    assert is_strictly_within(root, root) is False

    for bad in ("../secret.txt", "sub/../../secret.txt", "..\\secret.txt"):
        with pytest.raises(UnsafePathError):
            resolve_within(root, bad)

    assert safe_upload_stem("../../My Clip (Final)!.mp4") == "My_Clip_Final"
    assert validated_extension("track.MP3", ALLOWED_AUDIO_EXTENSIONS) == ".mp3"
    with pytest.raises(ValueError):
        validated_extension("malware.exe", ALLOWED_AUDIO_EXTENSIONS)


def test_db_rows_hydration_and_media_urls() -> None:
    raw = {
        "id": 7,
        "enabled": 1,
        "is_template": 0,
        "tags_json": '["a", "b"]',
        "broken_json": "{not-json",
        "output_path": "/output/v7.mp4",
    }
    hydrated = hydrate_row(
        raw,
        json_fields={"tags": ("tags_json", []), "meta": ("broken_json", {"fallback": True})},
        bool_fields=("enabled", "is_template"),
        media_url_from=("video_url", "output_path", ""),
    )
    assert hydrated["tags"] == ["a", "b"]
    assert hydrated["meta"] == {"fallback": True}
    assert hydrated["enabled"] is True
    assert hydrated["is_template"] is False
    assert hydrated["video_url"] == "/files/output/v7.mp4"
    assert file_media_url("pending", empty=None) is None
    assert parse_json_list('["x", 2]') == ["x", 2]
    assert parse_json_list("{bad") == []


def test_compute_job_scope_and_shared_services_catalog() -> None:
    called = False

    def _dummy_render(x: int) -> dict[str, str]:
        nonlocal called
        called = True
        return {"status": f"done_{x}"}

    assert run_studio_project_job(_dummy_render, 42) == "done_42"
    assert called is True
    with compute_job_scope():
        pass

    assert len(AVAILABLE_VOICE_CATALOG) >= 8
    assert any(k == "GEMINI_API_KEY" for k, _ in KNOWN_SECRET_KEYS)
