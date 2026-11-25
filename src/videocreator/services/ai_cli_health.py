"""Shared Claude CLI health-check service used by `/api/v1/ai/*` and legacy routes."""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from videocreator.ai.cli_base import find_claude_binary
from videocreator.ai.quota import clear_provider_rest, mark_provider_error


def check_claude_cli_health(db_file: Path) -> dict[str, Any]:
    """Checks whether `claude.exe` is installed and accessible on the host machine."""
    binary = find_claude_binary()
    if not binary:
        msg = "Không tìm thấy claude.exe trên máy. Hãy cài @anthropic-ai/claude-code và chạy `claude login`."
        mark_provider_error(db_file, "claude_cli", msg)
        return {"ok": False, "binary": None, "version": None, "message": msg}

    try:
        proc = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            check=False,
        )
        version_str = (proc.stdout or proc.stderr).strip()
        if proc.returncode == 0 and version_str:
            clear_provider_rest(db_file, "claude_cli")
            return {
                "ok": True,
                "binary": binary,
                "version": version_str,
                "message": f"Sẵn sàng: {version_str} ({binary})",
            }
        err = f"claude --version trả mã {proc.returncode}: {version_str}"
        mark_provider_error(db_file, "claude_cli", err)
        return {"ok": False, "binary": binary, "version": None, "message": err}
    except (OSError, subprocess.SubprocessError) as exc:
        err = f"Lỗi kiểm tra claude.exe: {exc}"
        mark_provider_error(db_file, "claude_cli", err)
        return {"ok": False, "binary": binary, "version": None, "message": err}


__all__ = ["check_claude_cli_health"]
