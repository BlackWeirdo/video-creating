"""Allowlist of shell commands a Studio agent may run (`FR-STD-10`)."""
from __future__ import annotations

import shlex
from pathlib import Path

ALLOWED_COMMAND_PREFIXES: tuple[tuple[str, ...], ...] = (
    ("rea-video", "decompose"),
    ("rea-video", "apply-review"),
    ("rea-video", "assemble"),
    ("ffmpeg",),
    ("ffprobe",),
    ("node",),
    ("npx", "remotion"),
    ("npm", "ci"),
    ("uv", "run"),
)


FORBIDDEN_COMMAND_TOKENS: frozenset[str] = frozenset(
    {
        "remake-run",
        "capsule-cinema",
        "curl",
        "wget",
        "invoke-webrequest",
        "iwr",
        "powershell",
        "pwsh",
        "cmd.exe",
        "rm",
        "del",
        "rmdir",
    }
)


def validate_shell_command_allowed(command_line: str) -> bool:
    """Enforces the strict Studio shell command allowlist (`FR-STD-10`)."""
    raw = (command_line or "").strip()
    if not raw:
        return False
    # Reject shell chaining / redirection operators
    if any(op in raw for op in ("&&", "||", ";", "|", ">", "<", "`", "$(")):
        return False

    try:
        tokens = shlex.split(raw, posix=False)
    except ValueError:
        return False
    if not tokens:
        return False

    lower_tokens = [t.strip("\"'").lower() for t in tokens]
    for tok in lower_tokens:
        if tok in FORBIDDEN_COMMAND_TOKENS:
            return False
        if ".." in tok:
            return False

    prog = Path(lower_tokens[0]).stem
    normalized = (prog, *lower_tokens[1:])
    for allowed_prefix in ALLOWED_COMMAND_PREFIXES:
        if normalized[: len(allowed_prefix)] == allowed_prefix:
            return True
    return False
