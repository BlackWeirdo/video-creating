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


def test_v1_to_v2_full_api_parity_endpoints(tmp_path: Path) -> None:
    """Verifies all 5 newly ported `/api/v1/*` groups (`broll`, `manual-tickets`, `ai/routes`, `manual-bundle`, `studio/templates`)."""
    from fastapi.testclient import TestClient

    from videocreator.db import get_conn
    from videocreator.pipeline.ffmpeg import run_ffmpeg

    data_dir = tmp_path / "data_parity"
    app = create_app(data_dir=data_dir, start_worker=False)
    paths = get_paths(data_dir)

    clip = tmp_path / "manual_broll.mp4"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=360x640:r=30:d=2.4",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(clip),
        ]
    )

    with TestClient(app) as client:
        # 1. /api/v1/broll + suggest + cancel
        broll_list = client.get("/api/v1/broll")
        assert broll_list.status_code == 200
        assert "sources" in broll_list.json()

        sug = client.post("/api/v1/broll/suggest")
        assert sug.status_code == 201
        assert sug.json()["queued"] is True

        canc = client.post("/api/v1/broll/suggest/cancel")
        assert canc.status_code == 200
        assert canc.json()["cancelled"] >= 1

        created_br = client.post(
            "/api/v1/broll",
            json={"prompt": "Macro velvet ring box spotlight", "source": "manual", "seconds": 6},
        )
        assert created_br.status_code == 201
        tid = int(created_br.json()["ticket_id"])

        # 2. /api/v1/manual-tickets (list, upload fulfillment, create + cancel, delete broll shot)
        mt_list = client.get("/api/v1/manual-tickets")
        assert mt_list.status_code == 200
        assert any(int(t["id"]) == tid for t in mt_list.json()["tickets"])

        with clip.open("rb") as fh:
            up = client.post(
                f"/api/v1/manual-tickets/{tid}/upload",
                files={"file": ("clip.mp4", fh, "video/mp4")},
            )
        assert up.status_code == 200
        shot_id = int(up.json()["shot_id"])

        t2 = client.post(
            "/api/v1/manual-tickets",
            json={"prompt": "Silk ribbon slow motion", "seconds": 6},
        )
        assert t2.status_code == 201
        t2_id = int(t2.json()["ticket_id"])
        c_res = client.post(f"/api/v1/manual-tickets/{t2_id}/cancel")
        assert c_res.status_code == 200
        assert c_res.json()["cancelled"] is True

        # 3. /api/v1/ai/routes + check-cli + wake
        ai_routes = client.get("/api/v1/ai/routes")
        assert ai_routes.status_code == 200
        assert "provider_states" in ai_routes.json()

        cli_res = client.post("/api/v1/ai/check-cli")
        assert cli_res.status_code == 200
        assert "ok" in cli_res.json()

        wake_res = client.post("/api/v1/ai/providers/claude_cli/wake")
        assert wake_res.status_code == 200
        assert wake_res.json()["woken"] is True

        # 4. /api/v1/studio/templates (save + list + render)
        with get_conn(paths.db_file) as conn:
            sid = int(
                conn.execute(
                    "INSERT INTO studio_sessions (workspace_id, prompt, status) VALUES (1, 'Showcase', 'done')"
                ).lastrowid
            )
        scene_tsx = paths.media_dir / "studio" / str(sid) / "src" / "Scene.tsx"
        scene_tsx.parent.mkdir(parents=True, exist_ok=True)
        scene_tsx.write_text("export const Scene = () => null;\n", encoding="utf-8")

        saved_tpl = client.post(
            f"/api/v1/studio/sessions/{sid}/save-template",
            json={"name": "Luxury Intro Template"},
        )
        assert saved_tpl.status_code == 201
        tpl_id = int(saved_tpl.json()["template_id"])

        tpl_list = client.get("/api/v1/studio/templates")
        assert tpl_list.status_code == 200
        assert any(int(t["id"]) == tpl_id for t in tpl_list.json()["templates"])

        rendered_tpl = client.post(
            f"/api/v1/studio/templates/{tpl_id}/render",
            json={"shot_ids": [shot_id], "subtitles": ["Mở màn sang trọng"], "title": "Intro"},
        )
        assert rendered_tpl.status_code == 201
        assert int(rendered_tpl.json()["session_id"]) > sid

        # 5. /api/v1/videos/{id}/manual-bundle + DELETE /api/v1/broll/{shot_id}
        out_rel = "output/test_master.mp4"
        out_mp4 = paths.media_dir / out_rel
        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        out_mp4.write_bytes(clip.read_bytes())
        with get_conn(paths.db_file) as conn:
            vid = int(
                conn.execute(
                    "INSERT INTO videos (workspace_id, engine, status, output_path, plan_json) VALUES (1, 'ffmpeg', 'approved', ?, '{}')",
                    (out_rel,),
                ).lastrowid
            )
        bundle = client.get(f"/api/v1/videos/{vid}/manual-bundle")
        assert bundle.status_code == 200
        assert bundle.headers["content-type"] == "application/zip"

        del_br = client.delete(f"/api/v1/broll/{shot_id}")
        assert del_br.status_code == 200
        assert del_br.json()["deleted"] is True


def test_disable_legacy_v1_flag_mounts_zero_jinja_routes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Proves `VIDEOCREATOR_DISABLE_LEGACY_V1=1` runs 100% template-free while keeping V2 API + essential mounts."""
    from fastapi.testclient import TestClient
    from starlette.routing import Route

    monkeypatch.setenv("VIDEOCREATOR_DISABLE_LEGACY_V1", "1")
    data_dir = tmp_path / "data_v2_only"
    app = create_app(data_dir=data_dir, start_worker=False)
    legacy_modules = [
        getattr(r.endpoint, "__module__", "")
        for r in app.routes
        if isinstance(r, Route)
        and str(getattr(r.endpoint, "__module__", "")).startswith("videocreator.api.routes_")
    ]
    assert legacy_modules == [], f"Legacy V1 routers still mounted: {legacy_modules}"

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/ui-unavailable").status_code == 200
        assert client.get("/broll").status_code == 404
        assert client.get("/").status_code == 404
