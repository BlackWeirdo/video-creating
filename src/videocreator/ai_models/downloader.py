"""HTTP Range `.part` downloader, mirror failover, SHA-256 verification, and model install/remove."""
from __future__ import annotations

import hashlib
import logging
import shutil
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from videocreator.ai_models.catalog import (
    get_local_model,
    get_local_model_by_rowid,
    set_model_state,
)
from videocreator.ai_models.smoke import verify_model_smoke_test
from videocreator.config import load_settings
from videocreator.db import get_conn, record_audit
from videocreator.paths import AppPaths

logger = logging.getLogger("videocreator.models_manager")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _looks_like_html_payload(first_chunk: bytes) -> bool:
    head = first_chunk.lstrip()[:64].lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def download_file_verified(
    *,
    model_id: str,
    filename: str,
    candidate_urls: list[str],
    expected_sha256: str,
    dest_dir: Path,
    on_bytes: Callable[[int, int], None] | None = None,
) -> tuple[Path, str]:
    """Downloads `filename` into `dest_dir` with `.part` HTTP Range resume, HTML rejection & SHA-256 check."""
    dest_file = dest_dir / filename
    part_file = dest_dir / f"{filename}.part"
    exp_hash = expected_sha256.strip().lower()

    if dest_file.is_file() and exp_hash:
        cur_hash = sha256_file(dest_file).lower()
        if cur_hash == exp_hash:
            sz = dest_file.stat().st_size
            if on_bytes:
                on_bytes(sz, sz)
            return dest_file, cur_hash
        dest_file.unlink(missing_ok=True)

    last_err: Exception | None = None
    for url in candidate_urls:
        clean_url = url.strip()
        if not clean_url:
            continue
        try:
            offset = part_file.stat().st_size if part_file.is_file() else 0
            headers = {"User-Agent": "VideoCreatorV2/2.0"}
            if offset > 0:
                headers["Range"] = f"bytes={offset}-"
            req = urllib.request.Request(clean_url, headers=headers)
            try:
                resp_ctx = urllib.request.urlopen(req, timeout=90.0)
            except urllib.error.HTTPError as http_exc:
                if http_exc.code == 416 and part_file.is_file() and exp_hash:
                    cur_hash = sha256_file(part_file).lower()
                    if cur_hash == exp_hash:
                        part_file.replace(dest_file)
                        return dest_file, cur_hash
                    part_file.unlink(missing_ok=True)
                raise

            with resp_ctx as resp:
                ctype = str(resp.headers.get("Content-Type") or "").lower()
                if ctype.startswith("text/html") or "application/xhtml" in ctype:
                    part_file.unlink(missing_ok=True)
                    raise ValueError(
                        f"Server returned HTML instead of binary model for '{filename}' ({ctype})"
                    )
                status_code = int(getattr(resp, "status", 200) or 200)
                content_len = int(resp.headers.get("Content-Length") or 0)
                if offset > 0 and status_code == 206:
                    mode = "ab"
                    written = offset
                    total_expected = offset + content_len if content_len > 0 else 0
                else:
                    mode = "wb"
                    written = 0
                    total_expected = content_len

                first_chunk_checked = written > 0
                with part_file.open(mode) as out_fh:
                    while True:
                        buf = resp.read(256 * 1024)
                        if not buf:
                            break
                        if not first_chunk_checked:
                            first_chunk_checked = True
                            if _looks_like_html_payload(buf):
                                out_fh.close()
                                part_file.unlink(missing_ok=True)
                                raise ValueError(
                                    f"Server returned HTML body instead of binary model for '{filename}'"
                                )
                        out_fh.write(buf)
                        written += len(buf)
                        if on_bytes:
                            on_bytes(written, total_expected)

            digest = sha256_file(part_file).lower()
            if exp_hash and digest != exp_hash:
                part_file.unlink(missing_ok=True)
                raise ValueError(
                    f"SHA-256 mismatch for '{model_id}/{filename}': expected {exp_hash}, got {digest}"
                )
            part_file.replace(dest_file)
            return dest_file, digest
        except Exception as exc:
            last_err = exc
            logger.warning(
                "Download attempt failed for %s/%s from %s: %s",
                model_id,
                filename,
                clean_url,
                exc,
            )
            continue

    assert last_err is not None
    raise last_err


def _install_from_local_source(
    src: Path,
    model_dir: Path,
    model_id: str,
    files_spec: list[dict[str, Any]],
    expected_sha256: str | None,
) -> tuple[Path, str]:
    if not src.exists():
        raise FileNotFoundError(f"Model source not found: {src}")
    if src.is_dir():
        for child in src.iterdir():
            target_child = model_dir / child.name
            if child.is_dir():
                if target_child.exists():
                    shutil.rmtree(target_child)
                shutil.copytree(child, target_child)
            else:
                shutil.copy2(child, target_child)
        dest = model_dir
        hasher = hashlib.sha256()
        for fpath in sorted(p for p in model_dir.rglob("*") if p.is_file()):
            hasher.update(sha256_file(fpath).encode("ascii"))
        digest = hasher.hexdigest()
    else:
        target_name = (
            str(files_spec[0]["filename"])
            if len(files_spec) == 1 and files_spec[0].get("filename")
            else src.name
        )
        dest = model_dir / target_name
        shutil.copy2(src, dest)
        digest = sha256_file(dest)

    check_sha = (
        expected_sha256.strip().lower()
        if expected_sha256
        else (
            str(files_spec[0].get("sha256") or "").strip().lower()
            if len(files_spec) == 1 and not src.is_dir() and expected_sha256 is not None
            else ""
        )
    )
    if check_sha and digest.lower() != check_sha:
        if dest.is_file():
            dest.unlink(missing_ok=True)
        raise ValueError(
            f"SHA-256 mismatch for model '{model_id}': expected {check_sha}, got {digest}"
        )
    return dest, digest


def install_local_model(
    paths: AppPaths,
    model_id: str,
    *,
    local_source_path: Path | str | None = None,
    expected_sha256: str | None = None,
    verify_smoke: bool = True,
) -> dict[str, Any]:
    """Installs a local model into `paths.models_dir/<model_id>` with SHA-256 verification and CPU smoke test."""
    info = get_local_model(paths, model_id)
    if info is None:
        raise ValueError(f"Unknown local model '{model_id}'")

    model_dir = paths.models_dir / model_id
    model_dir.mkdir(parents=True, exist_ok=True)
    set_model_state(
        paths,
        model_id,
        status="downloading",
        progress=0.02,
        smoke_tested=False,
        error=None,
    )

    files_spec: list[dict[str, Any]] = list(info.get("files") or [])

    try:
        if local_source_path is not None:
            src = Path(local_source_path).expanduser().resolve()
            dest, digest = _install_from_local_source(
                src, model_dir, model_id, files_spec, expected_sha256
            )
        else:
            mirror_base = load_settings(paths.config_file).models.mirror_base_url.strip().rstrip("/")
            if not files_spec:
                raw_url = str(info.get("download_url") or "").strip()
                if not raw_url:
                    raise RuntimeError(f"Model '{model_id}' has no configured download files")
                fname = Path(raw_url.split("?", 1)[0]).name or f"{model_id}.bin"
                files_spec = [
                    {
                        "filename": fname,
                        "url": raw_url,
                        "sha256": expected_sha256 or str(info.get("sha256") or ""),
                        "size_bytes": int(info.get("size_mb") or 0) * 1024 * 1024,
                    }
                ]

            total_catalog_bytes = sum(max(0, int(f.get("size_bytes") or 0)) for f in files_spec)
            completed_bytes = 0
            per_file_digests: list[str] = []
            downloaded_paths: list[Path] = []

            for idx, fspec in enumerate(files_spec):
                fname = str(fspec.get("filename") or "").strip()
                primary_url = str(fspec.get("url") or "").strip()
                if not fname or not primary_url:
                    raise ValueError(f"Invalid file specification in catalog for '{model_id}'")
                f_sha = (
                    expected_sha256.strip()
                    if (expected_sha256 and len(files_spec) == 1)
                    else str(fspec.get("sha256") or "").strip()
                )
                f_size = max(0, int(fspec.get("size_bytes") or 0))
                candidates: list[str] = []
                if mirror_base:
                    candidates.append(f"{mirror_base}/{model_id}/{fname}")
                candidates.append(primary_url)

                base_done = completed_bytes

                def _progress_cb(
                    cur_written: int, cur_total: int, _base: int = base_done, _idx: int = idx
                ) -> None:
                    denom = total_catalog_bytes if total_catalog_bytes > 0 else max(1, cur_total)
                    pct_raw = (
                        (_base + cur_written) / denom
                        if denom > 0
                        else (_idx + 0.5) / len(files_spec)
                    )
                    pct = min(0.92, max(0.05, pct_raw * 0.92))
                    set_model_state(paths, model_id, status="downloading", progress=round(pct, 3))

                dl_path, f_digest = download_file_verified(
                    model_id=model_id,
                    filename=fname,
                    candidate_urls=candidates,
                    expected_sha256=f_sha,
                    dest_dir=model_dir,
                    on_bytes=_progress_cb,
                )
                downloaded_paths.append(dl_path)
                per_file_digests.append(f_digest)
                completed_bytes += f_size if f_size > 0 else dl_path.stat().st_size

            if len(downloaded_paths) == 1:
                dest = downloaded_paths[0]
                digest = per_file_digests[0]
            else:
                dest = model_dir
                digest = hashlib.sha256(":".join(per_file_digests).encode("ascii")).hexdigest()

        set_model_state(
            paths,
            model_id,
            status="downloaded",
            progress=0.95,
            local_path=str(dest),
            sha256=digest,
            smoke_tested=False,
            error=None,
        )
        with get_conn(paths.db_file) as conn:
            record_audit(
                conn,
                actor="models_manager",
                action="download_model",
                object_type="local_model",
                detail=f"{model_id} -> {dest}",
            )

        if verify_smoke:
            return verify_model_smoke_test(paths, model_id)

        updated = get_local_model(paths, model_id)
        assert updated is not None
        return updated
    except Exception as exc:
        cur_info = get_local_model(paths, model_id)
        if cur_info and cur_info["status"] != "downloaded":
            set_model_state(paths, model_id, status="failed", smoke_tested=False, error=str(exc))
        raise


def remove_local_model(paths: AppPaths, model_id: str) -> dict[str, Any]:
    info = get_local_model(paths, model_id)
    if info is None:
        raise ValueError(f"Unknown local model '{model_id}'")

    model_dir = paths.models_dir / model_id
    if model_dir.exists():
        shutil.rmtree(model_dir, ignore_errors=True)
    set_model_state(
        paths,
        model_id,
        status="not_installed",
        progress=0.0,
        local_path="",
        sha256="",
        smoke_tested=False,
        error=None,
    )
    with get_conn(paths.db_file) as conn:
        record_audit(
            conn,
            actor="models_manager",
            action="remove_model",
            object_type="local_model",
            detail=model_id,
        )
    updated = get_local_model(paths, model_id)
    assert updated is not None
    return updated


def run_download_model_job(paths: AppPaths, rowid: int) -> str:
    """Background `io` worker handler triggered by `enqueue_job(..., 'download_model', ref_id=rowid)`."""
    info = get_local_model_by_rowid(paths, rowid)
    if info is None:
        raise ValueError(f"Model rowid={rowid} not found")
    installed = install_local_model(paths, str(info["model_id"]), verify_smoke=True)
    return str(installed["status"])
