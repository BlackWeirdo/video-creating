"""Encrypted secrets store using Windows DPAPI (CryptProtectData) or chmod 600 on Linux."""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import threading
from pathlib import Path

CRYPTPROTECT_UI_FORBIDDEN = 0x01

_ACTIVE_SECRET_VALUES: set[str] = set()
_LOCK = threading.RLock()


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _dpapi_encrypt(raw: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.c_wchar_p,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = ctypes.wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    buf = ctypes.create_string_buffer(raw, len(raw))
    in_blob = _DataBlob(
        len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    )
    out_blob = _DataBlob()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "VideoCreatorSecrets",
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        err = ctypes.GetLastError()
        raise OSError(f"CryptProtectData failed with error code {err}")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def _dpapi_decrypt(cipher: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    buf = ctypes.create_string_buffer(cipher, len(cipher))
    in_blob = _DataBlob(
        len(cipher), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))
    )
    out_blob = _DataBlob()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(out_blob),
    )
    if not ok:
        err = ctypes.GetLastError()
        raise OSError(f"CryptUnprotectData failed with error code {err}")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(out_blob.pbData, ctypes.c_void_p))


def register_secret_for_redaction(value: str) -> None:
    cleaned = value.strip()
    if len(cleaned) >= 6:
        with _LOCK:
            _ACTIVE_SECRET_VALUES.add(cleaned)


def get_registered_secret_values() -> list[str]:
    with _LOCK:
        return sorted(_ACTIVE_SECRET_VALUES, key=len, reverse=True)


class SecretsStore:
    """Stores key-value secrets in DPAPI-encrypted file on Windows or 0600 file on POSIX."""

    def __init__(self, secrets_file: Path) -> None:
        self.secrets_file = secrets_file
        self._lock = threading.RLock()
        self._sync_redaction_cache()

    def _read_all(self) -> dict[str, str]:
        if not self.secrets_file.exists():
            return {}
        raw_bytes = self.secrets_file.read_bytes()
        if not raw_bytes:
            return {}
        if os.name == "nt":
            plain_bytes = _dpapi_decrypt(raw_bytes)
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
            out_bytes = _dpapi_encrypt(plain_bytes)
        else:
            out_bytes = plain_bytes
        tmp_path = self.secrets_file.with_suffix(".bin.tmp")
        tmp_path.write_bytes(out_bytes)
        if os.name != "nt":
            os.chmod(tmp_path, 0o600)
        tmp_path.replace(self.secrets_file)
        if os.name != "nt":
            os.chmod(self.secrets_file, 0o600)

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
