"""Cloudflare R2 S3-compatible temporary video staging with 32-hex random keys (Phase 07, NFR-SEC-08)."""
from __future__ import annotations

import logging
import secrets
from pathlib import Path

from videocreator.config import load_settings
from videocreator.paths import AppPaths
from videocreator.posting.base import PermanentPostError, TransientPostError
from videocreator.secrets_store import SecretsStore


def _get_r2_client_and_config(
    paths: AppPaths,
    secrets_store: SecretsStore | None = None,
):  # type: ignore[no-untyped-def]
    sec = secrets_store or SecretsStore(paths.secrets_file)
    settings = load_settings(paths.config_file)
    account_id = sec.get("R2_ACCOUNT_ID")
    access_key = sec.get("R2_ACCESS_KEY_ID")
    secret_key = sec.get("R2_SECRET_ACCESS_KEY")
    bucket = settings.r2.bucket.strip()
    public_base = settings.r2.public_base.strip().rstrip("/")

    if not (account_id and access_key and secret_key and bucket and public_base):
        raise PermanentPostError(
            "Cloudflare R2 is not fully configured (need R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, r2.bucket, r2.public_base)"
        )

    import boto3
    from botocore.config import Config as BotoConfig

    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=BotoConfig(signature_version="s3v4"),
    )
    return client, bucket, public_base


def upload_to_r2(
    paths: AppPaths,
    video_path: Path,
    *,
    secrets_store: SecretsStore | None = None,
) -> tuple[str, str]:
    """Uploads `video_path` to R2 under a random 32-hex key and returns `(object_key, public_url)`."""
    if not video_path.exists():
        raise PermanentPostError(f"Video file does not exist for R2 upload: {video_path}")

    client, bucket, public_base = _get_r2_client_and_config(paths, secrets_store)
    object_key = f"videos/{secrets.token_hex(16)}.mp4"

    try:
        client.upload_file(
            str(video_path),
            bucket,
            object_key,
            ExtraArgs={"ContentType": "video/mp4"},
        )
    except Exception as exc:
        raise TransientPostError(f"R2 upload failed: {exc}") from exc

    return object_key, f"{public_base}/{object_key}"


def delete_from_r2(
    paths: AppPaths,
    object_key: str,
    *,
    secrets_store: SecretsStore | None = None,
) -> bool:
    """Deletes `object_key` from the R2 bucket. Returns False when it could not be deleted (retried later)."""
    if not object_key:
        return True
    try:
        client, bucket, _ = _get_r2_client_and_config(paths, secrets_store)
        client.delete_object(Bucket=bucket, Key=object_key)
        return True
    except Exception as exc:
        logging.getLogger("videocreator.posting.storage_r2").warning("R2 delete failed for %s: %s", object_key, exc)
        return False
