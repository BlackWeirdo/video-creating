"""Local AI models catalog queries, disk installation checks, and DB state updates."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all, query_one
from videocreator.db_rows import parse_json_list
from videocreator.paths import AppPaths


def _find_missing_python_pkgs(pkgs: list[str]) -> list[str]:
    missing: list[str] = []
    for pkg in pkgs:
        clean = str(pkg).strip()
        if not clean:
            continue
        try:
            if importlib.util.find_spec(clean) is None:
                missing.append(clean)
        except Exception:
            missing.append(clean)
    return missing


def _check_installed_on_disk(local_path: str, files: list[dict[str, Any]]) -> bool:
    if not local_path:
        return False
    p = Path(local_path)
    if not p.exists():
        return False
    if p.is_dir() and files:
        return all(
            (p / str(f.get("filename") or "")).is_file()
            for f in files
            if f.get("filename")
        )
    return True


def model_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    local_path = str(row.get("local_path") or "")
    files_raw = parse_json_list(row.get("files_json"))
    files: list[dict[str, Any]] = [f for f in files_raw if isinstance(f, dict)]
    req_pkgs = [
        str(x) for x in parse_json_list(row.get("requires_python_pkgs")) if str(x).strip()
    ]
    missing_pkgs = _find_missing_python_pkgs(req_pkgs)
    exists_on_disk = _check_installed_on_disk(local_path, files)
    return {
        "rowid": int(row["rowid"]) if row.get("rowid") is not None else 0,
        "model_id": str(row["model_id"]),
        "name": str(row["name"]),
        "category": str(row["category"]),
        "size_mb": int(row.get("size_mb") or 0),
        "status": str(row["status"]),
        "local_path": local_path,
        "installed_on_disk": exists_on_disk,
        "sha256": str(row.get("sha256") or ""),
        "download_url": str(row.get("download_url") or ""),
        "files": files,
        "license": str(row.get("license") or ""),
        "requires_python_pkgs": req_pkgs,
        "missing_python_pkgs": missing_pkgs,
        "smoke_tested": bool(int(row.get("smoke_tested") or 0)),
        "progress": float(row.get("progress") or 0.0),
        "error": row.get("error"),
        "updated_at": str(row.get("updated_at") or ""),
    }


def list_local_models(paths: AppPaths) -> list[dict[str, Any]]:
    rows = query_all(
        paths.db_file,
        "SELECT rowid, * FROM local_models ORDER BY category ASC, model_id ASC",
    )
    return [model_row_to_dict(r) for r in rows]


def get_local_model(paths: AppPaths, model_id: str) -> dict[str, Any] | None:
    row = query_one(
        paths.db_file,
        "SELECT rowid, * FROM local_models WHERE model_id = ?",
        (model_id,),
    )
    return model_row_to_dict(row) if row else None


def get_local_model_by_rowid(paths: AppPaths, rowid: int) -> dict[str, Any] | None:
    row = query_one(
        paths.db_file,
        "SELECT rowid, * FROM local_models WHERE rowid = ?",
        (int(rowid),),
    )
    return model_row_to_dict(row) if row else None


def set_model_state(
    paths: AppPaths,
    model_id: str,
    *,
    status: str,
    progress: float | None = None,
    local_path: str | None = None,
    sha256: str | None = None,
    smoke_tested: bool | None = None,
    error: str | None = "",
) -> None:
    sets = ["status = ?", "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: list[Any] = [status]
    if progress is not None:
        sets.append("progress = ?")
        params.append(float(progress))
    if local_path is not None:
        sets.append("local_path = ?")
        params.append(local_path)
    if sha256 is not None:
        sets.append("sha256 = ?")
        params.append(sha256)
    if smoke_tested is not None:
        sets.append("smoke_tested = ?")
        params.append(1 if smoke_tested else 0)
    if error != "":
        sets.append("error = ?")
        params.append(error)
    params.append(model_id)
    with get_conn(paths.db_file) as conn:
        conn.execute(f"UPDATE local_models SET {', '.join(sets)} WHERE model_id = ?", params)
