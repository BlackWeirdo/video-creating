"""Workflow CRUD persistence and JSON import/export."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.db_rows import hydrate_row
from videocreator.paths import AppPaths
from videocreator.pipeline.workflows.dag import topological_sort_workflow
from videocreator.workspaces import require_workspace


def hydrate_workflow(row: dict[str, Any]) -> dict[str, Any]:
    return hydrate_row(
        row,
        json_fields={"nodes": ("nodes_json", []), "edges": ("edges_json", [])},
        bool_fields=("is_template",),
    )


def list_workflows(db_file: Path, *, workspace_id: int) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        """
        SELECT * FROM workflows
        WHERE workspace_id = ? OR is_template = 1
        ORDER BY is_template DESC, id DESC
        """,
        (int(workspace_id),),
    )
    return [hydrate_workflow(r) for r in rows]


def get_workflow(db_file: Path, workflow_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM workflows WHERE id = ?", (int(workflow_id),))
    return hydrate_workflow(row) if row else None


def create_workflow(
    paths: AppPaths,
    *,
    workspace_id: int,
    name: str,
    description: str = "",
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    is_template: bool = False,
    actor: str = "api",
) -> dict[str, Any]:
    require_workspace(paths.db_file, workspace_id)
    clean_name = (name or "").strip()
    if not clean_name:
        raise ValueError("Workflow name is required")
    topological_sort_workflow(nodes, edges)

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO workflows (
                workspace_id, name, description, nodes_json, edges_json, is_template
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(workspace_id),
                clean_name,
                (description or "").strip(),
                json.dumps(nodes, ensure_ascii=False),
                json.dumps(edges, ensure_ascii=False),
                1 if is_template else 0,
            ),
        )
        wf_id = int(cur.lastrowid)
        record_audit(
            conn,
            actor=actor,
            action="create_workflow",
            object_type="workflow",
            object_id=wf_id,
            detail=f"{clean_name} ({len(nodes)} nodes)",
        )
    wf = get_workflow(paths.db_file, wf_id)
    assert wf is not None
    return wf


def update_workflow(
    paths: AppPaths,
    workflow_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    nodes: list[dict[str, Any]] | None = None,
    edges: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    existing = get_workflow(paths.db_file, workflow_id)
    if existing is None:
        return None
    next_nodes = nodes if nodes is not None else existing["nodes"]
    next_edges = edges if edges is not None else existing["edges"]
    topological_sort_workflow(next_nodes, next_edges)

    sets: list[str] = ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: list[Any] = []
    if name is not None and name.strip():
        sets.append("name = ?")
        params.append(name.strip())
    if description is not None:
        sets.append("description = ?")
        params.append(description.strip())
    if nodes is not None:
        sets.append("nodes_json = ?")
        params.append(json.dumps(next_nodes, ensure_ascii=False))
    if edges is not None:
        sets.append("edges_json = ?")
        params.append(json.dumps(next_edges, ensure_ascii=False))
    params.append(int(workflow_id))
    with get_conn(paths.db_file) as conn:
        conn.execute(f"UPDATE workflows SET {', '.join(sets)} WHERE id = ?", params)
    return get_workflow(paths.db_file, workflow_id)


def delete_workflow(paths: AppPaths, workflow_id: int) -> bool:
    existing = get_workflow(paths.db_file, workflow_id)
    if existing is None:
        return False
    with get_conn(paths.db_file) as conn:
        conn.execute("DELETE FROM workflows WHERE id = ?", (int(workflow_id),))
    return True


def export_workflow_json(db_file: Path, workflow_id: int) -> dict[str, Any]:
    wf = get_workflow(db_file, workflow_id)
    if wf is None:
        raise ValueError(f"Workflow #{workflow_id} not found")
    return {
        "schema_version": 2,
        "name": wf["name"],
        "description": wf["description"],
        "nodes": wf["nodes"],
        "edges": wf["edges"],
    }


def import_workflow_json(
    paths: AppPaths, workspace_id: int, payload: dict[str, Any]
) -> dict[str, Any]:
    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("Invalid workflow JSON: 'nodes' and 'edges' must be lists")
    return create_workflow(
        paths,
        workspace_id=workspace_id,
        name=str(payload.get("name") or "Imported Workflow"),
        description=str(payload.get("description") or ""),
        nodes=nodes,
        edges=edges,
        actor="import",
    )
