"""CLI entry point for Video Creator (desktop pywebview window or headless server)."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any

import uvicorn

from videocreator.app import create_app
from videocreator.auth import register_trusted_ui_origin, unregister_trusted_ui_origin
from videocreator.config import load_settings
from videocreator.paths import (
    REPO_ROOT,
    find_node_runtime,
    get_paths,
    is_port_available,
    pick_available_port,
)
from videocreator.secrets_store import SecretsStore

ERROR_ALREADY_EXISTS = 183


class SingleInstanceLock:
    """Ensures only one Video Creator instance runs per data directory (FR-OPS-08)."""

    def __init__(self, lock_file: Path, mutex_name: str | None = None) -> None:
        import hashlib

        self.lock_file = lock_file
        if mutex_name is None:
            digest = hashlib.sha256(str(lock_file.resolve()).lower().encode("utf-8")).hexdigest()[:16]
            self.mutex_name = f"Local\\VideoCreatorAppMutex_{digest}"
        else:
            self.mutex_name = mutex_name
        self._mutex_handle: int | None = None
        self._fd: int | None = None

    def acquire(self) -> bool:
        if os.name == "nt":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
            kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel32.CreateMutexW.restype = ctypes.c_void_p
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_bool
            handle = kernel32.CreateMutexW(None, False, self.mutex_name)
            if not handle:
                return False
            last_err = ctypes.get_last_error()  # type: ignore[attr-defined]
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
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_bool
            kernel32.CloseHandle(ctypes.c_void_p(self._mutex_handle))
            self._mutex_handle = None
        elif self._fd is not None:
            try:
                import fcntl

                fcntl.flock(self._fd, fcntl.LOCK_UN)
            except Exception:
                pass
            os.close(self._fd)
            self._fd = None


def wait_for_health(
    url: str,
    timeout_s: float = 30.0,
    server_thread: threading.Thread | None = None,
    process: subprocess.Popen[Any] | None = None,
) -> bool:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if server_thread is not None and not server_thread.is_alive():
            return False
        if process is not None and process.poll() is not None:
            return False
        try:
            with opener.open(url, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


# `find_node_runtime`, `is_port_available`, and `pick_available_port` live in `videocreator.paths`.


def _verify_videocreator_ui(ui_base_url: str, timeout_s: float = 5.0) -> bool:
    """Verify the UI server proxies to Video Creator V2's `/api/v1/health` (never a foreign app)."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    probe_url = f"{ui_base_url.rstrip('/')}/api/v1/health"
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with opener.open(probe_url, timeout=1.5) as resp:
                if resp.status == 200:
                    payload = json.loads(resp.read().decode("utf-8", errors="replace"))
                    if payload.get("status") == "ok" and payload.get("api_version") == "v1":
                        return True
        except Exception:
            time.sleep(0.15)
    return False


_PROC_TRUSTED_ORIGINS: dict[int, list[str]] = {}


def stop_nextjs_standalone(proc: subprocess.Popen[Any] | None) -> None:
    """Terminate the Next.js standalone UI subprocess cleanly."""
    if proc is not None:
        for origin in _PROC_TRUSTED_ORIGINS.pop(id(proc), []):
            unregister_trusted_ui_origin(origin)
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3.0)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=2.0)
        except Exception:
            pass


def start_nextjs_standalone(
    ui_port: int,
    backend_url: str,
    boot_log_path: Path | None = None,
    *,
    host: str = "127.0.0.1",
    server_path: Path | None = None,
    timeout_s: float = 20.0,
) -> subprocess.Popen[Any] | None:
    """Launch the built Next.js standalone server and wait until it serves HTTP 200."""
    target_server = server_path or (REPO_ROOT / "web-next" / ".next" / "standalone" / "server.js")
    if not target_server.is_file():
        return None
    node_bin = find_node_runtime()
    if not node_bin:
        return None

    bind_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    probe_host = f"[{bind_host}]" if ":" in bind_host and not bind_host.startswith("[") else bind_host
    env = os.environ.copy()
    env["PORT"] = str(ui_port)
    env["HOSTNAME"] = bind_host
    env["VIDEOCREATOR_API_URL"] = backend_url
    env["NEXT_TELEMETRY_DISABLED"] = "1"

    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    if boot_log_path is not None:
        boot_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(boot_log_path, "a", encoding="utf-8") as log_file:
            proc = subprocess.Popen(
                [node_bin, str(target_server)],
                cwd=str(target_server.parent),
                env=env,
                stdout=log_file,
                stderr=log_file,
                creationflags=creationflags,
            )
    else:
        proc = subprocess.Popen(
            [node_bin, str(target_server)],
            cwd=str(target_server.parent),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )

    if not wait_for_health(f"http://{probe_host}:{ui_port}/", timeout_s=timeout_s, process=proc):
        stop_nextjs_standalone(proc)
        return None
    if proc.poll() is not None or not _verify_videocreator_ui(f"http://{probe_host}:{ui_port}"):
        stop_nextjs_standalone(proc)
        return None
    registered = [register_trusted_ui_origin(f"http://{probe_host}:{ui_port}")]
    if bind_host == "127.0.0.1":
        registered.append(register_trusted_ui_origin(f"http://localhost:{ui_port}"))
    _PROC_TRUSTED_ORIGINS[id(proc)] = registered
    return proc


def _notify_windows_error(message: str) -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.user32.MessageBoxW(0, message, "Video Creator - Lỗi khởi động", 0x10)  # type: ignore[attr-defined]
    except Exception:
        pass


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
    parser.add_argument(
        "--ui-port",
        type=int,
        default=3200,
        help="Port for the Next.js standalone Studio UI (default: 3200)",
    )
    parser.add_argument(
        "--classic-ui",
        action="store_true",
        help="Open the classic Jinja2/HTMX UI instead of Next.js Studio UI",
    )
    return parser.parse_args(argv)


def _show_window_or_browser(base_url: str, server_thread: threading.Thread) -> None:
    """Opens the pywebview window; without it, the default browser, then waits for the server thread."""
    try:
        import webview

        webview.create_window(
            "Video Creator V2",
            base_url,
            width=1280,
            height=840,
            min_size=(960, 640),
        )
        webview.start(gui="edgechromium" if os.name == "nt" else None)
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


def _run_desktop_window(
    app: Any,
    host: str,
    port: int,
    base_url: str,
    boot_log_path: Path,
    *,
    ui_port: int = 3200,
    classic_ui: bool = False,
    local_host: str = "127.0.0.1",
    url_host: str = "127.0.0.1",
    instance_info_path: Path | None = None,
) -> int:
    """Runs the FastAPI backend + Next.js standalone UI and opens the desktop window."""
    server_cfg = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(server_cfg)
    thread = threading.Thread(target=server.run, daemon=True, name="uvicorn-thread")
    thread.start()

    if not wait_for_health(f"{base_url}/health", timeout_s=30.0, server_thread=thread):
        msg = f"Không khởi động được máy chủ nội bộ tại {base_url}.\nXem chi tiết tại: {boot_log_path}"
        print(f"Error: {msg}", file=sys.stderr)
        _notify_windows_error(msg)
        return 1

    ui_proc: subprocess.Popen[Any] | None = None
    display_url = base_url
    if classic_ui:
        print(
            "DeprecationWarning: --classic-ui is deprecated and will be removed in a future release.",
            file=sys.stderr,
        )
    else:
        chosen_ui_port = pick_available_port(local_host, ui_port, exclude_ports={port})
        if chosen_ui_port != ui_port:
            print(
                f"Notice: UI port {ui_port} is in use; starting Video Creator V2 Studio UI on port {chosen_ui_port}.",
                file=sys.stderr,
            )
        ui_proc = start_nextjs_standalone(
            chosen_ui_port,
            base_url,
            boot_log_path=boot_log_path,
            host=local_host,
        )
        if ui_proc is not None:
            display_url = f"http://{url_host}:{chosen_ui_port}"
        else:
            display_url = f"{base_url}/ui-unavailable"
            print(
                f"Warning: Next.js standalone UI unavailable; opening diagnostic page at {display_url} (see {boot_log_path}).",
                file=sys.stderr,
            )

    if instance_info_path is not None:
        try:
            instance_info_path.write_text(
                json.dumps(
                    {"display_url": display_url, "api_url": base_url, "pid": os.getpid()},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

    print(f"Video Creator V2 ready at {display_url} (API: {base_url})", flush=True)
    try:
        _show_window_or_browser(display_url, thread)
    finally:
        if instance_info_path is not None:
            instance_info_path.unlink(missing_ok=True)
        stop_nextjs_standalone(ui_proc)
        server.should_exit = True
        thread.join(timeout=5.0)
    return 0


def main(argv: list[str] | None = None) -> int:
    windowless = sys.stdout is None or sys.stderr is None
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    args = parse_args(argv)
    paths = get_paths(args.data_dir)
    boot_log_path = paths.logs_dir / "desktop_boot.log"
    if windowless:
        boot_log = open(boot_log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = boot_log
        sys.stderr = boot_log
    settings = load_settings(paths.config_file)

    host = (args.host or settings.host).strip()
    port = args.port or settings.port
    local_host = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url_host = f"[{local_host}]" if ":" in local_host and not local_host.startswith("[") else local_host

    if host.lower() not in ("127.0.0.1", "localhost", "::1"):
        secrets = SecretsStore(paths.secrets_file)
        if not secrets.has("UI_PASSWORD"):
            print(
                "Error: Binding outside 127.0.0.1 requires UI_PASSWORD to be set in Secrets Store (NFR-SEC-02).",
                file=sys.stderr,
            )
            return 2

    instance_info_path = paths.data_dir / "instance_url.json"
    lock = SingleInstanceLock(paths.lock_file)
    if not lock.acquire():
        open_url = ""
        if instance_info_path.is_file():
            try:
                saved = json.loads(instance_info_path.read_text(encoding="utf-8"))
                cand_api = str(saved.get("api_url") or "")
                cand_ui = str(saved.get("display_url") or "")
                if cand_ui and cand_api and wait_for_health(f"{cand_api}/health", timeout_s=2.0):
                    open_url = cand_ui
            except Exception:
                open_url = ""
        if not open_url:
            cand_ui = f"http://{url_host}:{args.ui_port}"
            fallback_url = (
                f"http://{url_host}:{port}"
                if args.classic_ui
                else f"http://{url_host}:{port}/ui-unavailable"
            )
            open_url = cand_ui if _verify_videocreator_ui(cand_ui, timeout_s=1.5) else fallback_url
        print(f"Video Creator V2 is already running. Opening {open_url} ...")
        if not args.headless:
            webbrowser.open(open_url)
        return 0

    if args.port is None and not is_port_available(local_host, port):
        alt_port = pick_available_port(local_host, port)
        print(
            f"Notice: Backend port {port} is in use; starting Video Creator V2 API on port {alt_port}.",
            file=sys.stderr,
        )
        port = alt_port
    base_url = f"http://{url_host}:{port}"

    try:
        app = create_app(paths.data_dir, bind_host=host)
        if args.headless:
            uvicorn.run(app, host=host, port=port, log_level="info")
            return 0

        return _run_desktop_window(
            app,
            host,
            port,
            base_url,
            boot_log_path,
            ui_port=args.ui_port,
            classic_ui=args.classic_ui,
            local_host=local_host,
            url_host=url_host,
            instance_info_path=instance_info_path,
        )
    except Exception as exc:
        import traceback

        traceback.print_exc()
        if windowless and not args.headless:
            _notify_windows_error(f"Lỗi khởi động Video Creator: {exc}\nLog: {boot_log_path}")
        raise
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
