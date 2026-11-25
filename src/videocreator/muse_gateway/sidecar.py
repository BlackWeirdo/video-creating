"""Local Sidecar process manager for `vc-hardened` Muse Gateway."""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from videocreator.config import load_settings, save_settings
from videocreator.config_ai import MuseGatewayConfig
from videocreator.muse_gateway.client import MuseGatewayClient
from videocreator.muse_gateway.errors import (
    MuseGatewayError,
    MuseUnavailable,
    MuseUnsafeGatewayError,
)
from videocreator.paths import (
    REPO_ROOT,
    AppPaths,
    find_node_runtime,
    is_port_available,
    pick_available_port,
)

logger = logging.getLogger("videocreator.muse_gateway.sidecar")


class MuseSidecarState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proc: subprocess.Popen[Any] | None = None
        self.owned: bool = False
        self.unsafe_error: str = ""
        self.last_error: str = ""


_SIDECAR_STATES: dict[Path, MuseSidecarState] = {}
_GLOBAL_LOCK = threading.Lock()


def _state_for(data_dir: Path) -> MuseSidecarState:
    resolved = data_dir.resolve()
    with _GLOBAL_LOCK:
        st = _SIDECAR_STATES.get(resolved)
        if st is None:
            st = MuseSidecarState()
            _SIDECAR_STATES[resolved] = st
        return st


def resolve_gateway_entry(cfg: MuseGatewayConfig) -> tuple[Path, Path] | None:
    """Returns `(script_path, app_dir)` for launching Muse Gateway sidecar, or `None` if not installed."""
    candidates: list[Path] = []
    if cfg.sidecar.gateway_entry.strip():
        custom = Path(cfg.sidecar.gateway_entry.strip()).expanduser()
        if custom.is_dir():
            candidates.extend([custom / "app" / "server.js", custom / "server.js", custom / "bin" / "muse-gateway.cjs"])
        else:
            candidates.append(custom)

    bundled = REPO_ROOT / "tools" / "muse-gateway"
    candidates.extend([bundled / "app" / "server.js", bundled / "bin" / "muse-gateway.cjs"])

    appdata = os.environ.get("APPDATA") or ""
    if appdata:
        npm_pkg = Path(appdata) / "npm" / "node_modules" / "muse-gateway"
        candidates.extend([npm_pkg / "app" / "server.js", npm_pkg / "bin" / "muse-gateway.cjs"])

    for cand in candidates:
        if cand.is_file():
            # If pointing at bin/muse-gateway.cjs and sibling app/server.js exists, prefer app/server.js
            # so MUSE_DATA_DIR is respected directly without CLI override.
            if cand.name == "muse-gateway.cjs":
                alt_server = cand.parent.parent / "app" / "server.js"
                if alt_server.is_file():
                    return alt_server.resolve(), alt_server.parent.resolve()
            return cand.resolve(), cand.parent.resolve()
    return None


def get_sidecar_runtime_status(paths: AppPaths) -> dict[str, Any]:
    st = _state_for(paths.data_dir)
    cfg = load_settings(paths.config_file).muse_gateway
    entry_info = resolve_gateway_entry(cfg)
    pid = st.proc.pid if (st.proc is not None and st.proc.poll() is None) else None
    return {
        "owned": st.owned and pid is not None,
        "pid": pid,
        "entry_found": entry_info is not None,
        "entry_path": str(entry_info[0]) if entry_info else "",
        "unsafe_error": st.unsafe_error,
        "last_error": st.last_error,
    }


def stop_muse_sidecar(paths: AppPaths, *, only_if_owned: bool = True) -> bool:
    st = _state_for(paths.data_dir)
    with st.lock:
        proc = st.proc
        if proc is None:
            st.owned = False
            return False
        if only_if_owned and not st.owned:
            return False
        if proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=4.0)
            except (OSError, subprocess.SubprocessError):
                try:
                    proc.kill()
                    proc.wait(timeout=2.0)
                except (OSError, subprocess.SubprocessError):
                    pass
        st.proc = None
        st.owned = False
        return True


def ensure_muse_sidecar_running(paths: AppPaths, *, timeout_s: float = 45.0) -> dict[str, Any]:
    """Attaches to an already-running hardened gateway or spawns a local sidecar on `127.0.0.1`."""
    settings = load_settings(paths.config_file)
    cfg = settings.muse_gateway
    if cfg.mode != "local_sidecar":
        raise MuseGatewayError("Sidecar chỉ khả dụng ở chế độ local_sidecar")

    st = _state_for(paths.data_dir)
    with st.lock:
        st.unsafe_error = ""
        st.last_error = ""

        # 1. Probe if a Muse Gateway is already listening at base_url
        probe_client = MuseGatewayClient(cfg, timeout_s=4.0)
        try:
            disc = probe_client.discover()
            if disc.get("service") == "muse-gateway":
                safety = probe_client.verify_ready_and_safe()
                return {
                    "running": True,
                    "attached": not st.owned,
                    "owned": st.owned,
                    "base_url": probe_client.base_url,
                    "hardened": safety["hardened"],
                }
        except MuseUnsafeGatewayError as exc:
            st.unsafe_error = str(exc)
            raise
        except MuseGatewayError:
            pass

        # 2. Pick port if busy with a foreign non-Muse process
        port = int(cfg.sidecar.port)
        if not is_port_available("127.0.0.1", port):
            port = pick_available_port("127.0.0.1", port, exclude_ports={settings.port})
            settings.muse_gateway.sidecar.port = port
            settings.muse_gateway.base_url = f"http://127.0.0.1:{port}"
            save_settings(paths.config_file, settings)
            cfg = settings.muse_gateway
        elif cfg.base_url.rstrip("/") != f"http://127.0.0.1:{port}":
            settings.muse_gateway.base_url = f"http://127.0.0.1:{port}"
            save_settings(paths.config_file, settings)
            cfg = settings.muse_gateway

        entry_info = resolve_gateway_entry(cfg)
        if entry_info is None:
            st.last_error = "Không tìm thấy gói muse-gateway (cấu hình gateway_entry hoặc đặt vào tools/muse-gateway)."
            raise MuseUnavailable(st.last_error)

        node_bin = find_node_runtime()
        if not node_bin:
            st.last_error = "Không tìm thấy Node.js runtime để chạy Muse Gateway sidecar."
            raise MuseUnavailable(st.last_error)

        script_path, app_dir = entry_info
        gw_data_dir = paths.data_dir / "muse-gateway"
        gw_data_dir.mkdir(parents=True, exist_ok=True)
        log_path = paths.logs_dir / "muse_gateway.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["HOSTNAME"] = "127.0.0.1"
        env["PORT"] = str(port)
        env["MUSE_PORT"] = str(port)
        env["MUSE_APP_DIR"] = str(app_dir)
        env["MUSE_DATA_DIR"] = str(gw_data_dir)
        env["MUSE_CMD_MODE"] = "off"
        env["MUSE_CTX_NO_FILES"] = "1"
        env["MUSE_CTX_NO_TREE"] = "1"
        env["MUSE_MEDIA_MAX_MB"] = str(cfg.sidecar.media_max_mb)
        env["MUSE_LONG_RENDER_GRACE_MS"] = str(cfg.sidecar.long_render_grace_ms)
        env.pop("MUSE_BIND", None)

        args = [node_bin, str(script_path)]
        if script_path.name == "muse-gateway.cjs":
            args.extend(["--serve", "--no-tray"])

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        log_fh = open(log_path, "a", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                args,
                cwd=str(app_dir),
                env=env,
                stdout=log_fh,
                stderr=log_fh,
                creationflags=creationflags,
            )
        finally:
            log_fh.close()

        st.proc = proc
        st.owned = True

        live_client = MuseGatewayClient(cfg, timeout_s=4.0)
        deadline = time.monotonic() + timeout_s
        ready = False
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                st.proc = None
                st.owned = False
                st.last_error = f"Muse Gateway sidecar thoát sớm (mã {proc.returncode}). Xem {log_path}"
                raise MuseUnavailable(st.last_error)
            try:
                if live_client.health().get("ok"):
                    ready = True
                    break
            except MuseGatewayError:
                time.sleep(0.25)

        if not ready:
            st.last_error = f"Muse Gateway sidecar quá hạn khởi động ({timeout_s}s)."
            stop_muse_sidecar_unlocked(st)
            raise MuseUnavailable(st.last_error)

        try:
            safety = live_client.verify_ready_and_safe()
        except MuseUnsafeGatewayError as exc:
            st.unsafe_error = str(exc)
            stop_muse_sidecar_unlocked(st)
            raise

        logger.info("Muse Gateway sidecar ready at %s (pid=%s)", live_client.base_url, proc.pid)
        return {
            "running": True,
            "attached": False,
            "owned": True,
            "pid": proc.pid,
            "base_url": live_client.base_url,
            "hardened": safety["hardened"],
        }


def stop_muse_sidecar_unlocked(st: MuseSidecarState) -> None:
    proc = st.proc
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=3.0)
        except (OSError, subprocess.SubprocessError):
            try:
                proc.kill()
                proc.wait(timeout=2.0)
            except (OSError, subprocess.SubprocessError):
                pass
    st.proc = None
    st.owned = False


__all__ = [
    "ensure_muse_sidecar_running",
    "get_sidecar_runtime_status",
    "resolve_gateway_entry",
    "stop_muse_sidecar",
]
