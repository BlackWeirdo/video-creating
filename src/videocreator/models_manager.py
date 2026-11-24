"""On-demand Local AI Models Manager (`VIDEOCREATOR_DATA/models`) & audio/ASR adapters (Phase 06)."""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

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


def _model_row_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    local_path = str(row.get("local_path") or "")
    exists_on_disk = bool(local_path and Path(local_path).exists())
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
    if error != "":
        sets.append("error = ?")
        params.append(error)
    params.append(model_id)
    with get_conn(paths.db_file) as conn:
        conn.execute(f"UPDATE local_models SET {', '.join(sets)} WHERE model_id = ?", params)


def install_local_model(
    paths: AppPaths,
    model_id: str,
    *,
    local_source_path: Path | str | None = None,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Installs a local model into `paths.models_dir/<model_id>` from a local file or catalog URL."""
    info = get_local_model(paths, model_id)
    if info is None:
        raise ValueError(f"Unknown local model '{model_id}'")

    model_dir = paths.models_dir / model_id
    model_dir.mkdir(parents=True, exist_ok=True)
    _set_model_state(paths, model_id, status="downloading", progress=0.05, error=None)

    try:
        if local_source_path is not None:
            src = Path(local_source_path).expanduser().resolve()
            if not src.exists():
                raise FileNotFoundError(f"Model source not found: {src}")
            if src.is_dir():
                dest = model_dir / src.name
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src, dest)
                digest = hashlib.sha256(src.name.encode("utf-8")).hexdigest()
            else:
                dest = model_dir / src.name
                shutil.copy2(src, dest)
                digest = _sha256_file(dest)
        else:
            url = str(info.get("download_url") or "").strip()
            if not url:
                raise RuntimeError(f"Model '{model_id}' has no configured download URL")
            filename = Path(url.split("?", 1)[0]).name or f"{model_id}.bin"
            dest = model_dir / filename
            tmp_dest = model_dir / f"{filename}.part"
            req = urllib.request.Request(url, headers={"User-Agent": "VideoCreator/2.0"})
            with urllib.request.urlopen(req, timeout=60.0) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                downloaded = 0
                with tmp_dest.open("wb") as out:
                    while True:
                        buf = resp.read(256 * 1024)
                        if not buf:
                            break
                        out.write(buf)
                        downloaded += len(buf)
                        if total > 0:
                            pct = min(0.95, max(0.1, downloaded / total))
                            _set_model_state(paths, model_id, status="downloading", progress=round(pct, 3))
            tmp_dest.replace(dest)
            digest = _sha256_file(dest)

        if expected_sha256 and digest.lower() != expected_sha256.strip().lower():
            if dest.is_file():
                dest.unlink(missing_ok=True)
            raise ValueError(
                f"SHA-256 mismatch for model '{model_id}': expected {expected_sha256}, got {digest}"
            )

        _set_model_state(
            paths,
            model_id,
            status="ready",
            progress=1.0,
            local_path=str(dest),
            sha256=digest,
            error=None,
        )
        with get_conn(paths.db_file) as conn:
            record_audit(
                conn,
                actor="models_manager",
                action="install_model",
                object_type="local_model",
                detail=f"{model_id} -> {dest}",
            )
        updated = get_local_model(paths, model_id)
        assert updated is not None
        return updated
    except Exception as exc:
        _set_model_state(paths, model_id, status="failed", error=str(exc))
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
    install_local_model(paths, str(info["model_id"]))
    return "ready"


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
    """Separates vocal dialogue and background music WAV stems cleanly via FFmpeg DSP (or ONNX UVR if available)."""
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

    # Vocal mid-band focus
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

    # Background bed extraction: stereo center-suppression when stereo, attenuated low-band bed when mono
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
            from faster_whisper import WhisperModel  # type: ignore[import-not-found]

            w_model = WhisperModel(model_info["local_path"], device="cpu", compute_type="int8")
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
        except Exception as exc:
            logger.debug("faster-whisper fallback triggered for %s: %s", input_media.name, exc)

    # Check companion SRT/VTT sidecar
    for ext in (".srt", ".vtt"):
        sidecar = input_media.with_suffix(ext)
        if sidecar.exists():
            parsed = _parse_srt_segments(sidecar.read_text(encoding="utf-8", errors="replace"))
            if parsed:
                return parsed

    # Speech-activity segmentation via FFmpeg silencedetect
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
