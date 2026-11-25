"""Tests for v2.3.0 Gemini Imagen 3 integration, V1->V2 API parity, and template-free legacy V1 disablement."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from videocreator.ai.budget import get_daily_api_spend
from videocreator.app import create_app
from videocreator.config import load_settings, save_settings
from videocreator.paths import get_paths
from videocreator.pipeline.assembly import render_styled_still_png
from videocreator.pipeline.characters import create_character, generate_ai_image
from videocreator.pipeline.news_studio import create_news_project, render_news_project
from videocreator.secrets_store import SecretsStore
from videocreator.workspaces import create_workspace

pytestmark = pytest.mark.local


def _make_sample_png_bytes(tmp_dir: Path) -> bytes:
    sample = tmp_dir / "sample_imagen.png"
    render_styled_still_png(sample, w=540, h=960, seed=42)
    return sample.read_bytes()


def test_generate_ai_image_uses_gemini_imagen_when_key_and_budget_available(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data_imagen"
    create_app(data_dir=data_dir, start_worker=False)
    paths = get_paths(data_dir)
    SecretsStore(paths.secrets_file).set("GEMINI_API_KEY", "AIzaTestRealImagenKey123456")

    ws_id = int(create_workspace(paths.db_file, name="AI Studio", content_policy="full_ai"))
    ch = create_character(
        paths,
        workspace_id=ws_id,
        name="Linh Presenter",
        appearance_prompt="Vietnamese anchor in navy blazer",
        seed=777,
    )

    png_bytes = _make_sample_png_bytes(tmp_path)
    captured_calls: list[dict[str, Any]] = []

    class FakeModels:
        def generate_images(self, *, model: str, prompt: str, config: Any) -> Any:
            captured_calls.append({"model": model, "prompt": prompt, "config": config})
            return SimpleNamespace(
                generated_images=[
                    SimpleNamespace(image=SimpleNamespace(image_bytes=png_bytes))
                ]
            )

    class FakeClient:
        def __init__(self, *, api_key: str) -> None:
            self.api_key = api_key
            self.models = FakeModels()

    import google.genai as genai_mod

    monkeypatch.setattr(genai_mod, "Client", FakeClient)

    img = generate_ai_image(
        paths,
        workspace_id=ws_id,
        character_id=int(ch["id"]),
        prompt="Modern newsroom backdrop",
        aspect_ratio="9:16",
        animate_to_shot=True,
    )
    assert img["provider"] == "gemini_imagen"
    assert img["simulation_flags"] == []
    assert img["motion_shot_id"] is not None
    assert (paths.media_dir / img["image_path"]).is_file()
    assert len(captured_calls) == 1
    assert captured_calls[0]["model"] == "imagen-3.0-generate-002"
    assert "Linh Presenter" in captured_calls[0]["prompt"]
    assert round(get_daily_api_spend(paths.db_file, bucket="generative"), 4) == 0.03

    # News studio with real Imagen character does NOT report ai_image_canvas_placeholder
    cfg = load_settings(paths.config_file)
    cfg.voice.vi_provider = "test_tone"
    save_settings(paths.config_file, cfg)

    news = create_news_project(
        paths,
        workspace_id=ws_id,
        title="Ban tin kinh te",
        source_kind="raw_text",
        raw_text="Kim ngach xuat khau tang 14.5% trong quy 3. Doanh nghiep mo rong don hang sang EU.",
        character_id=int(ch["id"]),
    )
    done_news = render_news_project(paths, int(news["id"]), build_pack=False)
    assert "ai_image_canvas_placeholder" not in done_news["simulation_flags"]


def test_generate_ai_image_falls_back_cleanly_when_budget_exhausted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data_imagen_budget"
    create_app(data_dir=data_dir, start_worker=False)
    paths = get_paths(data_dir)
    SecretsStore(paths.secrets_file).set("GEMINI_API_KEY", "AIzaTestRealImagenKey123456")

    cfg = load_settings(paths.config_file)
    cfg.budget.generative_daily_usd = 0.01  # Below $0.03 Imagen cost
    save_settings(paths.config_file, cfg)

    ws_id = int(create_workspace(paths.db_file, name="Fallback Studio", content_policy="full_ai"))
    img = generate_ai_image(
        paths,
        workspace_id=ws_id,
        prompt="Sunset studio scene",
        aspect_ratio="1:1",
        animate_to_shot=False,
    )
    assert img["provider"] == "local_card"
    assert img["simulation_flags"] == ["ai_image_canvas_placeholder"]
    assert (paths.media_dir / img["image_path"]).is_file()
