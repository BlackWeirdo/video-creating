"""Subscription CLI provider (`claude_cli`) via `claude.exe -p` (Phase 18)."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from videocreator.ai.base import (
    AIError,
    ProviderAuthError,
    ProviderQuotaExhausted,
    RouteKind,
    SchemaValidationError,
    T,
)
from videocreator.ai.budget import record_usage
from videocreator.ai.cli_base import (
    classify_cli_error,
    find_claude_binary,
    pydantic_to_strict_json_schema,
)
from videocreator.pipeline.probe import probe_video
from videocreator.pipeline.thumbs import extract_thumbnail


class ClaudeCLIProvider:
    """Implements `AIProvider` using the owner's Claude subscription via `claude.exe -p`."""

    name: str = "claude_cli"
    route_kind: RouteKind = "subscription"

    def __init__(
        self,
        db_file: Path,
        *,
        role: str = "writer",
        model: str = "sonnet",
        timeout_s: int = 300,
    ) -> None:
        self.db_file = db_file
        self.role = role
        self.model = model
        self.timeout_s = timeout_s

    def _run_claude(
        self,
        prompt: str,
        schema: type[T],
        workdir: Path,
        *,
        allow_read: bool = False,
    ) -> T:
        binary = find_claude_binary()
        if not binary:
            raise ProviderAuthError(
                self.name,
                "claude CLI binary not found on this machine. Install @anthropic-ai/claude-code and sign in.",
            )

        strict_schema = pydantic_to_strict_json_schema(schema)
        cmd: list[str] = [
            binary,
            "-p",
            "--model",
            self.model,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(strict_schema, ensure_ascii=False),
            "--permission-mode",
            "dontAsk",
        ]
        if allow_read:
            cmd.extend(["--allowedTools", "Read"])

        last_err: Exception | None = None
        for attempt in range(2):
            try:
                proc = subprocess.run(
                    cmd,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=str(workdir),
                    timeout=self.timeout_s,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise AIError(f"claude_cli timed out after {self.timeout_s}s") from exc

            try:
                payload: dict[str, Any] = json.loads(proc.stdout) if proc.stdout.strip() else {}
            except json.JSONDecodeError:
                payload = {}

            is_error = bool(payload.get("is_error")) or proc.returncode != 0
            api_status = payload.get("api_error_status")
            result_str = str(payload.get("result") or "")

            if is_error:
                raise classify_cli_error(
                    self.name,
                    proc.stdout,
                    proc.stderr,
                    api_error_status=int(api_status) if isinstance(api_status, int) else None,
                    result_text=result_str,
                )

            raw_structured = payload.get("structured_output")
            if raw_structured is None and result_str.strip().startswith("{"):
                try:
                    raw_structured = json.loads(result_str)
                except json.JSONDecodeError:
                    raw_structured = None

            usage = payload.get("usage") or {}
            units_in = int(usage.get("input_tokens") or 0)
            units_out = int(usage.get("output_tokens") or 0)

            try:
                validated = schema.model_validate(raw_structured)
                record_usage(
                    self.db_file,
                    provider=self.name,
                    model=self.model,
                    kind=self.role,
                    route="subscription",
                    units_in=units_in,
                    units_out=units_out,
                    cost_usd=0.0,
                )
                return validated
            except ValidationError as val_exc:
                last_err = val_exc
                if attempt == 0:
                    continue
                raise SchemaValidationError(
                    f"claude_cli structured_output failed schema validation after 2 attempts: {val_exc}"
                ) from val_exc

        raise SchemaValidationError(f"claude_cli validation failed: {last_err}")

    def describe_video(
        self,
        video: Path,
        prompt: str,
        schema: type[T],
        *,
        thumbnails: list[Path] | None = None,
    ) -> T:
        workdir = Path(tempfile.mkdtemp(prefix="vc-claude-vis-"))
        try:
            staged_names: list[str] = []
            if thumbnails:
                for idx, thumb in enumerate(thumbnails, start=1):
                    if thumb.exists():
                        dest_name = f"shot_{idx:03d}.jpg"
                        shutil.copy2(thumb, workdir / dest_name)
                        staged_names.append(dest_name)
            if not staged_names and video.exists():
                info = probe_video(video)
                mid_s = max(0.0, info.duration_s / 2.0)
                dest_name = "shot_001.jpg"
                extract_thumbnail(video, mid_s, workdir / dest_name)
                staged_names.append(dest_name)

            file_list_str = ", ".join(staged_names)
            augmented_prompt = (
                f"Đọc các file ảnh thu nhỏ trong thư mục hiện tại theo đúng thứ tự: {file_list_str}.\n"
                f"{prompt}"
            )
            return self._run_claude(augmented_prompt, schema, workdir, allow_read=True)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def generate_json(self, prompt: str, schema: type[T]) -> T:
        workdir = Path(tempfile.mkdtemp(prefix="vc-claude-gen-"))
        try:
            return self._run_claude(prompt, schema, workdir, allow_read=False)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
