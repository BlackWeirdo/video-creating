"""CLI entry point for Video Creator (desktop pywebview window or headless server)."""
from __future__ import annotations

import argparse
import ctypes
import os
import shutil
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
from videocreator.config import load_settings
from videocreator.paths import REPO_ROOT, get_paths
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


def find_node_runtime() -> str | None:
    """Locate the Node.js binary, preferring the project or iCast Node 24 LTS runtime."""
    env_override = os.environ.get("VIDEOCREATOR_NODE_BIN")
    if env_override and Path(env_override).is_file():
        return str(Path(env_override).resolve())

    node_exe = "node.exe" if os.name == "nt" else "node"
    candidates: list[Path] = [REPO_ROOT / "runtime" / "node" / node_exe]
    if os.name == "nt":
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            candidates.append(Path(local_app) / "Programs" / "iCast" / "runtime" / "node" / "node.exe")
        candidates.append(Path(r"C:\Users\ADMIN\AppData\Local\Programs\iCast\runtime\node\node.exe"))

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    found = shutil.which("node")
    return found if found else None


def stop_nextjs_standalone(proc: subprocess.Popen[Any] | None) -> None:
    """Terminate the Next.js standalone UI subprocess cleanly."""
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
        default=3000,
        help="Port for the Next.js standalone Studio UI (default: 3000)",
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
            "Video Creator",
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
    ui_port: int = 3000,
    classic_ui: bool = False,
    local_host: str = "127.0.0.1",
    url_host: str = "127.0.0.1",
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
    if not classic_ui:
        ui_proc = start_nextjs_standalone(
            ui_port,
            base_url,
            boot_log_path=boot_log_path,
            host=local_host,
        )
        if ui_proc is not None:
            display_url = f"http://{url_host}:{ui_port}"
        else:
            print(
                f"Warning: Next.js standalone UI unavailable; falling back to classic UI at {base_url}.",
                file=sys.stderr,
            )

    try:
        _show_window_or_browser(display_url, thread)
    finally:
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
    base_url = f"http://{url_host}:{port}"

    if host.lower() not in ("127.0.0.1", "localhost", "::1"):
        secrets = SecretsStore(paths.secrets_file)
        if not secrets.has("UI_PASSWORD"):
            print(
                "Error: Binding outside 127.0.0.1 requires UI_PASSWORD to be set in Secrets Store (NFR-SEC-02).",
                file=sys.stderr,
            )
            return 2

    lock = SingleInstanceLock(paths.lock_file)
    if not lock.acquire():
        ui_server_file = REPO_ROOT / "web-next" / ".next" / "standalone" / "server.js"
        open_url = (
            f"http://{url_host}:{args.ui_port}"
            if (not args.classic_ui and ui_server_file.is_file())
            else base_url
        )
        print(f"Video Creator is already running. Opening {open_url} ...")
        if not args.headless:
            webbrowser.open(open_url)
        return 0

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
