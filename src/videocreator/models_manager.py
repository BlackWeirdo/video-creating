"""On-demand Local AI Models Manager (`VIDEOCREATOR_DATA/models`), downloader, smoke verifier & audio/ASR helpers."""
from __future__ import annotations

import gc
import hashlib
import importlib.util
import json
import logging
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.paths import AppPaths, find_ffmpeg_binary
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_duration

logger = logging.getLogger("videocreator.models_manager")

_SILENCE_START_RE = re.compile(r"silence_start:\s*([0-9]+(?:\.[0-9]+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*([0-9]+(?:\.[0-9]+)?)")
_SRT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def _parse_json_list(raw: Any) -> list[Any]:
    if isinstance(raw, list):
        return raw
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _find_missing_python_pkgs(pkgs: list[str]) -> list[str]:
    missing: list[str] = []
    for pkg in pkgs:
        clean = str(pkg).strip()
        if not clean:
            continue
        try:
            if importlib.util.find_spec(clean) is None:
                missing.append(clean)
        except Exception:
            missing.append(clean)
    return missing


def _check_installed_on_disk(local_path: str, files: list[dict[str, Any]]) -> bool:
    if not local_path:
        return False
    p = Path(local_path)
    if not p.exists():
        return False
    if p.is_dir() and files:
        return all((p / str(f.get("filename") or "")).is_file() for f in files if f.get("filename"))
    return True


def _model_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    local_path = str(row.get("local_path") or "")
    files_raw = _parse_json_list(row.get("files_json"))
    files: list[dict[str, Any]] = [f for f in files_raw if isinstance(f, dict)]
    req_pkgs = [str(x) for x in _parse_json_list(row.get("requires_python_pkgs")) if str(x).strip()]
    missing_pkgs = _find_missing_python_pkgs(req_pkgs)
    exists_on_disk = _check_installed_on_disk(local_path, files)
    return {
        "rowid": int(row["rowid"]) if row.get("rowid") is not None else 0,
        "model_id": str(row["model_id"]),
        "name": str(row["name"]),
        "category": str(row["category"]),
        "size_mb": int(row.get("size_mb") or 0),
        "status": str(row["status"]),
        "local_path": local_path,
        "installed_on_disk": exists_on_disk,
        "sha256": str(row.get("sha256") or ""),
        "download_url": str(row.get("download_url") or ""),
        "files": files,
        "license": str(row.get("license") or ""),
        "requires_python_pkgs": req_pkgs,
        "missing_python_pkgs": missing_pkgs,
        "smoke_tested": bool(int(row.get("smoke_tested") or 0)),
        "progress": float(row.get("progress") or 0.0),
        "error": row.get("error"),
        "updated_at": str(row.get("updated_at") or ""),
    }


def list_local_models(paths: AppPaths) -> list[dict[str, Any]]:
    rows = query_all(
        paths.db_file,
        "SELECT rowid, * FROM local_models ORDER BY category ASC, model_id ASC",
    )
    return [_model_row_to_dict(r) for r in rows]


def get_local_model(paths: AppPaths, model_id: str) -> dict[str, Any] | None:
    row = query_one(
        paths.db_file,
        "SELECT rowid, * FROM local_models WHERE model_id = ?",
        (model_id,),
    )
    return _model_row_to_dict(row) if row else None


def get_local_model_by_rowid(paths: AppPaths, rowid: int) -> dict[str, Any] | None:
    row = query_one(
        paths.db_file,
        "SELECT rowid, * FROM local_models WHERE rowid = ?",
        (int(rowid),),
    )
    return _model_row_to_dict(row) if row else None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _set_model_state(
    paths: AppPaths,
    model_id: str,
    *,
    status: str,
    progress: float | None = None,
    local_path: str | None = None,
    sha256: str | None = None,
    smoke_tested: bool | None = None,
    error: str | None = "",
) -> None:
    sets = ["status = ?", "updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: list[Any] = [status]
    if progress is not None:
        sets.append("progress = ?")
        params.append(float(progress))
    if local_path is not None:
        sets.append("local_path = ?")
        params.append(local_path)
    if sha256 is not None:
        sets.append("sha256 = ?")
        params.append(sha256)
    if smoke_tested is not None:
        sets.append("smoke_tested = ?")
        params.append(1 if smoke_tested else 0)
    if error != "":
        sets.append("error = ?")
        params.append(error)
    params.append(model_id)
    with get_conn(paths.db_file) as conn:
        conn.execute(f"UPDATE local_models SET {', '.join(sets)} WHERE model_id = ?", params)


def _looks_like_html_payload(first_chunk: bytes) -> bool:
    head = first_chunk.lstrip()[:64].lower()
    return head.startswith(b"<!doctype html") or head.startswith(b"<html")


def _download_file_verified(
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
        cur_hash = _sha256_file(dest_file).lower()
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
                    cur_hash = _sha256_file(part_file).lower()
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

            digest = _sha256_file(part_file).lower()
            if exp_hash and digest != exp_hash:
                part_file.unlink(missing_ok=True)
                raise ValueError(
                    f"SHA-256 mismatch for '{model_id}/{filename}': expected {exp_hash}, got {digest}"
                )
            part_file.replace(dest_file)
            return dest_file, digest
        except Exception as exc:
            last_err = exc
            logger.warning("Download attempt failed for %s/%s from %s: %s", model_id, filename, clean_url, exc)
            continue

    assert last_err is not None
    raise last_err


def verify_model_smoke_test(paths: AppPaths, model_id: str) -> dict[str, Any]:
    """Runs a real CPU inference smoke test on an installed local model before marking it `ready`."""
    info = get_local_model(paths, model_id)
    if info is None:
        raise ValueError(f"Unknown local model '{model_id}'")
    local_target = str(info.get("local_path") or "").strip()
    if not local_target or not Path(local_target).exists():
        _set_model_state(
            paths,
            model_id,
            status="failed",
            smoke_tested=False,
            error="Model files not found on disk",
        )
        raise FileNotFoundError(f"Model '{model_id}' is not present on disk: {local_target}")

    missing_pkgs = list(info.get("missing_python_pkgs") or [])
    if missing_pkgs:
        msg = f"Missing required Python packages: {', '.join(missing_pkgs)}"
        _set_model_state(
            paths,
            model_id,
            status="downloaded",
            progress=0.95,
            smoke_tested=False,
            error=msg,
        )
        raise RuntimeError(msg)

    target_path = Path(local_target)
    try:
        if model_id in ("faster_whisper_small", "faster_whisper_medium"):
            import numpy as np
            from faster_whisper import WhisperModel

            w_dir = target_path if target_path.is_dir() else target_path.parent
            w_model = WhisperModel(str(w_dir), device="cpu", compute_type="int8", cpu_threads=2)
            try:
                silent = np.zeros(16000, dtype=np.float32)
                segs, _ = w_model.transcribe(silent, language="en", vad_filter=False)
                list(segs)
            finally:
                del w_model
        elif model_id == "vieneu_tts_vi":
            from vieneu.v3nano import V3NanoVieNeuTTS

            v_dir = target_path if target_path.is_dir() else target_path.parent
            tts = V3NanoVieNeuTTS(onnx_dir=str(v_dir))
            try:
                wav = tts.infer("Xin chào", apply_watermark=False)
                if wav is None or len(wav) < 400:
                    raise RuntimeError("VieNeu-TTS smoke test returned empty audio")
            finally:
                tts.close()
        elif model_id == "nllb_200_distilled_600m_ct2":
            import ctranslate2
            import sentencepiece as spm

            nllb_dir = target_path if target_path.is_dir() else target_path.parent
            sp_model = nllb_dir / "sentencepiece.bpe.model"
            sp = spm.SentencePieceProcessor(str(sp_model))
            translator = ctranslate2.Translator(
                str(nllb_dir),
                device="cpu",
                compute_type="int8",
                inter_threads=1,
                intra_threads=2,
            )
            try:
                tokens = ["eng_Latn", *sp.encode("Hello", out_type=str), "</s>"]
                out = translator.translate_batch(
                    [tokens],
                    target_prefix=[["vie_Latn"]],
                    beam_size=1,
                    max_decoding_length=24,
                )
                if not out or not out[0].hypotheses:
                    raise RuntimeError("NLLB-200 smoke test returned no hypothesis")
            finally:
                del translator
        else:
            import numpy as np
            import onnxruntime as ort

            onnx_path = target_path
            if onnx_path.is_dir():
                found = sorted(onnx_path.glob("*.onnx"))
                if not found:
                    raise FileNotFoundError(f"No .onnx model file found in {onnx_path}")
                onnx_path = found[0]

            sess_opts = ort.SessionOptions()
            sess_opts.intra_op_num_threads = 2
            sess_opts.inter_op_num_threads = 1
            sess = ort.InferenceSession(
                str(onnx_path),
                sess_options=sess_opts,
                providers=["CPUExecutionProvider"],
            )
            try:
                feed: dict[str, Any] = {}
                for inp in sess.get_inputs():
                    concrete: list[int] = []
                    rank = len(inp.shape)
                    for axis_idx, dim in enumerate(inp.shape):
                        if isinstance(dim, int) and dim > 0:
                            concrete.append(dim)
                        elif axis_idx == 0:
                            concrete.append(1)
                        elif model_id == "speaker_embedding_onnx":
                            concrete.append(80 if axis_idx == rank - 1 else 64)
                        elif model_id == "paddle_lama_inpaint":
                            concrete.append(512)
                        elif model_id == "rembg_u2net":
                            concrete.append(320)
                        else:
                            concrete.append(64)
                    inp_type = str(inp.type or "")
                    if "float16" in inp_type:
                        dtype: Any = np.float16
                    elif "int64" in inp_type:
                        dtype = np.int64
                    elif "int32" in inp_type:
                        dtype = np.int32
                    else:
                        dtype = np.float32
                    feed[inp.name] = np.zeros(tuple(concrete), dtype=dtype)
                outputs = sess.run(None, feed)
                if not outputs or outputs[0] is None:
                    raise RuntimeError(f"ONNX smoke test produced no output for '{model_id}'")
            finally:
                del sess
        gc.collect()
    except Exception as exc:
        _set_model_state(
            paths,
            model_id,
            status="failed",
            smoke_tested=False,
            error=f"Smoke test failed: {exc}",
        )
        raise ValueError(f"Model smoke test failed for '{model_id}': {exc}") from exc

    _set_model_state(
        paths,
        model_id,
        status="ready",
        progress=1.0,
        smoke_tested=True,
        error=None,
    )
    with get_conn(paths.db_file) as conn:
        record_audit(
            conn,
            actor="models_manager",
            action="verify_model",
            object_type="local_model",
            detail=f"{model_id} verified ready",
        )
    updated = get_local_model(paths, model_id)
    assert updated is not None
    return updated


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
    _set_model_state(
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
                    hasher.update(_sha256_file(fpath).encode("ascii"))
                digest = hasher.hexdigest()
            else:
                target_name = (
                    str(files_spec[0]["filename"])
                    if len(files_spec) == 1 and files_spec[0].get("filename")
                    else src.name
                )
                dest = model_dir / target_name
                shutil.copy2(src, dest)
                digest = _sha256_file(dest)

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

                def _progress_cb(cur_written: int, cur_total: int, _base: int = base_done, _idx: int = idx) -> None:
                    denom = total_catalog_bytes if total_catalog_bytes > 0 else max(1, cur_total)
                    pct_raw = (_base + cur_written) / denom if denom > 0 else (_idx + 0.5) / len(files_spec)
                    pct = min(0.92, max(0.05, pct_raw * 0.92))
                    _set_model_state(paths, model_id, status="downloading", progress=round(pct, 3))

                dl_path, f_digest = _download_file_verified(
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

        _set_model_state(
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
            _set_model_state(paths, model_id, status="failed", smoke_tested=False, error=str(exc))
        raise


def remove_local_model(paths: AppPaths, model_id: str) -> dict[str, Any]:
    info = get_local_model(paths, model_id)
    if info is None:
        raise ValueError(f"Unknown local model '{model_id}'")

    model_dir = paths.models_dir / model_id
    if model_dir.exists():
        shutil.rmtree(model_dir, ignore_errors=True)
    _set_model_state(
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


def _probe_audio_channels(media_path: Path) -> int:
    cmd = [
        find_ffmpeg_binary("ffprobe"),
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=channels",
        "-of",
        "default=nw=1:nk=1",
        str(media_path),
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=15,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return 0
    try:
        return max(0, int(proc.stdout.strip().splitlines()[0]))
    except ValueError:
        return 0


def separate_vocals_and_bgm(
    paths: AppPaths,
    input_media: Path,
    out_dir: Path,
) -> tuple[Path, Path]:
    """Separates vocal dialogue and background music WAV stems cleanly via FFmpeg DSP (or ONNX UVR in R3)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    vocal_wav = out_dir / "vocal.wav"
    bgm_wav = out_dir / "bgm.wav"

    channels = _probe_audio_channels(input_media)
    if channels == 0:
        try:
            dur = max(0.5, probe_duration(input_media))
        except Exception:
            dur = 2.0
        for dest in (vocal_wav, bgm_wav):
            run_ffmpeg(
                [
                    "-f",
                    "lavfi",
                    "-i",
                    "anullsrc=channel_layout=mono:sample_rate=48000",
                    "-t",
                    f"{dur:.3f}",
                    "-c:a",
                    "pcm_s16le",
                    str(dest.resolve()),
                ]
            )
        return vocal_wav, bgm_wav

    vocal_af = (
        "pan=mono|c0=0.5*c0+0.5*c1,highpass=f=120,lowpass=f=7500"
        if channels >= 2
        else "highpass=f=120,lowpass=f=7500"
    )
    run_ffmpeg(
        [
            "-i",
            str(input_media.resolve()),
            "-vn",
            "-af",
            vocal_af,
            "-c:a",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "1",
            str(vocal_wav.resolve()),
        ],
        allow_creative_filters=True,
    )

    bgm_af = (
        "pan=stereo|c0=c0-0.85*c1|c1=c1-0.85*c0,lowpass=f=4500,volume=0.8"
        if channels >= 2
        else "lowpass=f=400,volume=0.35"
    )
    run_ffmpeg(
        [
            "-i",
            str(input_media.resolve()),
            "-vn",
            "-af",
            bgm_af,
            "-c:a",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(bgm_wav.resolve()),
        ],
        allow_creative_filters=True,
    )
    return vocal_wav, bgm_wav


def _parse_srt_segments(raw_srt: str) -> list[dict[str, Any]]:
    blocks = re.split(r"\r?\n\r?\n+", raw_srt.strip())
    segments: list[dict[str, Any]] = []
    for block in blocks:
        lines = [ln.strip() for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        m = _SRT_TIME_RE.search("\n".join(lines[:2]))
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(g) for g in m.groups())
        start_s = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000.0
        end_s = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000.0
        text_lines = [ln for ln in lines if not ln.isdigit() and "-->" not in ln]
        source_text = " ".join(text_lines).strip()
        if end_s > start_s + 0.1 and source_text:
            segments.append(
                {
                    "index": len(segments),
                    "start_s": round(start_s, 3),
                    "end_s": round(end_s, 3),
                    "source_text": source_text,
                }
            )
    return segments


def transcribe_media_segments(
    paths: AppPaths,
    input_media: Path,
    *,
    lang: str = "auto",
) -> list[dict[str, Any]]:
    """Extracts timed speech segments using faster-whisper (when installed), SRT sidecars, or FFmpeg silencedetect."""
    try:
        model_info = get_local_model(paths, "faster_whisper_small")
    except Exception:
        model_info = None
    if model_info and model_info["status"] == "ready" and model_info["installed_on_disk"]:
        try:
            from faster_whisper import WhisperModel

            w_path = Path(model_info["local_path"])
            w_dir = w_path if w_path.is_dir() else w_path.parent
            w_model = WhisperModel(str(w_dir), device="cpu", compute_type="int8")
            try:
                lang_arg = None if lang == "auto" else lang
                w_segs, _ = w_model.transcribe(str(input_media), language=lang_arg)
                results: list[dict[str, Any]] = []
                for seg in w_segs:
                    txt = str(getattr(seg, "text", "") or "").strip()
                    st = float(getattr(seg, "start", 0.0))
                    en = float(getattr(seg, "end", st + 0.5))
                    if txt and en > st:
                        results.append(
                            {
                                "index": len(results),
                                "start_s": round(st, 3),
                                "end_s": round(en, 3),
                                "source_text": txt,
                            }
                        )
                if results:
                    return results
            finally:
                del w_model
        except Exception as exc:
            logger.debug("faster-whisper fallback triggered for %s: %s", input_media.name, exc)

    for ext in (".srt", ".vtt"):
        sidecar = input_media.with_suffix(ext)
        if sidecar.exists():
            parsed = _parse_srt_segments(sidecar.read_text(encoding="utf-8", errors="replace"))
            if parsed:
                return parsed

    total_dur = max(0.8, probe_duration(input_media))
    channels = _probe_audio_channels(input_media)
    silences: list[tuple[float, float]] = []
    if channels > 0:
        try:
            stderr_out = run_ffmpeg(
                [
                    "-i",
                    str(input_media.resolve()),
                    "-vn",
                    "-af",
                    "silencedetect=noise=-35dB:d=0.35",
                    "-f",
                    "null",
                    "-",
                ],
                allow_creative_filters=True,
            )
            cur_start: float | None = None
            for line in stderr_out.splitlines():
                ms = _SILENCE_START_RE.search(line)
                if ms:
                    cur_start = float(ms.group(1))
                    continue
                me = _SILENCE_END_RE.search(line)
                if me and cur_start is not None:
                    silences.append((cur_start, float(me.group(1))))
                    cur_start = None
            if cur_start is not None:
                silences.append((cur_start, total_dur))
        except Exception:
            silences = []

    windows: list[tuple[float, float]] = []
    cursor = 0.0
    for s_start, s_end in silences:
        if s_start - cursor >= 0.45:
            windows.append((cursor, min(total_dur, s_start)))
        cursor = max(cursor, s_end)
    if total_dur - cursor >= 0.45:
        windows.append((cursor, total_dur))

    if not windows:
        chunk_s = 3.0 if total_dur > 4.0 else total_dur
        t = 0.0
        while t < total_dur - 0.2:
            nxt = min(total_dur, t + chunk_s)
            if nxt - t >= 0.4:
                windows.append((t, nxt))
            t = nxt

    return [
        {
            "index": idx,
            "start_s": round(st, 3),
            "end_s": round(en, 3),
            "source_text": f"Segment {idx + 1} ({round(st, 1)}s-{round(en, 1)}s)",
        }
        for idx, (st, en) in enumerate(windows)
    ]
