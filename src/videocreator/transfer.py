"""Encrypted configuration, database, and secrets export/import (.vcx bundle, Phase 08)."""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from videocreator.config import load_settings, save_settings
from videocreator.db import get_user_version, max_supported_migration_version, migrate
from videocreator.job_store import recover_interrupted_jobs, set_queue_paused
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.studio.session import recover_stuck_studio_sessions


logger = logging.getLogger("videocreator.transfer")


class ExportPasswordError(ValueError):
    """Raised when the export/import password is missing or invalid."""


def _derive_fernet_key(password: str, salt: bytes) -> bytes:
    raw_key = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return base64.urlsafe_b64encode(raw_key)


def export_config_bundle(
    paths: AppPaths,
    password: str,
    dest_vcx: Path,
    *,
    secrets_store: SecretsStore | None = None,
) -> Path:
    """Creates a password-encrypted `.vcx` archive containing `config.toml`, `app.db`, and encrypted secrets."""
    clean_pw = password.strip()
    if len(clean_pw) < 4:
        raise ExportPasswordError("Password must be at least 4 characters")

    sec = secrets_store or SecretsStore(paths.secrets_file)
    secret_map: dict[str, str] = {}
    for k in sec.list_keys():
        val = sec.get(k)
        if val is not None:
            secret_map[k] = val

    salt = os.urandom(16)
    fernet = Fernet(_derive_fernet_key(clean_pw, salt))
    plaintext_bytes = json.dumps(secret_map, ensure_ascii=False).encode("utf-8")
    ciphertext = fernet.encrypt(plaintext_bytes)
    secrets_bundle = {
        "kdf": "scrypt",
        "salt_b64": base64.b64encode(salt).decode("ascii"),
        "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
    }

    dest_vcx.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="vc-export-"))
    try:
        db_snapshot = tmp_dir / "app.db"
        if paths.db_file.exists():
            src_conn = sqlite3.connect(str(paths.db_file))
            dst_conn = sqlite3.connect(str(db_snapshot))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()

        if not paths.config_file.exists():
            save_settings(paths.config_file, load_settings(paths.config_file))

        with zipfile.ZipFile(dest_vcx, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(paths.config_file, arcname="config.toml")
            if db_snapshot.exists():
                zf.write(db_snapshot, arcname="app.db")
            zf.writestr("secrets.enc.json", json.dumps(secrets_bundle, indent=2))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    return dest_vcx


MAX_VCX_TOTAL_BYTES = 512 * 1024 * 1024  # 512 MB ceiling for config + SQLite DB
MAX_SECRETS_MEMBER_BYTES = 4 * 1024 * 1024
ALLOWED_VCX_MEMBERS = frozenset({"secrets.enc.json", "config.toml", "app.db"})


def import_config_bundle(
    paths: AppPaths,
    source_vcx: Path,
    password: str,
    *,
    as_server: bool = False,
    secrets_store: SecretsStore | None = None,
) -> None:
    """Verifies password, then restores `config.toml`, `app.db`, and `secrets.bin` into `paths`.

    Defaults `settings.role = 'client'` unless `as_server=True` (FR-OPS-03).
    """
    if not source_vcx.exists():
        raise FileNotFoundError(f"Export bundle not found: {source_vcx}")
    clean_pw = password.strip()
    if not clean_pw:
        raise ExportPasswordError("Password is required to import configuration")

    tmp_dir = Path(tempfile.mkdtemp(prefix="vc-import-"))
    try:
        try:
            with zipfile.ZipFile(source_vcx, "r") as zf:
                infos = zf.infolist()
                names = {info.filename for info in infos}
                if "secrets.enc.json" not in names:
                    raise ValueError("Archive is missing secrets.enc.json")
                unexpected = names - ALLOWED_VCX_MEMBERS
                if unexpected:
                    raise ValueError(f"Archive contains unexpected entries: {sorted(unexpected)}")
                total_uncompressed = sum(max(0, info.file_size) for info in infos)
                if total_uncompressed > MAX_VCX_TOTAL_BYTES:
                    raise ValueError("Archive exceeds maximum allowed size")
                sec_info = zf.getinfo("secrets.enc.json")
                if sec_info.file_size > MAX_SECRETS_MEMBER_BYTES:
                    raise ValueError("secrets.enc.json is unexpectedly large")

                # Verify password BEFORE extracting app.db or config.toml to disk
                bundle_meta = json.loads(zf.read("secrets.enc.json").decode("utf-8"))
                salt = base64.b64decode(bundle_meta["salt_b64"])
                ciphertext = base64.b64decode(bundle_meta["ciphertext_b64"])
                fernet = Fernet(_derive_fernet_key(clean_pw, salt))
                try:
                    decrypted_bytes = fernet.decrypt(ciphertext)
                except InvalidToken as exc:
                    raise ExportPasswordError("Sai mật khẩu giải mã file cấu hình (.vcx)") from exc

                secret_map: dict[str, str] = json.loads(decrypted_bytes.decode("utf-8"))
                for member in ("config.toml", "app.db"):
                    if member in names:
                        zf.extract(member, path=tmp_dir)
        except zipfile.BadZipFile as exc:
            raise ValueError("Invalid .vcx archive file") from exc

        # Validate archive DB schema version BEFORE overwriting config.toml, app.db, or secrets
        extracted_db = tmp_dir / "app.db"
        if extracted_db.exists():
            max_ver = max_supported_migration_version()
            probe_conn = sqlite3.connect(str(extracted_db))
            try:
                src_ver = get_user_version(probe_conn)
            finally:
                probe_conn.close()
            if src_ver > max_ver:
                raise ValueError(
                    f"Bản sao lưu .vcx thuộc phiên bản mới hơn (user_version={src_ver} > {max_ver}), không thể khôi phục."
                )

        # Password & schema verified! Pause queue during swap, then replace config.toml, app.db, and secrets
        if paths.db_file.exists():
            try:
                set_queue_paused(paths.db_file, True)
            except sqlite3.Error as exc:
                logger.debug("Could not mark pre-restore DB paused: %s", exc)

        extracted_cfg = tmp_dir / "config.toml"
        if extracted_cfg.exists():
            shutil.copy2(extracted_cfg, paths.config_file)
        settings = load_settings(paths.config_file)
        settings.role = "server" if as_server else "client"
        save_settings(paths.config_file, settings)

        if extracted_db.exists():
            src_conn = sqlite3.connect(str(extracted_db))
            dst_conn = sqlite3.connect(str(paths.db_file))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()
            migrate(paths.db_file)
            recover_interrupted_jobs(paths.db_file)
            recover_stuck_studio_sessions(paths.db_file)
            from videocreator.api.v1.routes_system import clear_nav_counts_cache

            clear_nav_counts_cache()

        sec = secrets_store or SecretsStore(paths.secrets_file)
        sec.replace_all({str(k): str(v) for k, v in secret_map.items()})
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
