"""Synchronous `VideoGenProvider` adapter backed by Muse Gateway `/v1/tasks` (for background jobs)."""
from __future__ import annotations

import base64
import time
from pathlib import Path

from videocreator.ai.budget import record_usage
from videocreator.config import Settings
from videocreator.muse_gateway.client import MuseGatewayClient
from videocreator.muse_gateway.errors import MuseGatewayError
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore


class MuseVideoGenProvider:
    """Generates 9:16 video clips via Muse Gateway (`route='subscription'`, `$0` API cost)."""

    name = "muse_gateway"

    def __init__(
        self,
        paths: AppPaths,
        settings: Settings,
        secrets_store: SecretsStore,
        work_dir: Path,
    ) -> None:
        self.paths = paths
        self.settings = settings
        self.secrets = secrets_store
        self.work_dir = work_dir

    def generate_clip(
        self,
        prompt: str,
        seconds: int = 6,
        image: Path | None = None,
    ) -> Path:
        cfg = self.settings.muse_gateway
        client = MuseGatewayClient(cfg, self.secrets)
        client.verify_ready_and_safe()

        dur = max(1, min(60, int(seconds)))
        payload: dict[str, object] = {
            "model": cfg.default_video_model or "muse-video",
            "prompt": prompt,
            "duration": dur,
            "ratio": "9:16",
            "idempotency_key": f"vc-sync-{int(time.time() * 1000)}",
        }
        if image is not None and image.is_file():
            ext = image.suffix.lower()
            mime = "image/png" if ext == ".png" else ("image/webp" if ext == ".webp" else "image/jpeg")
            b64 = base64.b64encode(image.read_bytes()).decode("ascii")
            payload["images"] = [f"data:{mime};base64,{b64}"]

        created = client.create_task(payload)
        gw_id = str(created["id"])
        deadline = time.monotonic() + max(120.0, float(cfg.task_timeout_min) * 60.0)

        while time.monotonic() < deadline:
            time.sleep(max(2.0, float(cfg.poll_interval_s)))
            cur = client.get_task(gw_id)
            st = str(cur.get("status") or "running")
            if st in ("queued", "running"):
                continue
            if st != "succeeded":
                raise MuseGatewayError(
                    f"Muse video task {gw_id} ended with status '{st}': {cur.get('error')}"
                )
            media_list = [m for m in (cur.get("media") or []) if isinstance(m, dict) and m.get("url")]
            url = str(media_list[-1]["url"]) if media_list else str(cur.get("url") or "")
            if not url:
                raise MuseGatewayError(f"Muse video task {gw_id} returned no media URL")
            self.work_dir.mkdir(parents=True, exist_ok=True)
            out_mp4 = self.work_dir / f"muse_sync_{int(time.time() * 1000)}.mp4"
            client.download_media_to_file(url, out_mp4)
            record_usage(
                self.paths.db_file,
                provider=self.name,
                model=str(payload["model"]),
                kind="videogen",
                route="subscription",
                units_in=1,
                units_out=dur,
                cost_usd=0.0,
            )
            return out_mp4

        raise MuseGatewayError(f"Muse video task {gw_id} timed out")


__all__ = ["MuseVideoGenProvider"]
