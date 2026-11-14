"""MoneyPrinterTurbo child-process manager (Phase 09). The app only uses MPT for voice-over + SRT."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import httpx
import tomli_w

from videocreator.config import Settings, load_settings
from videocreator.paths import AppPaths, REPO_ROOT

logger = logging.getLogger("videocreator.engines.mpt_service")


def mpt_dir() -> Path:
    """Install location of the pinned MoneyPrinterTurbo checkout (see installer/install_mpt.cmd)."""
    return REPO_ROOT / "tools" / "mpt"


def write_mpt_config(settings: Settings, install_dir: Path | None = None) -> Path:
    """Writes MPT's own `config.toml` from its shipped example, bound to 127.0.0.1 and our port.

    MPT reads `config.toml` from its install directory. Stock footage, LLM script writing and
    bundled music are never requested by the app (it only calls the voice/subtitle endpoint);
    the bundled songs folder is removed at start as a second guard (`FR-REN-04`, `FR-REN-08`).
    """
    root = install_dir or mpt_dir()
    with (root / "config.example.toml").open("rb") as f:
        cfg = tomllib.load(f)
    cfg["listen_host"] = "127.0.0.1"
    cfg["listen_port"] = int(settings.mpt.port)
    cfg.setdefault("app", {})["video_source"] = "local"
    cfg["app"]["subtitle_provider"] = "edge"
    out_file = root / "config.toml"
    with out_file.open("wb") as f:
        tomli_w.dump(cfg, f)
    return out_file


class MPTServiceManager:
    """Manages the local MoneyPrinterTurbo FastAPI child process (`127.0.0.1:<port>`)."""

    def __init__(self, paths: AppPaths) -> None:
        self.paths = paths
        self.proc: subprocess.Popen[bytes] | None = None

    @property
    def base_url(self) -> str:
        cfg = load_settings(self.paths.config_file)
        return f"http://127.0.0.1:{cfg.mpt.port}"

    def is_installed(self) -> bool:
        return (mpt_dir() / ".venv" / "Scripts" / "python.exe").exists()

    def is_healthy(self, timeout_s: float = 1.5) -> bool:
        try:
            return httpx.get(f"{self.base_url}/docs", timeout=timeout_s).status_code == 200
        except Exception:
            return False

    def start(self) -> bool:
        """Starts MPT if installed and not already running. Returns True when a process is up or was launched."""
        cfg = load_settings(self.paths.config_file)
        if cfg.role != "server":
            return False
        if self.is_healthy():
            return True
        if not self.is_installed():
            logger.info("MoneyPrinterTurbo not installed in %s; videos render without voice-over", mpt_dir())
            return False

        root = mpt_dir()
        shutil.rmtree(root / "resource" / "songs", ignore_errors=True)
        try:
            write_mpt_config(cfg, root)
            self.proc = subprocess.Popen(
                [str(root / ".venv" / "Scripts" / "python.exe"), "main.py"],
                cwd=str(root),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            return True
        except Exception as exc:
            logger.warning("Failed to start MoneyPrinterTurbo (continuing without voice-over): %s", exc)
            self.proc = None
            return False

    def stop(self) -> None:
        if self.proc is None:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5.0)
        except Exception:
            self.proc.kill()
        self.proc = None
