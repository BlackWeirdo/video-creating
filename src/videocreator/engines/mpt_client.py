"""REST client for the local MoneyPrinterTurbo service, used for voice-over + voice-timed subtitles only.

Spike S12 (MoneyPrinterTurbo v1.3.9, 2026-11-14) showed that MPT's full video assembly forces the
video to the voice-over length: it truncates the last segment or loops the footage. So the app keeps
assembling with its own FFmpeg pipeline and only asks MPT for `audio.mp3` + `subtitle.srt`
(`POST /api/v1/subtitle`), then fetches both over HTTP so no filesystem path is shared with MPT.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


class MPTClientError(RuntimeError):
    """Raised when the local MoneyPrinterTurbo service is unreachable or a task fails."""


@dataclass(frozen=True)
class VoiceTrack:
    audio_path: Path
    srt_path: Path


class MPTClient:
    """Calls the local `127.0.0.1:<port>` MoneyPrinterTurbo REST API."""

    def __init__(self, base_url: str = "http://127.0.0.1:8080", *, http_client: Any = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = http_client

    @staticmethod
    def build_voice_payload(*, script_text: str, voice_name: str, language: str) -> dict[str, Any]:
        return {
            "video_script": script_text.strip(),
            "video_language": language,
            "voice_name": voice_name,
            "voice_rate": 1.0,
            "voice_volume": 1.0,
            "bgm_type": "",
            "video_source": "local",
            "subtitle_enabled": True,
        }

    def synthesize_voice(
        self,
        *,
        script_text: str,
        voice_name: str,
        language: str,
        dest_dir: Path,
        timeout_s: float = 120.0,
    ) -> VoiceTrack:
        """Generates the voice-over and its SRT, and downloads both into `dest_dir`."""
        payload = self.build_voice_payload(script_text=script_text, voice_name=voice_name, language=language)
        client = self._client or httpx.Client(timeout=30.0)
        try:
            try:
                resp = client.post(f"{self.base_url}/api/v1/subtitle", json=payload)
                resp.raise_for_status()
                task_id = (resp.json().get("data") or {}).get("task_id")
            except Exception as exc:
                raise MPTClientError(f"MPT service unreachable at {self.base_url}: {exc}") from exc
            if not task_id:
                raise MPTClientError(f"MPT did not return a task_id: {resp.text[:300]}")

            deadline = time.monotonic() + timeout_s
            while True:
                st_resp = client.get(f"{self.base_url}/api/v1/tasks/{task_id}")
                st_resp.raise_for_status()
                task = st_resp.json().get("data") or {}
                state = int(task.get("state") or 0)
                if state == 1:  # MPT: 1 = complete, -1 = failed
                    break
                if state < 0:
                    raise MPTClientError(f"MPT voice task {task_id} failed: {task.get('error')}")
                if time.monotonic() > deadline:
                    raise MPTClientError(f"MPT voice task {task_id} timed out after {timeout_s}s")
                time.sleep(1.0)

            dest_dir.mkdir(parents=True, exist_ok=True)
            track = VoiceTrack(audio_path=dest_dir / "voice.mp3", srt_path=dest_dir / "voice.srt")
            for remote_name, local_path in (("audio.mp3", track.audio_path), ("subtitle.srt", track.srt_path)):
                dl = client.get(f"{self.base_url}/api/v1/download/{task_id}/{remote_name}")
                if dl.status_code != 200 or not dl.content:
                    raise MPTClientError(f"MPT voice task {task_id} produced no {remote_name}")
                local_path.write_bytes(dl.content)
            return track
        except httpx.HTTPError as exc:
            raise MPTClientError(f"MPT request failed: {exc}") from exc
        finally:
            if self._client is None:
                client.close()
