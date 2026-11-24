"""Pytest session configuration and environment runtime wiring."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "models: tests that download or execute heavy local AI model weights",
    )

    node_exe = "node.exe" if os.name == "nt" else "node"
    bundled_node = REPO_ROOT / "runtime" / "node" / node_exe
    if not os.environ.get("VIDEOCREATOR_NODE_BIN") and bundled_node.is_file():
        os.environ["VIDEOCREATOR_NODE_BIN"] = str(bundled_node)

    bundled_ffmpeg_dir = REPO_ROOT / "runtime" / "ffmpeg"
    if not os.environ.get("VIDEOCREATOR_FFMPEG_DIR") and bundled_ffmpeg_dir.is_dir():
        os.environ["VIDEOCREATOR_FFMPEG_DIR"] = str(bundled_ffmpeg_dir)

    extra_dirs = [
        str(d)
        for d in (REPO_ROOT / "runtime" / "node", REPO_ROOT / "runtime" / "ffmpeg")
        if d.is_dir()
    ]
    if extra_dirs:
        cur_path = os.environ.get("PATH", "")
        os.environ["PATH"] = os.pathsep.join([*extra_dirs, cur_path])
