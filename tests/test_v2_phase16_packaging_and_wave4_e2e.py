"""Tests for Phase 16 & Stage R6: Truly Offline Windows `.exe` Installer & Empty-PATH Runtime Verification."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import threading
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from videocreator import __version__
from videocreator.__main__ import start_nextjs_standalone, stop_nextjs_standalone, wait_for_health
from videocreator.app import create_app
from videocreator.paths import REPO_ROOT, find_ffmpeg_binary, find_node_runtime, get_paths

pytestmark = [pytest.mark.local, pytest.mark.slow]


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
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Inno Setup 6"
        / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    ):
        if cand.is_file():
            return cand
    return None


def _link_or_copy_dir(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        proc = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(dst), str(src)],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and dst.exists():
            return
    shutil.copytree(src, dst)


def test_windows_v2_packaging_artifacts_and_exe_installer() -> None:
    assert re.match(r"^\d+\.\d+\.\d+$", __version__), f"Invalid semver: {__version__}"
    web_pkg = json.loads((REPO_ROOT / "web-next" / "package.json").read_text(encoding="utf-8"))
    assert web_pkg["version"] == __version__, (
        f"Version drift: web-next/package.json={web_pkg['version']} vs __version__={__version__}"
    )

    # Zero personal machine paths (`ADMIN` or `iCast`) in `src/` and `installer/` scripts
    for py_file in (REPO_ROOT / "src").rglob("*.py"):
        src_txt = py_file.read_text(encoding="utf-8")
        assert "ADMIN" not in src_txt, f"Hardcoded ADMIN path in {py_file}"
        assert "iCast" not in src_txt, f"Hardcoded iCast path in {py_file}"

    for script_name in (
        "videocreator.iss",
        "post_install.cmd",
        "post_install.ps1",
        "launch.vbs",
        "stage_bundle.ps1",
    ):
        s_path = REPO_ROOT / "installer" / script_name
        assert s_path.is_file(), f"Missing installer file: {script_name}"
        s_txt = s_path.read_text(encoding="utf-8")
        assert "ADMIN" not in s_txt, f"Hardcoded ADMIN in {script_name}"
        assert "iCast" not in s_txt, f"Hardcoded iCast in {script_name}"

    # Offline guarantee: `post_install.*` and `launch.vbs` must never invoke winget or network installers
    for offline_script in ("post_install.cmd", "post_install.ps1", "launch.vbs"):
        txt_lower = (REPO_ROOT / "installer" / offline_script).read_text(encoding="utf-8").lower()
        assert "winget" not in txt_lower, f"Network winget call found in {offline_script}"
        assert "https://" not in txt_lower, f"Network URL found in {offline_script}"
        assert "http://" not in txt_lower, f"Network URL found in {offline_script}"
        assert "install_mpt" not in txt_lower

    iss_path = REPO_ROOT / "installer" / "videocreator.iss"
    iss_text = iss_path.read_text(encoding="utf-8")
    assert "AppName=Video Creator V2" in iss_text
    assert f'#define MyAppVersion "{__version__}"' in iss_text
    assert "AppVersion={#MyAppVersion}" in iss_text
    assert "OutputBaseFilename=VideoCreatorV2Setup" in iss_text
    assert r"web-next\.next\standalone\*" in iss_text
    assert "THIRD_PARTY_NOTICES.md" in iss_text

    # Verify all required `[Files]` Source entries exist on disk for offline installation
    source_entries = re.findall(r'^Source:\s*"([^"]+)"', iss_text, flags=re.MULTILINE)
    assert len(source_entries) >= 12
    for raw_src in source_entries:
        if "build\\nuitka" in raw_src:
            continue
        clean_rel = raw_src.removesuffix(r"\*")
        resolved = (REPO_ROOT / "installer" / clean_rel).resolve()
        assert resolved.exists(), f"Missing Inno Setup [Files] source on disk: {raw_src} -> {resolved}"

    # Verify SHA-256 manifest matches staged runtime binaries
    manifest_path = REPO_ROOT / "installer" / "staging" / "runtime_sha256.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("python_exe", "node_exe", "ffmpeg_exe", "ffprobe_exe", "ytdlp_exe", "uv_exe"):
        assert key in manifest, f"Missing {key} in runtime_sha256.json"
        bin_file = REPO_ROOT / manifest[key]["path"]
        assert bin_file.is_file(), f"Missing staged runtime binary: {bin_file}"
        digest = hashlib.sha256(bin_file.read_bytes()).hexdigest()
        assert digest == manifest[key]["sha256"], f"SHA-256 mismatch for {key}"

    # Verify staged `.venv` launchers have zero hardcoded `Users\ADMIN` paths
    staged_venv = REPO_ROOT / "installer" / "staging" / "venv"
    assert (staged_venv / "Scripts" / "python.exe").is_file()
    assert (staged_venv / "Scripts" / "pythonw.exe").is_file()
    assert "ADMIN" not in (staged_venv / "pyvenv.cfg").read_text(encoding="utf-8")
    for exe_name in ("python.exe", "pythonw.exe"):
        raw_exe = (staged_venv / "Scripts" / exe_name).read_bytes()
        assert b"Users\\ADMIN" not in raw_exe, f"Build-host path leaked into staged {exe_name}"

    # Verify embedded FreeCut (MIT) & third-party notices
    assert (REPO_ROOT / "tools" / "freecut" / "index.html").is_file()
    assert (REPO_ROOT / "tools" / "freecut" / "LICENSE").is_file()
    notices_text = (REPO_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "FreeCut" in notices_text
    assert "NLLB-200" in notices_text
    assert "VieNeu-TTS" in notices_text

    assert find_node_runtime() is not None
    assert Path(find_ffmpeg_binary("ffmpeg")).is_file()

    exe_path = REPO_ROOT / "installer" / "dist" / "VideoCreatorV2Setup.exe"
    if not exe_path.is_file():
        iscc = _find_iscc()
        assert iscc is not None, "Neither VideoCreatorV2Setup.exe nor ISCC.exe available"
        proc = subprocess.run(
            [str(iscc), str(iss_path)], capture_output=True, text=True, check=False
        )
        assert proc.returncode == 0, proc.stderr or proc.stdout

    assert exe_path.is_file()
    # Truly self-contained offline installer (Python 3.11 + .venv + Node 24 + FFmpeg + yt-dlp + FreeCut)
    assert exe_path.stat().st_size > 150 * 1024 * 1024
    assert exe_path.read_bytes()[:2] == b"MZ"


@pytest.mark.skipif(os.name != "nt", reason="Windows offline bundle relocation test")
def test_offline_relocated_bundle_boots_with_empty_path(tmp_path: Path) -> None:
    """Relocates staged `{app}` to a fresh folder, runs `post_install.cmd`, and boots with `PATH=""`."""
    staged_venv = REPO_ROOT / "installer" / "staging" / "venv"
    assert (staged_venv / "Scripts" / "python.exe").is_file()

    app_dir = tmp_path / "CleanPC_VideoCreatorV2"
    (app_dir / "installer").mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "pyproject.toml", app_dir / "pyproject.toml")
    for f_name in ("post_install.cmd", "post_install.ps1", "launch.vbs"):
        shutil.copy2(REPO_ROOT / "installer" / f_name, app_dir / "installer" / f_name)

    _link_or_copy_dir(REPO_ROOT / "runtime", app_dir / "runtime")
    _link_or_copy_dir(REPO_ROOT / "tools", app_dir / "tools")
    _link_or_copy_dir(REPO_ROOT / "src", app_dir / "src")
    (app_dir / "web-next" / ".next").mkdir(parents=True, exist_ok=True)
    _link_or_copy_dir(
        REPO_ROOT / "web-next" / ".next" / "standalone",
        app_dir / "web-next" / ".next" / "standalone",
    )

    # Create relocated `.venv` with its own `pyvenv.cfg` + `Scripts/`, linking `Lib/`
    reloc_venv = app_dir / ".venv"
    (reloc_venv / "Scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy2(staged_venv / "pyvenv.cfg", reloc_venv / "pyvenv.cfg")
    shutil.copy2(staged_venv / "Scripts" / "python.exe", reloc_venv / "Scripts" / "python.exe")
    shutil.copy2(staged_venv / "Scripts" / "pythonw.exe", reloc_venv / "Scripts" / "pythonw.exe")
    _link_or_copy_dir(staged_venv / "Lib", reloc_venv / "Lib")

    try:
        # 1. Execute `post_install.cmd` (must succeed offline and rewrite `.venv/pyvenv.cfg` to relocated `runtime\python`)
        post_proc = subprocess.run(
            ["cmd.exe", "/c", str(app_dir / "installer" / "post_install.cmd")],
            cwd=str(app_dir),
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        assert post_proc.returncode == 0, post_proc.stderr or post_proc.stdout
        rewritten_cfg = (reloc_venv / "pyvenv.cfg").read_text(encoding="utf-8")
        assert str(app_dir / "runtime" / "python") in rewritten_cfg

        # 2. Launch relocated `.venv\Scripts\python.exe` with completely EMPTY `PATH=""`!
        api_port = _free_port()
        ui_port = _free_port()
        while ui_port == api_port:
            ui_port = _free_port()

        probe_script = f"""
import json, os, threading, urllib.request, uvicorn
from pathlib import Path
assert os.environ.get("PATH", "") == "", f"Expected empty PATH, got {{os.environ.get('PATH')}}"

import onnxruntime, ctranslate2, faster_whisper, rapidocr_onnxruntime, rembg, edge_tts
from videocreator.paths import (
    find_ffmpeg_binary,
    find_node_runtime,
    find_uv_binary,
    find_yt_dlp_command,
    get_paths,
)
from videocreator.app import create_app
from videocreator.__main__ import start_nextjs_standalone, stop_nextjs_standalone, wait_for_health

app_root = Path(os.path.abspath(r"{app_dir}"))
node_bin = Path(os.path.abspath(find_node_runtime()))
ff_bin = Path(os.path.abspath(find_ffmpeg_binary("ffmpeg")))
fp_bin = Path(os.path.abspath(find_ffmpeg_binary("ffprobe")))
yt_bin = Path(os.path.abspath(find_yt_dlp_command()[0]))
uv_bin = Path(os.path.abspath(find_uv_binary()))

for resolved in (node_bin, ff_bin, fp_bin, yt_bin, uv_bin):
    assert resolved.is_file(), f"Missing resolved binary: {{resolved}}"
    assert app_root in resolved.parents, f"Binary {{resolved}} resolved outside relocated bundle {{app_root}}"

paths = get_paths(Path(r"{tmp_path / 'clean_data'}"))
app = create_app(paths.data_dir, start_worker=False, bind_host="127.0.0.1")
srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port={api_port}, log_level="warning"))
th = threading.Thread(target=srv.run, daemon=True)
th.start()
ui_proc = None
try:
    assert wait_for_health("http://127.0.0.1:{api_port}/health", timeout_s=20.0, server_thread=th)
    ui_proc = start_nextjs_standalone(
        {ui_port},
        "http://127.0.0.1:{api_port}",
        host="127.0.0.1",
        server_path=app_root / "web-next" / ".next" / "standalone" / "server.js",
        timeout_s=25.0,
    )
    assert ui_proc is not None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({{}}))
    with opener.open("http://127.0.0.1:{ui_port}/api/v1/health", timeout=10.0) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok" and body["version"] == "{__version__}"
    print("EMPTY_PATH_OFFLINE_BOOT_OK")
finally:
    stop_nextjs_standalone(ui_proc)
    srv.should_exit = True
    th.join(timeout=5.0)
"""
        clean_env = {
            "PATH": "",
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", r"C:\Windows"),
            "WINDIR": os.environ.get("WINDIR", r"C:\Windows"),
            "SYSTEMDRIVE": os.environ.get("SYSTEMDRIVE", "C:"),
            "TEMP": str(tmp_path),
            "TMP": str(tmp_path),
            "USERPROFILE": str(tmp_path),
            "APPDATA": str(tmp_path / "AppData" / "Roaming"),
            "LOCALAPPDATA": str(tmp_path / "AppData" / "Local"),
            "PYTHONIOENCODING": "utf-8",
            "VIDEOCREATOR_APP_ROOT": str(app_dir),
        }
        empty_proc = subprocess.run(
            [str(reloc_venv / "Scripts" / "python.exe"), "-c", probe_script],
            cwd=str(app_dir),
            env=clean_env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        assert (
            empty_proc.returncode == 0
        ), f"STDOUT:\n{empty_proc.stdout}\nSTDERR:\n{empty_proc.stderr}"
        assert "EMPTY_PATH_OFFLINE_BOOT_OK" in empty_proc.stdout
    finally:
        for junc in (
            reloc_venv / "Lib",
            app_dir / "web-next" / ".next" / "standalone",
            app_dir / "src",
            app_dir / "tools",
            app_dir / "runtime",
        ):
            if junc.exists():
                subprocess.run(["cmd.exe", "/c", "rmdir", str(junc)], capture_output=True, check=False)


def test_wave4_nextjs_standalone_views_and_proxy(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    api_port = _free_port()
    ui_port = _free_port()
    while ui_port == api_port:
        ui_port = _free_port()

    api_base = f"http://127.0.0.1:{api_port}"
    ui_base = f"http://127.0.0.1:{ui_port}"
    app = create_app(paths.data_dir, bind_host="127.0.0.1")
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=api_port, log_level="warning")
    )
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
