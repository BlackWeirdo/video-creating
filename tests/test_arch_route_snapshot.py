"""Architecture route-table order snapshot & API v1 dependency direction guards."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute, Mount

from videocreator.app import create_app
from videocreator.paths import REPO_ROOT

pytestmark = pytest.mark.local

SNAPSHOT_FILE = Path(__file__).resolve().parent / "snapshots" / "routes.json"

# Emptied in Wave 2 once shared services replace legacy V1 imports.
TEMPORARY_V1_IMPORTS_ALLOWLIST: frozenset[tuple[str, str]] = frozenset(
    {
        ("src/videocreator/api/v1/routes_resources.py", "videocreator.api.routes_assets"),
        ("src/videocreator/api/v1/routes_resources.py", "videocreator.api.routes_voices"),
        ("src/videocreator/api/v1/routes_settings_v1.py", "videocreator.api.routes_settings"),
    }
)


def extract_app_route_table(data_dir: Path) -> list[dict[str, Any]]:
    app = create_app(data_dir=data_dir, start_worker=False)
    entries: list[dict[str, Any]] = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            methods = sorted(m for m in (route.methods or set()) if m not in ("HEAD", "OPTIONS"))
            entries.append(
                {
                    "kind": "http",
                    "methods": methods,
                    "path": route.path,
                    "module": getattr(route.endpoint, "__module__", ""),
                }
            )
        elif isinstance(route, Mount):
            entries.append(
                {
                    "kind": "mount",
                    "methods": ["MOUNT"],
                    "path": route.path,
                    "module": type(route.app).__module__,
                }
            )
    return entries


def test_fastapi_route_order_matches_snapshot(tmp_path: Path) -> None:
    """Guarantees router splits never drop, duplicate, or reorder registered HTTP routes."""
    assert SNAPSHOT_FILE.is_file(), f"Missing route snapshot at {SNAPSHOT_FILE}"
    expected = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    actual = extract_app_route_table(tmp_path / "snap_data")

    exp_sig = [(e["kind"], e["methods"], e["path"]) for e in expected]
    act_sig = [(e["kind"], e["methods"], e["path"]) for e in actual]
    assert act_sig == exp_sig, (
        f"Route table drifted! Expected {len(exp_sig)} routes, got {len(act_sig)}.\n"
        f"Added: {[x for x in act_sig if x not in exp_sig]}\n"
        f"Removed: {[x for x in exp_sig if x not in act_sig]}"
    )


def test_api_v1_does_not_import_legacy_v1_routes() -> None:
    """`src/videocreator/api/v1/*` must not depend on legacy `videocreator.api.routes_*` HTML routers."""
    v1_dir = REPO_ROOT / "src" / "videocreator" / "api" / "v1"
    violations: list[str] = []
    for py_file in sorted(v1_dir.rglob("*.py")):
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith("videocreator.api.routes_"):
                    if (rel, node.module) not in TEMPORARY_V1_IMPORTS_ALLOWLIST:
                        violations.append(f"{rel}:{node.lineno} -> {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("videocreator.api.routes_"):
                        if (rel, alias.name) not in TEMPORARY_V1_IMPORTS_ALLOWLIST:
                            violations.append(f"{rel}:{node.lineno} -> {alias.name}")
    assert violations == [], "Forbidden api/v1 -> legacy V1 route imports:\n" + "\n".join(violations)
