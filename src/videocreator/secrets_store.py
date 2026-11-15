"""Encrypted secrets store using Windows DPAPI (CryptProtectData) or chmod 600 on Linux."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from videocreator.dpapi import dpapi_decrypt, dpapi_encrypt

_ACTIVE_SECRET_VALUES: set[str] = set()
_LOCK = threading.RLock()


def register_secret_for_redaction(value: str) -> None:
    cleaned = value.strip()
    if len(cleaned) >= 6:
        with _LOCK:
            _ACTIVE_SECRET_VALUES.add(cleaned)


def get_registered_secret_values() -> list[str]:
    with _LOCK:
        return sorted(_ACTIVE_SECRET_VALUES, key=len, reverse=True)


# Decrypted secrets per file, valid while the file's (mtime, size) signature is unchanged.
_DECRYPTED_CACHE: dict[Path, tuple[tuple[int, int], dict[str, str]]] = {}

class SecretsStore:
    """Stores key-value secrets in DPAPI-encrypted file on Windows or 0600 file on POSIX."""

    def __init__(self, secrets_file: Path) -> None:
        self.secrets_file = secrets_file
        self._lock = threading.RLock()
        self._sync_redaction_cache()

    def _read_all(self) -> dict[str, str]:
        """All secrets; the file is read and decrypted again only when it changed on disk."""
        try:
            stat = self.secrets_file.stat()
        except FileNotFoundError:
            return {}
        signature = (stat.st_mtime_ns, stat.st_size)
        with _LOCK:
            cached = _DECRYPTED_CACHE.get(self.secrets_file)
        if cached is not None and cached[0] == signature:
            return dict(cached[1])
        data = self._read_file()
        with _LOCK:
            _DECRYPTED_CACHE[self.secrets_file] = (signature, data)
        return dict(data)

    def _read_file(self) -> dict[str, str]:
        raw_bytes = self.secrets_file.read_bytes()
        if not raw_bytes:
            return {}
        if os.name == "nt":
            plain_bytes = dpapi_decrypt(raw_bytes)
        else:
            plain_bytes = raw_bytes
        data = json.loads(plain_bytes.decode("utf-8"))
        if not isinstance(data, dict):
            return {}
        return {str(k): str(v) for k, v in data.items()}

    def _write_all(self, data: dict[str, str]) -> None:
        self.secrets_file.parent.mkdir(parents=True, exist_ok=True)
        plain_bytes = json.dumps(data, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if os.name == "nt":
            out_bytes = dpapi_encrypt(plain_bytes)
        else:
            out_bytes = plain_bytes
        tmp_path = self.secrets_file.with_suffix(".bin.tmp")
        tmp_path.write_bytes(out_bytes)
        if os.name != "nt":
            os.chmod(tmp_path, 0o600)
        tmp_path.replace(self.secrets_file)
        if os.name != "nt":
            os.chmod(self.secrets_file, 0o600)
        with _LOCK:
            _DECRYPTED_CACHE.pop(self.secrets_file, None)

    def _sync_redaction_cache(self) -> None:
        try:
            data = self._read_all()
        except Exception:
            return
        for val in data.values():
            register_secret_for_redaction(val)

    def get(self, name: str) -> str | None:
        with self._lock:
            data = self._read_all()
            val = data.get(name)
            if val:
                register_secret_for_redaction(val)
            return val

    def set(self, name: str, value: str) -> None:
        with self._lock:
            data = self._read_all()
            data[name] = value
            self._write_all(data)
            register_secret_for_redaction(value)

    def delete(self, name: str) -> bool:
        with self._lock:
            data = self._read_all()
            if name not in data:
                return False
            del data[name]
            self._write_all(data)
            return True

    def list_keys(self) -> list[str]:
        with self._lock:
            return sorted(self._read_all().keys())

    def has(self, name: str) -> bool:
        val = self.get(name)
        return bool(val and val.strip())
