"""Wave 5 verification: isolated mounts, `/ui-unavailable` diagnostic page, and `--classic-ui` deprecation."""
from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import videocreator.__main__ as cli_main
from videocreator.api import (
    mounts,
    routes_config_bundle,
    routes_freecut_bridge,
    routes_media,
    routes_oauth,
)
from videocreator.app import create_app

pytestmark = pytest.mark.local


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_mounts_package_matches_backward_compatible_facades() -> None:
    assert mounts.media_router is routes_media.router
    assert mounts.freecut_router is routes_freecut_bridge.router
    assert mounts.oauth_router is routes_oauth.router
    assert mounts.config_bundle_router is routes_config_bundle.router


def test_ui_unavailable_diagnostic_page_renders_vietnamese_guidance(tmp_path: Path) -> None:
    app = create_app(tmp_path / "data", start_worker=False)
    with TestClient(app) as client:
        res = client.get("/ui-unavailable")
        assert res.status_code == 200
        assert "no-store" in res.headers.get("cache-control", "")
        html_text = res.text
        assert "Giao diện Video Creator V2 Studio chưa khởi động được" in html_text
        assert "desktop_boot.log" in html_text
        assert "/api/v1/health" in html_text


def test_desktop_launcher_uses_diagnostic_page_on_nextjs_failure_and_warns_on_classic_ui(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    app = create_app(tmp_path / "data", start_worker=False, bind_host="127.0.0.1")
    opened_urls: list[str] = []

    monkeypatch.setattr(cli_main, "start_nextjs_standalone", lambda *a, **kw: None)
    monkeypatch.setattr(
        cli_main,
        "_show_window_or_browser",
        lambda url, _thread: opened_urls.append(url),
    )

    port1 = _free_port()
    base1 = f"http://127.0.0.1:{port1}"
    rc1 = cli_main._run_desktop_window(
        app,
        "127.0.0.1",
        port1,
        base1,
        tmp_path / "boot1.log",
        ui_port=_free_port(),
        classic_ui=False,
    )
    assert rc1 == 0
    assert opened_urls[-1] == f"{base1}/ui-unavailable"
    err1 = capsys.readouterr().err
    assert "/ui-unavailable" in err1

    port2 = _free_port()
    base2 = f"http://127.0.0.1:{port2}"
    rc2 = cli_main._run_desktop_window(
        app,
        "127.0.0.1",
        port2,
        base2,
        tmp_path / "boot2.log",
        ui_port=_free_port(),
        classic_ui=True,
    )
    assert rc2 == 0
    assert opened_urls[-1] == base2
    err2 = capsys.readouterr().err
    assert "DeprecationWarning: --classic-ui is deprecated" in err2
