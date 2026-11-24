"""Direct Google Veo video-generation provider via `google-genai` (Phase 14)."""
from __future__ import annotations

import time
from pathlib import Path

from videocreator.ai.key_pool import acquire_api_key
from videocreator.config import Settings
from videocreator.secrets_store import SecretsStore


class VeoVideoGenProvider:
    """Generates 9:16 B-roll clips via Google Veo (`google-genai` SDK)."""

    name = "veo_api"

    def __init__(
        self,
        settings: Settings,
        secrets_store: SecretsStore,
        work_dir: Path,
    ) -> None:
        self.settings = settings
        self.secrets = secrets_store
        self.work_dir = work_dir
        veo_cfg = settings.videogen.models.get("veo")
        self.model = veo_cfg.endpoint if veo_cfg else "veo-3.0-generate-preview"

    def generate_clip(
        self,
        prompt: str,
        seconds: int = 6,
        image: Path | None = None,
    ) -> Path:
        db_file = self.secrets.secrets_file.parent / "app.db"
        api_key, _ = acquire_api_key(
            db_file,
            "gemini",
            legacy_secret_name="GEMINI_API_KEY",
            secrets_store=self.secrets,
        )
        if not api_key:
            raise RuntimeError("Missing GEMINI_API_KEY in SecretsStore for Veo video generation")

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        config = types.GenerateVideosConfig(
            aspect_ratio="9:16",
            duration_seconds=max(5, min(8, int(seconds))),
        )
        operation = client.models.generate_videos(
            model=self.model,
            prompt=prompt,
            config=config,
        )
        deadline = time.monotonic() + 300.0
        while not operation.done and time.monotonic() < deadline:
            time.sleep(5.0)
            operation = client.operations.get(operation)

        if not operation.done or not operation.response or not operation.response.generated_videos:
            raise RuntimeError("Veo video generation did not return a generated video")

        gen_video = operation.response.generated_videos[0]
        self.work_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.work_dir / f"veo_{int(time.time() * 1000)}.mp4"
        client.files.download(file=gen_video.video)
        gen_video.video.save(str(out_path))
        return out_path
