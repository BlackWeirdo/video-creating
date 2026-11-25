"""Centralized path-traversal guards and upload filename/extension sanitizers (NFR-SEC-05)."""
from __future__ import annotations

import re
from collections.abc import Collection
from pathlib import Path

_SAFE_STEM_RE = re.compile(r"[^a-zA-Z0-9._-]+")


class UnsafePathError(ValueError):
    """Raised when a relative path attempts to escape its permitted root directory."""


def resolve_within(root: Path, rel_subpath: str | Path) -> Path:
    """Resolves `rel_subpath` strictly inside `root`, raising `UnsafePathError` on traversal."""
    root_resolved = root.resolve()
    raw_str = str(rel_subpath or "").replace("\\", "/").strip().lstrip("/")
    rel_obj = Path(raw_str)
    if ".." in rel_obj.parts or rel_obj.is_absolute():
        raise UnsafePathError("Path traversal forbidden")
    target = (root_resolved / rel_obj).resolve()
    if not target.is_relative_to(root_resolved):
        raise UnsafePathError("Resolved path escapes root directory")
    return target


def is_strictly_within(parent: Path, candidate: Path) -> bool:
    """Returns True iff `candidate` resolves to a descendant strictly inside `parent`."""
    try:
        parent_res = parent.resolve()
        cand_res = candidate.resolve()
        return cand_res != parent_res and cand_res.is_relative_to(parent_res)
    except OSError:
        return False


def safe_upload_stem(filename: str | None, fallback: str = "upload") -> str:
    """Extracts a clean filesystem-safe stem from an untrusted upload filename."""
    raw_name = Path(filename or fallback).name
    stem = Path(raw_name).stem
    cleaned = _SAFE_STEM_RE.sub("_", stem).strip("._-")
    return cleaned[:80] if cleaned else fallback


def validated_extension(
    filename: str | None,
    allowed_extensions: Collection[str],
    *,
    default_ext: str = "",
) -> str:
    """Validates and returns the lowercase `.ext` of `filename` against `allowed_extensions`."""
    raw_name = Path(filename or "").name
    ext = Path(raw_name).suffix.lower() or default_ext.lower()
    normalized_allowed = {e.lower() for e in allowed_extensions}
    if not ext or ext not in normalized_allowed:
        raise ValueError(f"Định dạng tệp không hợp lệ: '{ext or raw_name}'")
    return ext
