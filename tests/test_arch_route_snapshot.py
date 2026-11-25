"""Architecture route-table order snapshot & API v1 dependency direction guards."""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any

import pytest
from starlette.routing import Mount, Route

from videocreator.app import create_app
from videocreator.paths import REPO_ROOT

pytestmark = pytest.mark.local

SNAPSHOT_FILE = Path(__file__).resolve().parent / "snapshots" / "routes.json"

# Zero reverse imports from `api/v1` to legacy `api/routes_*` allowed!
TEMPORARY_V1_IMPORTS_ALLOWLIST: frozenset[tuple[str, str]] = frozenset()


def _walk_routes(routes: list[Any], prefix: str = "") -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for route in routes:
        orig_router = getattr(route, "original_router", None)
        sub_routes = getattr(route, "routes", None)
        route_path = getattr(route, "path", "") or ""
        if isinstance(route, Mount):
            entries.append(
                {
                    "kind": "mount",
                    "methods": ["MOUNT"],
                    "path": f"{prefix}{route_path}",
                    "module": type(route.app).__module__,
                }
            )
        elif orig_router is not None:
            ctx = getattr(route, "include_context", None)
            inc_prefix = getattr(ctx, "prefix", None)
            if inc_prefix is None:
                inc_prefix = getattr(orig_router, "prefix", "") or ""
            entries.extend(_walk_routes(list(orig_router.routes), prefix=f"{prefix}{inc_prefix}"))
        elif sub_routes is not None and not isinstance(route, Route):
            entries.extend(_walk_routes(list(sub_routes), prefix=f"{prefix}{route_path}"))
        elif isinstance(route, Route):
            if route_path in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"):
                continue
            methods = sorted(m for m in (route.methods or set()) if m not in ("HEAD", "OPTIONS"))
            entries.append(
                {
                    "kind": "http",
                    "methods": methods,
                    "path": f"{prefix}{route_path}",
                    "module": getattr(route.endpoint, "__module__", ""),
                }
            )
    return entries


def extract_app_route_table(data_dir: Path) -> list[dict[str, Any]]:
    app = create_app(data_dir=data_dir, start_worker=False)
    return _walk_routes(list(app.routes))


def test_fastapi_route_order_matches_snapshot(tmp_path: Path) -> None:
    """Guarantees router splits never drop, duplicate, or reorder registered HTTP routes."""
    assert SNAPSHOT_FILE.is_file(), f"Missing route snapshot at {SNAPSHOT_FILE}"
    expected = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    assert len(expected) >= 150, f"Snapshot suspiciously small ({len(expected)} routes)"
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
