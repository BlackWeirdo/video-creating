"""End-to-end topological workflow execution and background job runner."""
from __future__ import annotations

import json
import shutil
from typing import Any

from videocreator.db import get_conn, record_audit
from videocreator.job_store import report_active_job_progress
from videocreator.muse_gateway.studio_bridge import MuseMediaPendingError
from videocreator.paths import AppPaths
from videocreator.pipeline.compute_job import run_studio_project_job
from videocreator.pipeline.workflows.dag import node_kind, topological_sort_workflow
from videocreator.pipeline.workflows.node_runners import (
    NODE_RUNNERS,
    WorkflowExecState,
    run_scene_node,
)
from videocreator.pipeline.workflows.store import get_workflow
from videocreator.workspaces import require_workspace


def execute_workflow(
    paths: AppPaths,
    workflow_id: int,
    *,
    workspace_id_override: int | None = None,
) -> dict[str, Any]:
    """Topologically executes a workflow DAG end-to-end and returns the workflow run record."""
    wf = get_workflow(paths.db_file, workflow_id)
    if wf is None:
        raise ValueError(f"Workflow #{workflow_id} not found")

    ws_id = int(workspace_id_override or wf["workspace_id"])
    ws = require_workspace(paths.db_file, ws_id)
    policy = str(ws.get("content_policy") or "strict_footage")
    ordered, parents_map = topological_sort_workflow(wf["nodes"], wf["edges"])

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            "INSERT INTO workflow_runs (workflow_id, workspace_id, status) VALUES (?, ?, 'running')",
            (int(workflow_id), ws_id),
        )
        run_id = int(cur.lastrowid)

    work_dir = paths.work_dir / f"workflow_{workflow_id}_run_{run_id}"
    work_dir.mkdir(parents=True, exist_ok=True)
    node_outputs: dict[str, Any] = {}
    st = WorkflowExecState(
        paths=paths,
        workflow_id=int(workflow_id),
        wf=wf,
        ws_id=ws_id,
        ws=ws,
        policy=policy,
        work_dir=work_dir,
    )

    try:
        total_nodes = max(1, len(ordered))
        for n_idx, node in enumerate(ordered, start=1):
            nid = str(node["id"])
            kind = node_kind(node)
            report_active_job_progress(
                0.08 + 0.85 * ((n_idx - 1) / total_nodes),
                f"Đang chạy nút {n_idx}/{total_nodes}: {kind} ({nid})",
            )
            data = dict(node.get("data") or {})
            upstream = [node_outputs[p] for p in parents_map[nid] if p in node_outputs]
            runner = NODE_RUNNERS.get(kind, run_scene_node)
            node_outputs[nid] = runner(st, nid, data, upstream)

        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                UPDATE workflow_runs
                SET status = 'completed', waiting_media = 0, node_outputs_json = ?, video_id = ?, error = NULL
                WHERE id = ?
                """,
                (json.dumps(node_outputs, ensure_ascii=False), st.final_video_id, run_id),
            )
            conn.execute(
                "UPDATE workflows SET last_status = 'completed', last_video_id = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
                (st.final_video_id, int(workflow_id)),
            )
            record_audit(
                conn,
                actor="workflow",
                action="execute_workflow",
                object_type="workflow_run",
                object_id=run_id,
                detail=f"wf #{workflow_id} -> video #{st.final_video_id}",
            )
        return {
            "id": run_id,
            "workflow_id": int(workflow_id),
            "workspace_id": ws_id,
            "status": "completed",
            "video_id": st.final_video_id,
            "node_outputs": node_outputs,
        }
    except MuseMediaPendingError as pending_exc:
        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                UPDATE workflow_runs
                SET waiting_media = 1, node_outputs_json = ?, error = ?
                WHERE id = ?
                """,
                (json.dumps(node_outputs, ensure_ascii=False), str(pending_exc)[:300], run_id),
            )
            conn.execute(
                "UPDATE workflows SET last_status = 'waiting_media', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
                (int(workflow_id),),
            )
        return {
            "id": run_id,
            "workflow_id": int(workflow_id),
            "workspace_id": ws_id,
            "status": "waiting_media",
            "video_id": None,
            "node_outputs": node_outputs,
        }
    except Exception as exc:
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE workflow_runs SET status = 'failed', error = ? WHERE id = ?",
                (str(exc)[:400], run_id),
            )
            conn.execute(
                "UPDATE workflows SET last_status = 'failed', updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?",
                (int(workflow_id),),
            )
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def run_workflow_job(paths: AppPaths, workflow_id: int) -> str:
    return run_studio_project_job(execute_workflow, paths, workflow_id)
