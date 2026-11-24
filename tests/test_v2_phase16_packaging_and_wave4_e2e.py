"""Tests for Phase 16: Wave 4 Next.js Studio Views & Windows Inno Setup V2 Packaging."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from videocreator.__main__ import start_nextjs_standalone, stop_nextjs_standalone, wait_for_health
from videocreator.app import create_app
from videocreator.paths import REPO_ROOT, find_ffmpeg_binary, find_node_runtime, get_paths

pytestmark = pytest.mark.local


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _get(url: str) -> tuple[int, bytes]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(urllib.request.Request(url), timeout=15.0) as resp:
        return int(resp.status), resp.read()


def _find_iscc() -> Path | None:
    cmd = shutil.which("ISCC.exe")
    if cmd:
        return Path(cmd)
    for cand in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    ):
        if cand.is_file():
            return cand
    return None


def test_windows_v2_packaging_artifacts_and_exe_installer() -> None:
    iss_path = REPO_ROOT / "installer" / "videocreator.iss"
    iss_text = iss_path.read_text(encoding="utf-8")
    assert "AppName=Video Creator V2" in iss_text
    assert "AppVersion=2.0.0" in iss_text
    assert "OutputBaseFilename=VideoCreatorV2Setup" in iss_text
    assert r"web-next\.next\standalone\*" in iss_text
    assert "THIRD_PARTY_NOTICES.md" in iss_text
    assert "install_mpt.cmd" not in iss_text

    notices = REPO_ROOT / "THIRD_PARTY_NOTICES.md"
    assert notices.is_file()
    notices_text = notices.read_text(encoding="utf-8")
    assert "FreeCut" in notices_text
    assert "@xyflow/react" in notices_text
    assert "FFmpeg" in notices_text

    assert (REPO_ROOT / "scripts" / "build_nuitka.ps1").is_file()
    assert (REPO_ROOT / "installer" / "stage_bundle.ps1").is_file()
    assert (REPO_ROOT / "installer" / "post_install.cmd").is_file()
    assert (REPO_ROOT / "installer" / "launch.vbs").is_file()
    assert "install_mpt" not in (REPO_ROOT / "installer" / "post_install.cmd").read_text(encoding="utf-8")

    # Verify runtime path resolvers find Node 24 LTS & FFmpeg
    assert find_node_runtime() is not None
    assert Path(find_ffmpeg_binary("ffmpeg")).is_file() or shutil.which("ffmpeg") is not None

    exe_path = REPO_ROOT / "installer" / "dist" / "VideoCreatorV2Setup.exe"
    if not exe_path.is_file():
        iscc = _find_iscc()
        assert iscc is not None, "Neither VideoCreatorV2Setup.exe nor ISCC.exe available"
        proc = subprocess.run([str(iscc), str(iss_path)], capture_output=True, text=True, check=False)
        assert proc.returncode == 0, proc.stderr or proc.stdout

    assert exe_path.is_file()
    assert exe_path.stat().st_size > 5 * 1024 * 1024
    # PE executable MZ header check
    assert exe_path.read_bytes()[:2] == b"MZ"


def test_wave4_nextjs_standalone_views_and_proxy(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    api_port = _free_port()
    ui_port = _free_port()
    while ui_port == api_port:
        ui_port = _free_port()

    api_base = f"http://127.0.0.1:{api_port}"
    ui_base = f"http://127.0.0.1:{ui_port}"
    app = create_app(paths.data_dir, bind_host="127.0.0.1")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True, name="e2e-w4-uvicorn")
    thread.start()
    ui_proc: Any = None
    try:
        assert wait_for_health(f"{api_base}/health", timeout_s=20.0, server_thread=thread)
        ui_proc = start_nextjs_standalone(
            ui_port,
            api_base,
            boot_log_path=paths.logs_dir / "next_w4_e2e.log",
            host="127.0.0.1",
            timeout_s=25.0,
        )
        assert ui_proc is not None

        for route in ("/welcome", "/novel", "/podcast", "/lipsync", "/settings"):
            st, raw = _get(f"{ui_base}{route}")
            assert st == 200, f"Unexpected status {st} on {route}"
            assert len(raw) > 200

        for api_ep in (
            "/api/v1/onboarding/status",
            "/api/v1/backup/summary",
            "/api/v1/novels/projects",
            "/api/v1/podcasts/projects",
            "/api/v1/lipsync/projects",
        ):
            st, raw = _get(f"{ui_base}{api_ep}")
            assert st == 200, f"Unexpected status {st} on {api_ep}"
            parsed = json.loads(raw.decode("utf-8"))
            assert isinstance(parsed, dict)
    finally:
        stop_nextjs_standalone(ui_proc)
        server.should_exit = True
        thread.join(timeout=5.0)
