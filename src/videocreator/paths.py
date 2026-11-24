"""Filesystem paths and directory layout for Video Creator."""
from __future__ import annotations

import os
import shutil
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "VideoCreatorV2"
PACKAGE_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGE_DIR.parent.parent


@dataclass(frozen=True)
class AppPaths:
    data_dir: Path

    @property
    def config_file(self) -> Path:
        return self.data_dir / "config.toml"

    @property
    def db_file(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def secrets_file(self) -> Path:
        return self.data_dir / "secrets.bin"

    @property
    def lock_file(self) -> Path:
        return self.data_dir / "instance.lock"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def log_file(self) -> Path:
        return self.logs_dir / "app.log"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"

    @property
    def inbox_dir(self) -> Path:
        return self.data_dir / "inbox"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def footage_dir(self) -> Path:
        return self.media_dir / "footage"

    @property
    def thumbs_dir(self) -> Path:
        return self.media_dir / "thumbs"

    @property
    def output_dir(self) -> Path:
        return self.media_dir / "output"

    @property
    def reference_dir(self) -> Path:
        return self.media_dir / "reference"

    @property
    def studio_dir(self) -> Path:
        return self.media_dir / "studio"

    @property
    def assets_dir(self) -> Path:
        return self.media_dir / "assets"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def migrations_dir(self) -> Path:
        return PACKAGE_DIR / "migrations"

    @property
    def templates_dir(self) -> Path:
        return PACKAGE_DIR / "web" / "templates"

    @property
    def static_dir(self) -> Path:
        return PACKAGE_DIR / "web" / "static"

    def ensure_dirs(self) -> None:
        for directory in (
            self.data_dir,
            self.logs_dir,
            self.backups_dir,
            self.work_dir,
            self.inbox_dir,
            self.media_dir,
            self.footage_dir,
            self.thumbs_dir,
            self.output_dir,
            self.reference_dir,
            self.studio_dir,
            self.assets_dir,
            self.models_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


def get_paths(data_dir: Path | str | None = None) -> AppPaths:
    if data_dir is not None:
        resolved = Path(data_dir).expanduser().resolve()
    else:
        env_override = os.environ.get("VIDEOCREATOR_DATA")
        if env_override:
            resolved = Path(env_override).expanduser().resolve()
        else:
            resolved = Path(user_data_dir(APP_NAME, appauthor=False)).resolve()
    paths = AppPaths(data_dir=resolved)
    paths.ensure_dirs()
    return paths


def find_ffmpeg_binary(name: str = "ffmpeg") -> str:
    exe_name = f"{name}.exe" if os.name == "nt" else name
    env_dir = (os.environ.get("VIDEOCREATOR_FFMPEG_DIR") or "").strip()
    if env_dir:
        env_bin = Path(env_dir).expanduser().resolve() / exe_name
        if env_bin.is_file():
            return str(env_bin)
    runtime_bundled = REPO_ROOT / "runtime" / "ffmpeg" / exe_name
    if runtime_bundled.is_file():
        return str(runtime_bundled)
    bundled = REPO_ROOT / "ffmpeg" / "bin" / exe_name
    if bundled.is_file():
        return str(bundled)
    found = shutil.which(name)
    if found:
        return found
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        winget_link = Path(local_app_data) / "Microsoft" / "WinGet" / "Links" / exe_name
        if winget_link.exists():
            return str(winget_link)
        winget_pkgs = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_pkgs.exists():
            matches = sorted(winget_pkgs.glob(f"Gyan.FFmpeg*/ffmpeg-*/bin/{exe_name}"))
            if matches:
                return str(matches[-1])
    return name


def find_node_runtime() -> str | None:
    """Locate the Node.js binary: `VIDEOCREATOR_NODE_BIN` -> `{app}/runtime/node` -> `PATH`."""
    env_override = (os.environ.get("VIDEOCREATOR_NODE_BIN") or "").strip()
    if env_override and Path(env_override).is_file():
        return str(Path(env_override).resolve())

    node_exe = "node.exe" if os.name == "nt" else "node"
    bundled = REPO_ROOT / "runtime" / "node" / node_exe
    if bundled.is_file():
        return str(bundled)

    found = shutil.which("node")
    return found if found else None


def find_rea_video_binary() -> str:
    candidates = [
        REPO_ROOT / "tools" / "rea" / "Scripts" / "rea-video.exe",
        REPO_ROOT / "tools" / "rea" / "bin" / "rea-video",
        REPO_ROOT / "spikes" / ".venv-rea" / "Scripts" / "rea-video.exe",
        REPO_ROOT / "spikes" / ".venv-rea" / "bin" / "rea-video",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    found = shutil.which("rea-video")
    if found:
        return found
    raise FileNotFoundError("rea-video CLI binary not found in tools/rea, spikes/.venv-rea, or PATH")


def find_yt_dlp_command() -> list[str]:
    """Locate `yt-dlp`: `VIDEOCREATOR_YTDLP_BIN` -> `{app}/runtime/yt-dlp` -> `.venv` -> `PATH` -> `python -m yt_dlp`."""
    env_override = (os.environ.get("VIDEOCREATOR_YTDLP_BIN") or "").strip()
    if env_override and Path(env_override).is_file():
        return [str(Path(env_override).resolve())]

    exe_name = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
    bundled = REPO_ROOT / "runtime" / "yt-dlp" / exe_name
    if bundled.is_file():
        return [str(bundled)]

    venv_exe = Path(sys.executable).parent / exe_name
    if venv_exe.is_file():
        return [str(venv_exe)]

    which_exe = shutil.which("yt-dlp")
    if which_exe:
        return [which_exe]
    return [sys.executable, "-m", "yt_dlp"]


def find_uv_binary() -> str | None:
    """Locate `uv`: `VIDEOCREATOR_UV_BIN` -> `{app}/runtime/uv` -> `PATH`."""
    env_override = (os.environ.get("VIDEOCREATOR_UV_BIN") or "").strip()
    if env_override and Path(env_override).is_file():
        return str(Path(env_override).resolve())

    exe_name = "uv.exe" if os.name == "nt" else "uv"
    bundled = REPO_ROOT / "runtime" / "uv" / exe_name
    if bundled.is_file():
        return str(bundled)

    found = shutil.which("uv")
    return found if found else None


def find_python_runtime() -> str:
    """Locate bundled Python or current interpreter: `VIDEOCREATOR_PYTHON_BIN` -> `{app}/.venv` -> `{app}/runtime/python` -> `sys.executable`."""
    env_override = (os.environ.get("VIDEOCREATOR_PYTHON_BIN") or "").strip()
    if env_override and Path(env_override).is_file():
        return str(Path(env_override).resolve())

    py_exe = "python.exe" if os.name == "nt" else "python3"
    venv_py = (
        REPO_ROOT / ".venv" / "Scripts" / "python.exe"
        if os.name == "nt"
        else REPO_ROOT / ".venv" / "bin" / "python"
    )
    if venv_py.is_file():
        return str(venv_py)

    bundled = REPO_ROOT / "runtime" / "python" / py_exe
    if bundled.is_file():
        return str(bundled)

    return sys.executable


def is_port_available(host: str, port: int) -> bool:
    """Return True only if nothing is listening on `(host, port)` and it can be bound exclusively."""
    bind_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    family = socket.AF_INET6 if ":" in bind_host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        if probe.connect_ex((bind_host, int(port))) == 0:
            return False
    with socket.socket(family, socket.SOCK_STREAM) as sock:
        excl_opt = getattr(socket, "SO_EXCLUSIVEADDRUSE", None)
        if excl_opt is not None:
            try:
                sock.setsockopt(socket.SOL_SOCKET, excl_opt, 1)
            except OSError:
                pass
        try:
            sock.bind((bind_host, int(port)))
            return True
        except OSError:
            return False


def pick_available_port(
    host: str,
    preferred_port: int,
    *,
    exclude_ports: set[int] | None = None,
    max_tries: int = 30,
) -> int:
    """Pick `preferred_port` if free, otherwise scan upward for an available local TCP port."""
    excluded = exclude_ports or set()
    for offset in range(max(1, max_tries)):
        cand = int(preferred_port) + offset
        if cand in excluded or cand > 65535:
            continue
        if is_port_available(host, cand):
            return cand
    bind_host = "127.0.0.1" if host in ("0.0.0.0", "::", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((bind_host, 0))
        return int(sock.getsockname()[1])


