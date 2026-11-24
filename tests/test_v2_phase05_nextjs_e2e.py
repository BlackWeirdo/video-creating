"""End-to-end tests for Next.js 15 standalone Studio UI, runtime proxy, and dual-process launcher."""
from __future__ import annotations

import json
import re
import socket
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from videocreator.__main__ import (
    find_node_runtime,
    is_port_available,
    parse_args,
    pick_available_port,
    start_nextjs_standalone,
    stop_nextjs_standalone,
    wait_for_health,
)
from videocreator.app import create_app
from videocreator.db import query_one
from videocreator.paths import APP_NAME, REPO_ROOT, get_paths

pytestmark = pytest.mark.local


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _http_request(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    with opener.open(req, timeout=15.0) as resp:
        return int(resp.status), resp.read()


def test_cli_flags_and_node_runtime() -> None:
    default_args = parse_args([])
    assert default_args.ui_port == 3200
    assert APP_NAME == "VideoCreatorV2"

    args = parse_args(["--ui-port", "3100", "--classic-ui"])
    assert args.ui_port == 3100
    assert args.classic_ui is True

    node_bin = find_node_runtime()
    assert node_bin is not None
    assert Path(node_bin).is_file()

    # Occupied listener port must be detected and skipped by pick_available_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        busy_port = int(occupied.getsockname()[1])
        assert is_port_available("127.0.0.1", busy_port) is False
        chosen = pick_available_port("127.0.0.1", busy_port)
        assert chosen != busy_port
        assert is_port_available("127.0.0.1", chosen) is True


def test_nextjs_standalone_routes_static_and_runtime_proxy_e2e(tmp_path: Path) -> None:
    standalone_server = REPO_ROOT / "web-next" / ".next" / "standalone" / "server.js"
    assert standalone_server.is_file(), f"Missing standalone build at {standalone_server}"

    paths = get_paths(tmp_path / "data")
    api_port = _free_port()
    ui_port = _free_port()
    while ui_port == api_port:
        ui_port = _free_port()
    assert api_port != 8765
    assert ui_port != 3000

    api_base = f"http://127.0.0.1:{api_port}"
    ui_base = f"http://127.0.0.1:{ui_port}"

    app = create_app(paths.data_dir, bind_host="127.0.0.1")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True, name="e2e-uvicorn")
    thread.start()
    ui_proc: Any = None
    try:
        assert wait_for_health(f"{api_base}/health", timeout_s=20.0, server_thread=thread)

        ui_proc = start_nextjs_standalone(
            ui_port,
            api_base,
            boot_log_path=paths.logs_dir / "next_e2e.log",
            host="127.0.0.1",
            timeout_s=25.0,
        )
        assert ui_proc is not None, f"Next.js standalone failed to start; see {paths.logs_dir / 'next_e2e.log'}"

        routes = [
            "/",
            "/trends",
            "/products",
            "/footage",
            "/videos",
            "/videos/1",
            "/video-style",
            "/approval",
            "/studio",
            "/settings",
        ]
        home_html = ""
        for route in routes:
            status, raw = _http_request(f"{ui_base}{route}")
            assert status == 200, f"Unexpected status {status} on Next.js route {route}"
            text = raw.decode("utf-8", errors="replace")
            assert len(text) > 200
            if route == "/":
                home_html = text

        static_match = re.search(r'"(/_next/static/[^"]+\.(?:js|css))"', home_html)
        assert static_match is not None, "No /_next/static asset found in rendered HTML"
        asset_status, asset_bytes = _http_request(f"{ui_base}{static_match.group(1)}")
        assert asset_status == 200
        assert len(asset_bytes) > 50

        # Runtime backend proxy on dynamic port (must NOT hardcode :8765)
        h_status, h_raw = _http_request(f"{ui_base}/api/v1/health")
        assert h_status == 200
        health_payload = json.loads(h_raw.decode("utf-8"))
        assert health_payload["status"] == "ok"
        assert health_payload["api_version"] == "v1"

        create_payload = json.dumps(
            {
                "name": "Studio Next E2E",
                "niche": "jewelry",
                "content_policy": "hybrid_remix",
                "approval_mode": "bulk",
                "default_aspect_ratio": "16:9",
            }
        ).encode("utf-8")
        c_status, c_raw = _http_request(
            f"{ui_base}/api/v1/workspaces",
            method="POST",
            body=create_payload,
            headers={"Content-Type": "application/json", "Origin": ui_base},
        )
        assert c_status == 201
        created = json.loads(c_raw.decode("utf-8"))["workspace"]
        assert created["name"] == "Studio Next E2E"
        assert created["content_policy"] == "hybrid_remix"

        list_status, list_raw = _http_request(f"{ui_base}/api/v1/workspaces")
        assert list_status == 200
        ws_list = json.loads(list_raw.decode("utf-8"))["workspaces"]
        assert any(int(w["id"]) == int(created["id"]) for w in ws_list)

        db_row = query_one(
            paths.db_file,
            "SELECT id, name, content_policy FROM workspaces WHERE id = ?",
            (created["id"],),
        )
        assert db_row is not None
        assert db_row["name"] == "Studio Next E2E"

        # /files runtime proxy
        probe_file = paths.media_dir / "probe.txt"
        probe_file.parent.mkdir(parents=True, exist_ok=True)
        probe_file.write_text("hello-v2-files-proxy", encoding="utf-8")
        f_status, f_raw = _http_request(f"{ui_base}/files/probe.txt")
        assert f_status == 200
        assert f_raw.decode("utf-8") == "hello-v2-files-proxy"

        # V1 classic HTMX route still works side-by-side
        v1_status, v1_raw = _http_request(f"{api_base}/products")
        assert v1_status == 200
        assert len(v1_raw) > 200
    finally:
        stop_nextjs_standalone(ui_proc)
        server.should_exit = True
        thread.join(timeout=5.0)
