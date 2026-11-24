"""One-shot admin utility to mirror verified local AI models into the company Cloudflare R2 bucket.

Usage:
    uv run python scripts/push_models_to_r2.py [--model-id MODEL_ID] [--prefix models] [--download-missing]

After pushing, set `models.mirror_base_url = "https://<r2.public_base>/models"` in Settings.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

from videocreator.db import migrate
from videocreator.models_manager import get_local_model, install_local_model, list_local_models
from videocreator.paths import get_paths
from videocreator.posting.storage_r2 import _get_r2_client_and_config


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def push_models(
    *,
    data_dir: Path | None = None,
    model_id: str | None = None,
    prefix: str = "models",
    download_missing: bool = False,
) -> list[str]:
    paths = get_paths(data_dir)
    migrate(paths.db_file, paths.migrations_dir)
    client, bucket, public_base = _get_r2_client_and_config(paths)
    clean_prefix = prefix.strip().strip("/")

    catalog = [get_local_model(paths, model_id)] if model_id else list_local_models(paths)
    uploaded_urls: list[str] = []

    for entry in catalog:
        if entry is None:
            raise ValueError(f"Unknown model_id: {model_id}")
        mid = str(entry["model_id"])
        files_spec = list(entry.get("files") or [])
        if not entry.get("installed_on_disk"):
            if not download_missing:
                print(f"[SKIP] {mid}: not installed on disk (pass --download-missing to fetch first)")
                continue
            print(f"[FETCH] Downloading & verifying {mid} before mirroring...")
            entry = install_local_model(paths, mid, verify_smoke=False)

        model_dir = paths.models_dir / mid
        for fspec in files_spec:
            fname = str(fspec.get("filename") or "").strip()
            expected_sha = str(fspec.get("sha256") or "").strip().lower()
            fpath = model_dir / fname
            if not fpath.is_file():
                raise FileNotFoundError(f"Missing expected model file: {fpath}")
            actual_sha = _sha256_file(fpath).lower()
            if expected_sha and actual_sha != expected_sha:
                raise ValueError(f"SHA-256 mismatch on {fpath}: expected {expected_sha}, got {actual_sha}")

            obj_key = f"{clean_prefix}/{mid}/{fname}" if clean_prefix else f"{mid}/{fname}"
            print(f"[UPLOAD] {fpath.name} ({fpath.stat().st_size} bytes) -> s3://{bucket}/{obj_key}")
            client.upload_file(
                str(fpath),
                bucket,
                obj_key,
                ExtraArgs={"ContentType": "application/octet-stream"},
            )
            url = f"{public_base}/{obj_key}"
            uploaded_urls.append(url)

    mirror_hint = f"{public_base}/{clean_prefix}" if clean_prefix else public_base
    print(f"\nUploaded {len(uploaded_urls)} model file(s). Suggested mirror_base_url: {mirror_hint}")
    return uploaded_urls


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Push verified local AI models to Cloudflare R2 mirror.")
    parser.add_argument("--data-dir", type=Path, default=None, help="Override VIDEOCREATOR_DATA directory")
    parser.add_argument("--model-id", type=str, default=None, help="Push only a single model_id")
    parser.add_argument("--prefix", type=str, default="models", help="Object key prefix inside R2 bucket")
    parser.add_argument(
        "--download-missing",
        action="store_true",
        help="Download missing models from primary URLs before mirroring to R2",
    )
    args = parser.parse_args(argv)
    try:
        push_models(
            data_dir=args.data_dir,
            model_id=args.model_id,
            prefix=args.prefix,
            download_missing=args.download_missing,
        )
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
