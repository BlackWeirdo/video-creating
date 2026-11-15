"""Tolerant readers for JSON stored in text columns: a missing or broken value becomes the default."""
from __future__ import annotations

import json
from typing import Any


def loads_or(raw: Any, default: Any) -> Any:
    """`json.loads(raw)`, or `default` when `raw` is empty or not valid JSON."""
    if not raw:
        return default
    try:
        return json.loads(str(raw))
    except Exception:
        return default


def parse_int_list(raw: Any) -> list[int]:
    """A JSON array of integers (e.g. `product_ids_json`); `[]` when empty or malformed."""
    try:
        return [int(x) for x in json.loads(str(raw or "[]"))]
    except Exception:
        return []


def parse_str_list(raw: Any) -> list[str]:
    """A JSON array of strings (e.g. `tags_json`); `[]` when empty or malformed."""
    try:
        return [str(x) for x in json.loads(str(raw or "[]"))]
    except Exception:
        return []
