"""Shared streaming upload helpers with extension allowlists and byte-size ceilings."""
from __future__ import annotations

import uuid
from collections.abc import Collection
from pathlib import Path

from fastapi import HTTPException, UploadFile

from videocreator.safe_paths import validated_extension

MAX_FOOTAGE_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB
MAX_LOCALIZE_UPLOAD_BYTES = 1024 * 1024 * 1024  # 1 GB
MAX_IMAGE_OR_VOICE_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


async def save_upload_to_temp(
    file: UploadFile,
    work_dir: Path,
    *,
    allowed_extensions: Collection[str] | None = None,
    default_ext: str = "",
    max_bytes: int = MAX_FOOTAGE_UPLOAD_BYTES,
    prefix: str = "upload",
    invalid_ext_message: str | None = None,
    too_large_message: str | None = None,
) -> Path:
    """Streams an `UploadFile` to `work_dir/<prefix>_<uuid><ext>`, enforcing extension and size limits."""
    ext = default_ext
    if allowed_extensions is not None:
        try:
            ext = validated_extension(
                file.filename, allowed_extensions, default_ext=default_ext
            )
        except ValueError as exc:
            raw_ext = Path(file.filename or "").suffix.lower() or default_ext
            msg = invalid_ext_message or f"Định dạng tệp không hợp lệ: {raw_ext}"
            raise HTTPException(status_code=400, detail=msg) from exc

    work_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = work_dir / f"{prefix}_{uuid.uuid4().hex}{ext}"
    written = 0
    try:
        with tmp_path.open("wb") as out_fh:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    limit_mb = max(1, max_bytes // (1024 * 1024))
                    raise HTTPException(
                        status_code=413,
                        detail=too_large_message or f"Tệp tải lên vượt quá giới hạn {limit_mb} MB",
                    )
                out_fh.write(chunk)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise
    return tmp_path


async def read_upload_bytes_checked(
    file: UploadFile,
    *,
    allowed_extensions: Collection[str] | None = None,
    default_ext: str = "",
    min_bytes: int = 1,
    max_bytes: int = MAX_IMAGE_OR_VOICE_UPLOAD_BYTES,
    invalid_ext_message: str | None = None,
    empty_message: str = "Tệp tải lên rỗng",
) -> tuple[bytes, str]:
    """Reads bounded upload bytes into memory after extension & size validation."""
    ext = default_ext
    if allowed_extensions is not None:
        try:
            ext = validated_extension(
                file.filename, allowed_extensions, default_ext=default_ext
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail=invalid_ext_message or str(exc)
            ) from exc

    buf = bytearray()
    while chunk := await file.read(512 * 1024):
        buf.extend(chunk)
        if len(buf) > max_bytes:
            limit_mb = max(1, max_bytes // (1024 * 1024))
            raise HTTPException(
                status_code=413,
                detail=f"Tệp tải lên vượt quá giới hạn {limit_mb} MB",
            )
    if len(buf) < min_bytes:
        raise HTTPException(status_code=400, detail=empty_message)
    return bytes(buf), ext
