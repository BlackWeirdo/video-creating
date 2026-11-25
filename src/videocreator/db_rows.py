"""Shared SQLite row hydration helpers for JSON columns, boolean flags, and `/files/*` URLs."""
from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Mapping
from typing import Any

from videocreator.jsonutil import loads_or


def parse_json_list(raw: Any) -> list[Any]:
    """Parses a JSON array column (or returns `raw` if already a `list`); `[]` on invalid input."""
    if isinstance(raw, list):
        return list(raw)
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def file_media_url(rel_path: Any, *, empty: str | None = "") -> str | None:
    """Builds a `/files/<rel>` URL for stored media paths, returning `empty` when blank or `'pending'`."""
    rel = str(rel_path or "").strip().lstrip("/")
    if not rel or rel == "pending":
        return empty
    return f"/files/{rel}"


def hydrate_row(
    row: Mapping[str, Any],
    *,
    json_fields: Mapping[str, tuple[str, Any]] | None = None,
    bool_fields: Mapping[str, tuple[str, bool]] | Iterable[str] = (),
    media_url_from: tuple[str, str, str | None] | None = None,
) -> dict[str, Any]:
    """Hydrates a raw SQLite row dict into an API-ready dictionary with typed JSON/bool fields."""
    out = dict(row)
    if json_fields:
        for out_key, (col_name, default_val) in json_fields.items():
            raw_val = row.get(col_name)
            parsed = loads_or(raw_val, None)
            out[out_key] = copy.deepcopy(default_val) if parsed is None else parsed

    if isinstance(bool_fields, Mapping):
        for out_key, (col_name, default_bool) in bool_fields.items():
            raw_b = row.get(col_name)
            out[out_key] = default_bool if raw_b is None else bool(int(raw_b))
    else:
        for field_name in bool_fields:
            out[field_name] = bool(int(row.get(field_name) or 0))

    if media_url_from is not None:
        url_key, path_col, empty_default = media_url_from
        out[url_key] = file_media_url(row.get(path_col), empty=empty_default)

    return out
