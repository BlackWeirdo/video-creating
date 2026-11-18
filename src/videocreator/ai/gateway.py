"""Model gateway video-generation adapter for Kling, Seedance, and config-driven models (Phase 14)."""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from videocreator.config import Settings
from videocreator.secrets_store import SecretsStore

MAX_GATEWAY_VIDEO_BYTES = 250 * 1024 * 1024


def _assert_trusted_gateway_url(url: str, base_url: str) -> None:
    parsed = urlparse(url)
    base = urlparse(base_url)
    if parsed.scheme != base.scheme or not parsed.hostname or not base.hostname:
        raise RuntimeError(f"Untrusted gateway callback URL: {url}")
    host = parsed.hostname.lower()
    base_host = base.hostname.lower()
    same_fal = base_host.endswith(".fal.run") and host.endswith(".fal.run")
    if host != base_host and not same_fal:
        raise RuntimeError(f"Gateway callback URL host mismatch ({host} != {base_host})")


class GatewayVideoGenProvider:
    """Unified queue-based model gateway adapter (`fal.ai` compatible) reading model endpoints from `config.toml`."""

    def __init__(
        self,
        model_key: str,
        settings: Settings,
        secrets_store: SecretsStore,
        work_dir: Path,
        *,
        http_client: Any = None,
    ) -> None:
        clean_key = model_key.replace("gateway_api:", "").strip().lower()
        if clean_key not in settings.videogen.models:
            raise KeyError(f"Unknown videogen gateway model '{clean_key}' in config.toml")
        self.model_key = clean_key
        self.model_cfg = settings.videogen.models[clean_key]
        self.name = f"gateway_api:{clean_key}"
        self.base_url = settings.videogen.gateway_base_url.rstrip("/")
        self.secrets = secrets_store
        self.work_dir = work_dir
        self._client = http_client

    def _get_api_key(self) -> str:
        key = self.secrets.get("FAL_API_KEY") or self.secrets.get("VIDEOGEN_GATEWAY_API_KEY")
        if not key:
            raise RuntimeError("Missing FAL_API_KEY in SecretsStore for gateway video generation")
        return key

    def generate_clip(
        self,
        prompt: str,
        seconds: int = 6,
        image: Path | None = None,
    ) -> Path:
        api_key = self._get_api_key()
        headers = {
            "Authorization": f"Key {api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "prompt": prompt,
            "duration": str(max(4, min(10, int(seconds)))),
            "aspect_ratio": "9:16",
        }
        if image is not None and image.exists() and self.model_cfg.supports_image:
            raw_b64 = base64.b64encode(image.read_bytes()).decode("ascii")
            payload["image_url"] = f"data:image/jpeg;base64,{raw_b64}"

        submit_url = f"{self.base_url}/{self.model_cfg.endpoint.lstrip('/')}"
        client = self._client or httpx.Client(timeout=120.0)
        close_client = self._client is None
        try:
            resp = client.post(submit_url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

            # Immediate video URL or queued status URL
            video_url = (data.get("video") or {}).get("url") or data.get("video_url")
            status_url = data.get("status_url")
            response_url = data.get("response_url")
            if status_url:
                _assert_trusted_gateway_url(str(status_url), self.base_url)
            if response_url:
                _assert_trusted_gateway_url(str(response_url), self.base_url)

            deadline = time.monotonic() + 300.0
            while not video_url and status_url and time.monotonic() < deadline:
                time.sleep(2.0)
                st_resp = client.get(status_url, headers=headers)
                st_resp.raise_for_status()
                st_data = st_resp.json()
                status_val = str(st_data.get("status") or "").upper()
                if status_val == "COMPLETED":
                    video_url = (st_data.get("video") or {}).get("url") or st_data.get("video_url")
                    target_res_url = st_data.get("response_url") or response_url
                    if not video_url and target_res_url:
                        _assert_trusted_gateway_url(str(target_res_url), self.base_url)
                        res_resp = client.get(str(target_res_url), headers=headers)
                        res_resp.raise_for_status()
                        res_data = res_resp.json()
                        video_url = (res_data.get("video") or {}).get("url") or res_data.get("video_url")
                    break
                if status_val in ("FAILED", "ERROR", "CANCELLED"):
                    raise RuntimeError(f"Gateway video generation failed: {st_data}")

            if not video_url:
                raise RuntimeError(f"Gateway response did not return a video URL: {data}")

            parsed_dl = urlparse(str(video_url))
            if parsed_dl.scheme not in ("https", "http"):
                raise RuntimeError(f"Unsupported gateway video URL scheme: {video_url}")

            self.work_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.work_dir / f"gateway_{self.model_key}_{int(time.time() * 1000)}.mp4"
            if hasattr(client, "stream"):
                total = 0
                with client.stream("GET", str(video_url)) as dl_resp:
                    dl_resp.raise_for_status()
                    with out_path.open("wb") as fh:
                        for chunk in dl_resp.iter_bytes():
                            total += len(chunk)
                            if total > MAX_GATEWAY_VIDEO_BYTES:
                                out_path.unlink(missing_ok=True)
                                raise RuntimeError("Gateway video exceeds maximum allowed size")
                            fh.write(chunk)
            else:
                dl_resp = client.get(str(video_url))
                dl_resp.raise_for_status()
                if len(dl_resp.content) > MAX_GATEWAY_VIDEO_BYTES:
                    raise RuntimeError("Gateway video exceeds maximum allowed size")
                out_path.write_bytes(dl_resp.content)
            return out_path
        finally:
            if close_client:
                client.close()
