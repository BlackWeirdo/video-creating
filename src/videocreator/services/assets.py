"""Audio asset probing and workspace import service (music & SFX)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Literal

from videocreator.db import get_conn, record_audit
from videocreator.paths import AppPaths, find_ffmpeg_binary
from videocreator.workspaces import DEFAULT_WORKSPACE_ID, require_workspace

ALLOWED_AUDIO_EXTENSIONS: set[str] = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}
MAX_AUDIO_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


def probe_audio_duration(file_path: Path) -> float:
    """Probes an audio file using `ffprobe` and returns its duration in seconds."""
    ffprobe_bin = find_ffmpeg_binary("ffprobe")
    proc = subprocess.run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=codec_type",
            "-of",
            "json",
            str(file_path),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )
    if proc.returncode != 0:
        raise ValueError(f"ffprobe failed on audio file {file_path.name}: {proc.stderr[:200]}")
    data = json.loads(proc.stdout or "{}")
    streams = data.get("streams") or []
    if not any(s.get("codec_type") == "audio" for s in streams):
        raise ValueError(f"File '{file_path.name}' contains no valid audio stream")
    dur = float((data.get("format") or {}).get("duration") or 0.0)
    if dur <= 0.1:
        raise ValueError(f"Audio duration invalid ({dur}s)")
    return round(dur, 3)


def import_audio_asset(
    paths: AppPaths,
    source_file: Path,
    *,
    kind: Literal["music", "sfx"] = "music",
    title: str = "",
    workspace_id: int = DEFAULT_WORKSPACE_ID,
) -> int:
    ext = source_file.suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise ValueError(f"Unsupported audio extension '{ext}'")
    ws = require_workspace(paths.db_file, int(workspace_id))

    duration_s = probe_audio_duration(source_file)
    clean_title = title.strip() or source_file.stem
    meta: dict[str, Any] = {"title": clean_title, "original_name": source_file.name}
    if kind == "music":
        try:
            from videocreator.pipeline.audio_beats import analyse_music_beats

            meta.update(analyse_music_beats(source_file, title_hint=clean_title))
        except Exception:
            pass

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO assets (kind, path, duration_s, meta_json, workspace_id)
            VALUES (?, 'pending', ?, ?, ?)
            """,
            (kind, duration_s, json.dumps(meta, ensure_ascii=False), int(ws["id"])),
        )
        asset_id = int(cur.lastrowid or 0)
        rel_path = f"assets/{kind}_{asset_id}{ext}"
        dest = paths.media_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, dest)
        conn.execute("UPDATE assets SET path = ? WHERE id = ?", (rel_path, asset_id))
        record_audit(
            conn,
            actor="ui",
            action="asset.imported",
            object_type="asset",
            object_id=asset_id,
            detail=f"{kind}: {meta['title']} ({duration_s}s)",
        )
    return asset_id
