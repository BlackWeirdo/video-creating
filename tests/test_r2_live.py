"""Live Cloudflare R2 upload, public GET verification, and delete test (Phase 07)."""
from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from videocreator.config import load_settings, save_settings
from videocreator.db import migrate
from videocreator.paths import get_paths
from videocreator.posting.storage_r2 import delete_from_r2, upload_to_r2
from videocreator.secrets_store import SecretsStore

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
CLIP_PORTRAIT = SAMPLES_DIR / "clip1_6s.mp4"


@pytest.mark.live
def test_r2_live_upload_get_and_delete(tmp_path: Path) -> None:
    account_id = os.environ.get("R2_ACCOUNT_ID")
    access_key = os.environ.get("R2_ACCESS_KEY_ID")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY")
    bucket = os.environ.get("R2_BUCKET")
    public_base = os.environ.get("R2_PUBLIC_BASE")
    if not (account_id and access_key and secret_key and bucket and public_base):
        pytest.skip("R2 environment variables not configured for live R2 test")

    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    sec = SecretsStore(paths.secrets_file)
    sec.set("R2_ACCOUNT_ID", account_id)
    sec.set("R2_ACCESS_KEY_ID", access_key)
    sec.set("R2_SECRET_ACCESS_KEY", secret_key)

    cfg = load_settings(paths.config_file)
    cfg.r2.bucket = bucket
    cfg.r2.public_base = public_base
    save_settings(paths.config_file, cfg)

    obj_key, pub_url = upload_to_r2(paths, CLIP_PORTRAIT, secrets_store=sec)
    try:
        resp = httpx.head(pub_url, timeout=30.0, follow_redirects=True)
        assert resp.status_code == 200
    finally:
        delete_from_r2(paths, obj_key, secrets_store=sec)
