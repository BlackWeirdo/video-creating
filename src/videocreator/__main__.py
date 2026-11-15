"""CLI entry point for Video Creator (desktop pywebview window or headless server)."""
from __future__ import annotations

import argparse
import ctypes
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn

from videocreator.app import create_app
from videocreator.config import load_settings
from videocreator.paths import get_paths
from videocreator.secrets_store import SecretsStore

ERROR_ALREADY_EXISTS = 183


class SingleInstanceLock:
    """Ensures only one Video Creator instance runs per data directory (FR-OPS-08)."""

    def __init__(self, lock_file: Path, mutex_name: str = "Local\\VideoCreatorAppMutex") -> None:
        self.lock_file = lock_file
        self.mutex_name = mutex_name
        self._mutex_handle: int | None = None
        self._fd: int | None = None

    def acquire(self) -> bool:
        if os.name == "nt":
            kernel32 = ctypes.windll.kernel32
            kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            handle = kernel32.CreateMutexW(None, False, self.mutex_name)
            if not handle:
                return False
            last_err = kernel32.GetLastError()
            if last_err == ERROR_ALREADY_EXISTS:
                kernel32.CloseHandle(ctypes.c_void_p(handle))
                return False
            self._mutex_handle = int(handle)
            return True

        import fcntl

        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.lock_file), os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self._fd = fd
        return True

    def release(self) -> None:
        if os.name == "nt" and self._mutex_handle is not None:
            ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(self._mutex_handle))
            self._mutex_handle = None
        elif self._fd is not None:
            try:
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except Exception:
                pass
            os.close(self._fd)
            self._fd = None


def wait_for_health(url: str, timeout_s: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Video Creator")
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run FastAPI server without opening a desktop window",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=None,
        help="Override bind host from config.toml",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Override bind port from config.toml",
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default=None,
        help="Override data directory (or set VIDEOCREATOR_DATA)",
    )
    return parser.parse_args(argv)


def _show_window_or_browser(base_url: str, server_thread: threading.Thread) -> None:
    """Opens the pywebview window; without it, the default browser, then waits for the server thread."""
    try:
        import webview

        webview.create_window(
            "Video Creator",
            base_url,
            width=1280,
            height=840,
            min_size=(960, 640),
        )
        webview.start()
    except Exception as exc:
        print(
            f"Warning: Could not open pywebview window ({exc}). Falling back to default browser.",
            file=sys.stderr,
        )
        webbrowser.open(base_url)
        try:
            while server_thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass


def _run_desktop_window(app: Any, host: str, port: int, base_url: str) -> int:
    """Runs the server on a background thread and the desktop window in the foreground."""
    server_cfg = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(server_cfg)
    thread = threading.Thread(target=server.run, daemon=True, name="uvicorn-thread")
    thread.start()

    if not wait_for_health(f"{base_url}/health"):
        print("Error: Local server failed to start within timeout.", file=sys.stderr)
        return 1
    try:
        _show_window_or_browser(base_url, thread)
    finally:
        server.should_exit = True
        thread.join(timeout=5.0)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    paths = get_paths(args.data_dir)
    settings = load_settings(paths.config_file)

    host = args.host or settings.host
    port = args.port or settings.port
    local_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    base_url = f"http://{local_host}:{port}"

    if host not in ("127.0.0.1", "localhost"):
        secrets = SecretsStore(paths.secrets_file)
        if not secrets.has("UI_PASSWORD"):
            print(
                "Error: Binding outside 127.0.0.1 requires UI_PASSWORD to be set in Secrets Store (NFR-SEC-02).",
                file=sys.stderr,
            )
            return 2

    lock = SingleInstanceLock(paths.lock_file)
    if not lock.acquire():
        print(f"Video Creator is already running. Opening {base_url} ...")
        if not args.headless:
            webbrowser.open(base_url)
        return 0

    try:
        app = create_app(paths.data_dir, bind_host=host)
        if args.headless:
            uvicorn.run(app, host=host, port=port, log_level="info")
            return 0

        return _run_desktop_window(app, host, port, base_url)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
