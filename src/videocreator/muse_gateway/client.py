"""Synchronous HTTP client for Muse Gateway `/v1/*` public endpoints and safe media downloads."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from videocreator.config_ai import MuseGatewayConfig
from videocreator.muse_gateway.errors import (
    MuseAuthError,
    MuseGatewayError,
    MuseInputError,
    MuseQuotaWait,
    MuseUnavailable,
    MuseUnsafeGatewayError,
)
from videocreator.muse_gateway.security import (
    assert_hardened_config_payload,
    assert_trusted_media_url,
    sanitize_prompt,
    validate_gateway_base_url,
)
from videocreator.secrets_store import SecretsStore

MAX_MUSE_MEDIA_DOWNLOAD_BYTES = 300 * 1024 * 1024  # 300 MB


def _extract_error_message(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])
            if isinstance(err, str) and err:
                return err
            if data.get("message"):
                return str(data["message"])
    except ValueError:
        pass
    return (resp.text or f"HTTP {resp.status_code}")[:300]


class MuseGatewayClient:
    """Typed client for Muse Gateway `/v1/*` + health/safety probes."""

    def __init__(
        self,
        cfg: MuseGatewayConfig,
        secrets: SecretsStore | None = None,
        *,
        api_key_override: str | None = None,
        timeout_s: float = 60.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.cfg = cfg
        self.base_url = validate_gateway_base_url(cfg.base_url, cfg.mode)
        self.api_key = (
            api_key_override
            if api_key_override is not None
            else ((secrets.get("MUSE_GATEWAY_API_KEY") or "").strip() if secrets else "")
        )
        self.timeout_s = timeout_s
        self._external_client = http_client

    def _headers(self, *, include_auth: bool = True) -> dict[str, str]:
        hdrs = {"Accept": "application/json"}
        if include_auth and self.api_key:
            hdrs["Authorization"] = f"Bearer {self.api_key}"
        return hdrs

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        include_auth: bool = True,
        timeout_s: float | None = None,
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        client = self._external_client
        own = client is None
        if client is None:
            client = httpx.Client(timeout=timeout_s or self.timeout_s, trust_env=False)
        try:
            try:
                resp = client.request(
                    method,
                    url,
                    headers=self._headers(include_auth=include_auth),
                    json=json_body,
                    timeout=timeout_s or self.timeout_s,
                )
            except httpx.RequestError as exc:
                raise MuseUnavailable(f"Không kết nối được Muse Gateway ({self.base_url}): {exc}") from exc

            if resp.status_code in (401, 403):
                raise MuseAuthError(
                    f"Muse Gateway từ chối xác thực ({resp.status_code}): {_extract_error_message(resp)}"
                )
            if resp.status_code == 429:
                raise MuseQuotaWait(
                    f"Muse Gateway giới hạn tần suất (429): {_extract_error_message(resp)}",
                    retry_after_s=1800,
                )
            if resp.status_code == 400:
                raise MuseInputError(_extract_error_message(resp))
            if resp.status_code >= 500:
                raise MuseUnavailable(
                    f"Muse Gateway lỗi máy chủ ({resp.status_code}): {_extract_error_message(resp)}"
                )
            if resp.status_code >= 400:
                raise MuseGatewayError(
                    f"Muse Gateway HTTP {resp.status_code}: {_extract_error_message(resp)}"
                )
            return resp
        finally:
            if own:
                client.close()

    def health(self) -> dict[str, Any]:
        resp = self._request("GET", "/api/health", include_auth=False, timeout_s=8.0)
        data = resp.json()
        return data if isinstance(data, dict) else {"ok": False}

    def discover(self) -> dict[str, Any]:
        resp = self._request("GET", "/api/pair", include_auth=False, timeout_s=8.0)
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def get_config(self) -> dict[str, Any]:
        resp = self._request("GET", "/api/config", include_auth=False, timeout_s=8.0)
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def verify_ready_and_safe(self) -> dict[str, Any]:
        """Verifies `/api/health` is up AND enforces `vc-hardened` (`cmdMode == 'off'`)."""
        h = self.health()
        if not h.get("ok"):
            raise MuseUnavailable("Muse Gateway /api/health reported not ok")
        if self.cfg.mode == "local_sidecar":
            cfg_payload = self.get_config()
            assert_hardened_config_payload(cfg_payload)
            return {"health": h, "hardened": True, "fork": cfg_payload.get("fork", "vc-hardened")}
        if not self.cfg.remote_hardened_confirmed:
            raise MuseUnsafeGatewayError(
                "Chế độ remote yêu cầu xác nhận gateway từ xa đã chạy bản vc-hardened (MUSE_CMD_MODE=off)."
            )
        return {"health": h, "hardened": True, "fork": "remote-confirmed"}

    def list_models(self) -> list[dict[str, Any]]:
        resp = self._request("GET", "/v1/models", timeout_s=15.0)
        data = resp.json()
        items = data.get("data") if isinstance(data, dict) else []
        return [m for m in (items or []) if isinstance(m, dict)]

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = dict(payload)
        body["prompt"] = sanitize_prompt(str(body.get("prompt") or ""))
        if not body["prompt"]:
            raise MuseInputError("Muse task prompt cannot be empty")
        resp = self._request("POST", "/v1/tasks", json_body=body, timeout_s=45.0)
        data = resp.json()
        if not isinstance(data, dict) or not data.get("id"):
            raise MuseGatewayError("Muse Gateway /v1/tasks returned invalid task object")
        return data

    def get_task(self, gateway_task_id: str) -> dict[str, Any]:
        clean_id = (gateway_task_id or "").strip()
        if not clean_id:
            raise MuseInputError("gateway_task_id is required")
        resp = self._request("GET", f"/v1/tasks/{clean_id}", timeout_s=20.0)
        data = resp.json()
        if not isinstance(data, dict):
            raise MuseGatewayError("Invalid task response")
        return data

    def list_tasks(self, *, limit: int = 100) -> list[dict[str, Any]]:
        capped = max(1, min(100, int(limit)))
        resp = self._request("GET", f"/v1/tasks?limit={capped}", timeout_s=25.0)
        data = resp.json()
        rows = data.get("data") if isinstance(data, dict) else []
        return [r for r in (rows or []) if isinstance(r, dict)]

    def cancel_task(self, gateway_task_id: str) -> dict[str, Any]:
        clean_id = (gateway_task_id or "").strip()
        resp = self._request("DELETE", f"/v1/tasks/{clean_id}", timeout_s=15.0)
        data = resp.json()
        return data if isinstance(data, dict) else {"id": clean_id, "status": "cancelled"}

    def generate_images(
        self,
        *,
        prompt: str,
        model: str = "muse-image",
        n: int = 1,
        size: str = "1024x1792",
        response_format: str = "b64_json",
    ) -> dict[str, Any]:
        clean_prompt = sanitize_prompt(prompt)
        if not clean_prompt:
            raise MuseInputError("Image prompt is required")
        resp = self._request(
            "POST",
            "/v1/images/generations",
            json_body={
                "model": model or "muse-image",
                "prompt": clean_prompt,
                "n": max(1, min(4, int(n))),
                "size": size,
                "response_format": response_format,
            },
            timeout_s=180.0,
        )
        data = resp.json()
        return data if isinstance(data, dict) else {"data": []}

    def synthesize_speech(
        self,
        *,
        text: str,
        model: str = "muse-voice",
        voice: str | None = None,
        language: str | None = None,
        speed: float | None = None,
    ) -> bytes:
        clean_text = sanitize_prompt(text)
        if not clean_text:
            raise MuseInputError("Speech input text is required")
        body: dict[str, Any] = {
            "model": model or "muse-voice",
            "input": clean_text,
        }
        if voice:
            body["voice"] = voice
        if language:
            body["language"] = language
        if speed is not None:
            body["speed"] = float(speed)
        resp = self._request("POST", "/v1/audio/speech", json_body=body, timeout_s=180.0)
        if not resp.content:
            raise MuseGatewayError("Muse Gateway returned empty audio bytes")
        return bytes(resp.content)

    def chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        model: str = "muse-chat",
        response_format: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        sanitized_msgs: list[dict[str, Any]] = []
        for msg in messages:
            entry = dict(msg)
            if isinstance(entry.get("content"), str):
                entry["content"] = sanitize_prompt(entry["content"])
            sanitized_msgs.append(entry)
        body: dict[str, Any] = {
            "model": model or "muse-chat",
            "messages": sanitized_msgs,
            "stream": False,
        }
        if response_format is not None:
            body["response_format"] = response_format
        resp = self._request("POST", "/v1/chat/completions", json_body=body, timeout_s=120.0)
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def download_media_to_file(
        self,
        media_url: str,
        dest_path: Path,
        *,
        max_bytes: int = MAX_MUSE_MEDIA_DOWNLOAD_BYTES,
    ) -> Path:
        trusted_url = assert_trusted_media_url(media_url, self.base_url)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_part = dest_path.with_suffix(dest_path.suffix + ".part")
        client = self._external_client
        own = client is None
        if client is None:
            client = httpx.Client(timeout=120.0, trust_env=False)
        try:
            try:
                with client.stream(
                    "GET", trusted_url, headers=self._headers(include_auth=False)
                ) as resp:
                    if resp.status_code >= 400:
                        raise MuseGatewayError(
                            f"Media download failed ({resp.status_code}) for {trusted_url}"
                        )
                    total = 0
                    with tmp_part.open("wb") as fh:
                        for chunk in resp.iter_bytes(chunk_size=256 * 1024):
                            total += len(chunk)
                            if total > max_bytes:
                                raise MuseInputError(
                                    f"Muse media file exceeds max size ({max_bytes} bytes)"
                                )
                            fh.write(chunk)
            except httpx.RequestError as exc:
                tmp_part.unlink(missing_ok=True)
                raise MuseUnavailable(f"Lỗi tải media từ Muse Gateway: {exc}") from exc
            except BaseException:
                tmp_part.unlink(missing_ok=True)
                raise
        finally:
            if own:
                client.close()
        tmp_part.replace(dest_path)
        return dest_path


__all__ = ["MAX_MUSE_MEDIA_DOWNLOAD_BYTES", "MuseGatewayClient"]
