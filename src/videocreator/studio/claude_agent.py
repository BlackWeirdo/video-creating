"""The real Studio agent: one `claude -p` run restricted to file tools inside the session folder (`FR-STD-10`)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from videocreator.ai.budget import record_usage
from videocreator.ai.cli_base import classify_cli_error, find_claude_binary
from videocreator.config import Settings
from videocreator.studio.prompts import SKILLS_DIR

AGENT_TOOLS = "Read,Write,Edit,Glob,Grep"
AGENT_ALLOWED_TOOLS = (
    "Read,Glob,Grep,Write(plan.json),Write(src/Scene.tsx),Edit(plan.json),Edit(src/Scene.tsx)"
)


# (session_dir, prompt, attempt, resume_ref) -> (session_ref, estimated_cost_usd)
CodeGenerator = Callable[[Path, str, int, str | None], tuple[str, float]]


class StudioNotAvailableError(RuntimeError):
    """Raised when Studio cannot run on this machine (no claude CLI, no Node.js)."""


def make_claude_generator(db_file: Path, settings: Settings) -> CodeGenerator:
    """Real generator: one `claude -p` run restricted to file tools inside the session folder."""
    binary = find_claude_binary()
    if not binary:
        raise StudioNotAvailableError("Chưa cài hoặc chưa đăng nhập Claude Code trên máy chủ; Studio không chạy được.")

    def generate(session_dir: Path, prompt: str, attempt: int, resume_ref: str | None) -> tuple[str, float]:
        cmd = [
            binary, "-p",
            "--model", settings.studio.model,
            "--output-format", "json",
            "--permission-mode", "dontAsk",
            "--tools", AGENT_TOOLS,
            "--allowedTools", AGENT_ALLOWED_TOOLS,
            "--strict-mcp-config",
            "--max-budget-usd", f"{settings.studio.max_session_usd:.2f}",
            "--add-dir", str(SKILLS_DIR),
        ]
        if resume_ref:
            cmd.extend(["--resume", resume_ref])
        try:
            proc = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                cwd=str(session_dir), timeout=900, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("Studio agent quá 15 phút không trả lời") from exc
        try:
            payload: dict[str, Any] = json.loads(proc.stdout) if proc.stdout.strip() else {}
        except json.JSONDecodeError:
            payload = {}
        if proc.returncode != 0 or payload.get("is_error"):
            api_status = payload.get("api_error_status")
            raise classify_cli_error(
                "claude_cli", proc.stdout, proc.stderr,
                api_error_status=api_status if isinstance(api_status, int) else None,
                result_text=str(payload.get("result") or ""),
            )
        usage = payload.get("usage") or {}
        record_usage(
            db_file, provider="claude_cli", model=settings.studio.model, kind="studio", route="subscription",
            units_in=int(usage.get("input_tokens") or 0), units_out=int(usage.get("output_tokens") or 0),
            cost_usd=0.0,
        )
        return str(payload.get("session_id") or ""), float(payload.get("total_cost_usd") or 0.0)

    return generate
