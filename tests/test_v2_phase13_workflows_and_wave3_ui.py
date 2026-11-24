"""Tests for Phase 13: Visual Workflow Node DAG Engine & Wave 3 Next.js Studio Views."""
from __future__ import annotations

import json
import socket
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

from videocreator.__main__ import (
    start_nextjs_standalone,
    stop_nextjs_standalone,
    wait_for_health,
)
from videocreator.app import create_app
from videocreator.db import query_one
from videocreator.paths import REPO_ROOT, get_paths
from videocreator.pipeline.probe import probe_video

pytestmark = pytest.mark.local


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_workflow_dag_cycle_export_import_and_execute(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        # 1. Seeded starter templates
        templates = client.get("/api/v1/workflows?workspace_id=1").json()["workflows"]
        assert len(templates) >= 3
        assert any(w["is_template"] for w in templates)

        # 2. Cycle and self-loop rejection (400)
        cyc = client.post(
            "/api/v1/workflows",
            json={
                "workspace_id": 1,
                "name": "Cyclic Graph",
                "nodes": [
                    {"id": "a", "data": {"node_kind": "character_node"}},
                    {"id": "b", "data": {"node_kind": "scene_node"}},
                ],
                "edges": [
                    {"id": "e1", "source": "a", "target": "b"},
                    {"id": "e2", "source": "b", "target": "a"},
                ],
            },
        )
        assert cyc.status_code == 400

        self_loop = client.post(
            "/api/v1/workflows",
            json={
                "workspace_id": 1,
                "name": "Self Loop",
                "nodes": [{"id": "a", "data": {"node_kind": "scene_node"}}],
                "edges": [{"id": "e1", "source": "a", "target": "a"}],
            },
        )
        assert self_loop.status_code == 400

        # 3. Create valid Character -> Scene -> Voice -> Render DAG and run synchronously
        ws_res = client.post(
            "/api/v1/workspaces",
            json={"name": "Workflow AI WS", "content_policy": "full_ai"},
        )
        ws_id = int(ws_res.json()["workspace"]["id"])

        dag_nodes = [
            {
                "id": "n_char",
                "type": "character_node",
                "position": {"x": 20, "y": 80},
                "data": {
                    "node_kind": "character_node",
                    "name": "MC An",
                    "appearance_prompt": "Ao vest xam hien dai",
                    "prompt": "Gioi thieu meo chon nhan bac 925 chuan size",
                },
            },
            {
                "id": "n_scene",
                "type": "scene_node",
                "position": {"x": 260, "y": 80},
                "data": {"node_kind": "scene_node"},
            },
            {
                "id": "n_voice",
                "type": "voice_node",
                "position": {"x": 500, "y": 80},
                "data": {"node_kind": "voice_node", "lang": "vi"},
            },
            {
                "id": "n_render",
                "type": "render_node",
                "position": {"x": 740, "y": 80},
                "data": {"node_kind": "render_node", "style_preset": "neon_glow", "aspect_ratio": "9:16"},
            },
        ]
        dag_edges = [
            {"id": "e1", "source": "n_char", "target": "n_scene"},
            {"id": "e2", "source": "n_scene", "target": "n_voice"},
            {"id": "e3", "source": "n_voice", "target": "n_render"},
        ]
        cr = client.post(
            "/api/v1/workflows",
            json={"workspace_id": ws_id, "name": "Character DAG", "nodes": dag_nodes, "edges": dag_edges},
        )
        assert cr.status_code == 201
        wf_id = int(cr.json()["workflow"]["id"])

        # JSON Export / Import round-trip
        exp = client.get(f"/api/v1/workflows/{wf_id}/export")
        assert exp.status_code == 200
        imp = client.post(
            "/api/v1/workflows/import",
            json={"workspace_id": ws_id, "payload": exp.json()},
        )
        assert imp.status_code == 201
        assert len(imp.json()["workflow"]["nodes"]) == 4
        assert len(imp.json()["workflow"]["edges"]) == 3

        # Execute full DAG -> renders real QC-passing MP4
        rn = client.post(
            f"/api/v1/workflows/{wf_id}/run",
            json={"workspace_id": ws_id, "sync": True},
        )
        assert rn.status_code == 200, rn.text
        run_data = rn.json()["run"]
        assert run_data["status"] == "completed"
        vid_id = int(run_data["video_id"])
        v_row = query_one(paths.db_file, "SELECT output_path, qc_json FROM videos WHERE id = ?", (vid_id,))
        assert v_row is not None
        assert json.loads(v_row["qc_json"])["passed"] is True
        assert probe_video(paths.media_dir / str(v_row["output_path"])).duration_s >= 4.8


def test_wave3_nextjs_standalone_views(tmp_path: Path) -> None:
    standalone = REPO_ROOT / "web-next" / ".next" / "standalone" / "server.js"
    assert standalone.is_file(), f"Missing standalone server at {standalone}"

    paths = get_paths(tmp_path / "data")
    api_port = _free_port()
    ui_port = _free_port()
    while ui_port == api_port:
        ui_port = _free_port()

    api_base = f"http://127.0.0.1:{api_port}"
    ui_base = f"http://127.0.0.1:{ui_port}"
    app = create_app(paths.data_dir, bind_host="127.0.0.1")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    ui_proc: Any = None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        assert wait_for_health(f"{api_base}/health", timeout_s=20.0, server_thread=thread)
        ui_proc = start_nextjs_standalone(
            ui_port,
            api_base,
            boot_log_path=paths.logs_dir / "next_w3.log",
            host="127.0.0.1",
            timeout_s=25.0,
        )
        assert ui_proc is not None

        for path in ("/characters", "/news", "/editor", "/workflows", "/freecut"):
            with opener.open(f"{ui_base}{path}", timeout=15.0) as resp:
                assert resp.status == 200
                body = resp.read().decode("utf-8", errors="replace")
                assert len(body) > 150

        for api_path in (
            "/api/v1/characters",
            "/api/v1/news/projects",
            "/api/v1/editor/projects",
            "/api/v1/workflows",
        ):
            with opener.open(f"{ui_base}{api_path}", timeout=15.0) as resp:
                assert resp.status == 200
    finally:
        stop_nextjs_standalone(ui_proc)
        server.should_exit = True
        thread.join(timeout=5.0)
