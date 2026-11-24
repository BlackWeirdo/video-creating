"""Filesystem paths and directory layout for Video Creator."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "VideoCreator"
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
    bundled = REPO_ROOT / "ffmpeg" / "bin" / f"{name}.exe"
    if bundled.exists():
        return str(bundled)
    runtime_bundled = REPO_ROOT / "runtime" / "ffmpeg" / f"{name}.exe"
    if runtime_bundled.exists():
        return str(runtime_bundled)
    found = shutil.which(name)
    if found:
        return found
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        winget_link = Path(local_app_data) / "Microsoft" / "WinGet" / "Links" / f"{name}.exe"
        if winget_link.exists():
            return str(winget_link)
        winget_pkgs = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_pkgs.exists():
            matches = sorted(winget_pkgs.glob(f"Gyan.FFmpeg*/ffmpeg-*/bin/{name}.exe"))
            if matches:
                return str(matches[-1])
    return name


def find_node_runtime() -> str | None:
    """Locate the Node.js binary, preferring the project or bundled Node 24 LTS runtime."""
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

