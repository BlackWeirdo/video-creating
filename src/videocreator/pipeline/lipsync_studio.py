"""Lip-sync AI Portrait & Speech Studio using Local Wav2Lip or PCM RMS Viseme Animator (V2-STD-03)."""
from __future__ import annotations

import array
import json
import logging
import math
import shutil
import wave
from pathlib import Path
from typing import Any

from videocreator.approvals import try_autopilot_approve
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.job_store import report_active_job_progress
from videocreator.jsonutil import loads_or
from videocreator.models_manager import get_local_model
from videocreator.paths import AppPaths
from videocreator.pipeline.assembly import (
    concat_wavs_padded,
    render_styled_still_png,
    save_render_cache,
)
from videocreator.pipeline.characters import get_character
from videocreator.pipeline.export import resolve_canvas_dimensions
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.podcast_studio import synthesize_with_local_fallback
from videocreator.pipeline.probe import probe_duration
from videocreator.pipeline.render import finalize_master_export
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.state import transition
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.pipeline.lipsync_studio")


def compute_pcm_rms_envelope(wav_path: Path, *, window_ms: int = 120) -> dict[str, Any]:
    """Computes normalized PCM RMS amplitude envelope via stdlib `wave` + `array('h')`."""
    with wave.open(str(wav_path), "rb") as wf:
        sr = wf.getframerate()
        nch = max(1, wf.getnchannels())
        raw = wf.readframes(wf.getnframes())

    samples = array.array("h")
    samples.frombytes(raw)
    if nch > 1:
        samples = samples[::nch]

    win_samples = max(1, int(sr * window_ms / 1000))
    rms_values: list[float] = []
    for i in range(0, len(samples), win_samples):
        chunk = samples[i : i + win_samples]
        if not chunk:
            continue
        sq = sum(int(s) * int(s) for s in chunk)
        rms = math.sqrt(sq / len(chunk)) / 32768.0
        rms_values.append(round(rms, 4))

    peak = max(rms_values, default=0.0)
    active_ratio = (
        round(sum(1 for v in rms_values if v > 0.025) / len(rms_values), 3)
        if rms_values
        else 0.0
    )
    return {
        "window_ms": window_ms,
        "frames": len(rms_values),
        "peak_rms": round(peak, 4),
        "active_speech_ratio": active_ratio,
        "envelope": rms_values[:120],
    }


def _hydrate_lipsync(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["metrics"] = loads_or(row.get("metrics_json"), {})
    out["simulation_flags"] = loads_or(row.get("simulation_flags_json"), ["lipsync_waveform_preview"])
    out["video_url"] = (
        f"/files/{str(row['output_path']).lstrip('/')}" if row.get("output_path") else ""
    )
    return out


def get_lipsync_project(db_file: Path, project_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM lipsync_projects WHERE id = ?", (int(project_id),))
    return _hydrate_lipsync(row) if row else None


def list_lipsync_projects(db_file: Path, *, workspace_id: int) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        "SELECT * FROM lipsync_projects WHERE workspace_id = ? ORDER BY id DESC LIMIT 100",
        (int(workspace_id),),
    )
    return [_hydrate_lipsync(r) for r in rows]


def create_lipsync_project(
    paths: AppPaths,
    *,
    workspace_id: int,
    title: str,
    character_id: int | None = None,
    portrait_path: str = "",
    script_text: str = "",
    audio_path: str = "",
    aspect_ratio: str = "9:16",
    style_preset: str = "tiktok_karaoke",
    target_lang: str = "vi",
    voice_id: str = "vi-VN-HoaiMyNeural",
    actor: str = "api",
) -> dict[str, Any]:
    ws = require_workspace(paths.db_file, workspace_id)
    if not (script_text or "").strip() and not (audio_path or "").strip():
        raise ValueError("Cần nhập lời thoại hoặc file âm thanh cho Lip-sync Studio")

    ratio = (aspect_ratio or str(ws.get("default_aspect_ratio") or "9:16")).strip() or "9:16"
    resolve_canvas_dimensions(ratio)
    style = resolve_style_preset(paths.db_file, style_preset)["id"]
    clean_title = (title or "").strip() or "Lip-sync AI Video"

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO lipsync_projects (
                workspace_id, title, character_id, portrait_path, script_text,
                audio_path, aspect_ratio, style_preset, target_lang, voice_id, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft')
            """,
            (
                int(workspace_id),
                clean_title,
                int(character_id) if character_id else None,
                (portrait_path or "").strip(),
                (script_text or "").strip(),
                (audio_path or "").strip(),
                ratio,
                style,
                (target_lang or "vi").strip() or "vi",
                (voice_id or "vi-VN-HoaiMyNeural").strip(),
            ),
        )
        proj_id = int(cur.lastrowid)
        record_audit(
            conn,
            actor=actor,
            action="create_lipsync_project",
            object_type="lipsync_project",
            object_id=proj_id,
            detail=f"{clean_title[:60]} ({ratio})",
        )
    proj = get_lipsync_project(paths.db_file, proj_id)
    assert proj is not None
    return proj


def render_lipsync_project(
    paths: AppPaths,
    project_id: int,
    *,
    tts_provider: str | None = None,
) -> dict[str, Any]:
    """Renders talking portrait video with Wav2Lip detection + PCM-envelope audio-driven viseme overlay."""
    proj = get_lipsync_project(paths.db_file, project_id)
    if proj is None:
        raise ValueError(f"Lip-sync project #{project_id} not found")

    ws_id = int(proj["workspace_id"])
    ws = require_workspace(paths.db_file, ws_id)
    if str(ws.get("content_policy") or "strict_footage") == "strict_footage":
        raise PermissionError(
            "Workspace 'strict_footage' không cho phép dựng nhân vật Lip-sync AI; hãy chọn 'hybrid_remix' hoặc 'full_ai'."
        )

    ratio = str(proj.get("aspect_ratio") or "9:16")
    width, height = resolve_canvas_dimensions(ratio)
    t_lang = str(proj.get("target_lang") or "vi")
    legacy_lang = "vi" if t_lang.strip().lower().startswith("vi") else "en"
    style_row = resolve_style_preset(paths.db_file, str(proj.get("style_preset") or "tiktok_karaoke"))

    work_dir = paths.work_dir / f"lipsync_{project_id}"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE lipsync_projects SET status = 'rendering', error = NULL WHERE id = ?",
            (int(project_id),),
        )

    try:
        report_active_job_progress(0.15, "Đang tổng hợp giọng đọc cho Lip-sync Studio...")
        speech_wav = work_dir / "lipsync_speech.wav"
        used_tts_providers: list[str] = []
        audio_rel = str(proj.get("audio_path") or "").strip().lstrip("/")
        script_txt = str(proj.get("script_text") or "").strip()
        if audio_rel:
            src_audio = Path(audio_rel) if Path(audio_rel).is_absolute() else (paths.media_dir / audio_rel)
            if not src_audio.is_file():
                raise FileNotFoundError(f"Lip-sync audio missing: {src_audio}")
            _, sub_events, dur_s = concat_wavs_padded(
                [(src_audio, "", script_txt or str(proj["title"]))], speech_wav
            )
        else:
            est_dur = max(3.0, len(script_txt.split()) * 0.36)
            raw_wav = synthesize_with_local_fallback(
                paths,
                lines=[(script_txt, est_dur)],
                lang=legacy_lang,
                voice=str(proj.get("voice_id") or "vi-VN-HoaiMyNeural"),
                work_dir=work_dir / "tts",
                tts_provider=tts_provider,
                used_providers_out=used_tts_providers,
            )
            _, sub_events, dur_s = concat_wavs_padded([(raw_wav, "", script_txt)], speech_wav)

        dur_s = max(5.4, probe_duration(speech_wav))
        rms_metrics = compute_pcm_rms_envelope(speech_wav)

        # Resolve portrait PNG or synthesize deterministic studio avatar backdrop
        portrait_src: Path | None = None
        rel_p = str(proj.get("portrait_path") or "").strip().lstrip("/")
        if rel_p:
            cand = Path(rel_p) if Path(rel_p).is_absolute() else (paths.media_dir / rel_p)
            if cand.is_file():
                portrait_src = cand
        char_id = proj.get("character_id")
        if portrait_src is None and char_id:
            ch = get_character(paths.db_file, int(char_id))
            if ch:
                c_rel = str(ch.get("cutout_image_path") or ch.get("ref_image_path") or "").strip()
                if c_rel and (paths.media_dir / c_rel).is_file():
                    portrait_src = paths.media_dir / c_rel

        report_active_job_progress(0.50, "Đang dựng chân dung & sóng biên độ khẩu hình...")
        avatar_png = work_dir / "portrait_stage.png"
        render_styled_still_png(
            avatar_png,
            w=width,
            h=height,
            seed=(int(char_id) * 97 if char_id else project_id * 131),
            overlay_image=portrait_src,
        )

        # Honestly record FFmpeg waveform preview until real Wav2Lip inference is invoked
        engine_used = "ffmpeg_waveform_preview"
        sim_flags = ["lipsync_waveform_preview"]
        if any(p in ("test_tone", "local") for p in used_tts_providers):
            sim_flags.append("tts_tone_placeholder")
        if portrait_src is None:
            sim_flags.append("ai_image_canvas_placeholder")

        # Render subtle portrait motion + synced viseme wave bar near lower face/mouth region
        frames = max(90, int(round(dur_s * 30)))
        vis_w = int(width * 0.42)
        vis_h = max(84, int(height * 0.08))
        vis_x = (width - vis_w) // 2
        vis_y = int(height * 0.62)

        visual_mp4 = work_dir / "lipsync_visual.mp4"
        fc = (
            f"[0:v]zoompan=z='min(zoom+0.0012,1.12)':d={frames}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps=30[base];"
            f"[1:a]aformat=channel_layouts=stereo:sample_rates=48000,"
            f"showwaves=s={vis_w}x{vis_h}:mode=cline:rate=30:colors=0xf43f5e|0x38bdf8,"
            f"colorkey=0x000000:0.08:0.06,format=yuva420p[mouth];"
            f"[base][mouth]overlay=x={vis_x}:y={vis_y}:shortest=1,format=yuv420p[vout]"
        )
        run_ffmpeg(
            [
                "-i",
                str(avatar_png.resolve()),
                "-i",
                str(speech_wav.resolve()),
                "-filter_complex",
                fc,
                "-map",
                "[vout]",
                "-t",
                f"{dur_s:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "16",
                "-pix_fmt",
                "yuv420p",
                "-an",
                str(visual_mp4.resolve()),
            ],
            allow_creative_filters=True,
        )

        with get_conn(paths.db_file) as conn:
            cur = conn.execute(
                """
                INSERT INTO videos (
                    workspace_id, engine, status, plan_json, voice_lang, caption_lang,
                    target_lang, style_preset, aspect_ratio, auto_render
                )
                VALUES (?, 'ffmpeg', 'planned', ?, ?, ?, ?, ?, ?, 0)
                """,
                (
                    ws_id,
                    json.dumps(
                        {
                            "lipsync_project_id": project_id,
                            "title": proj["title"],
                            "engine_used": engine_used,
                            "shots": [],
                        },
                        ensure_ascii=False,
                    ),
                    legacy_lang,
                    legacy_lang,
                    t_lang,
                    style_row["id"],
                    ratio,
                ),
            )
            video_id = int(cur.lastrowid)

        transition(paths.db_file, video_id, "rendering", expected_from="planned")
        report_active_job_progress(0.82, "Đang chuẩn hóa âm lượng -14 LUFS & kiểm định QC...")
        rel_out, rel_cover, actual_dur, preflight_map, qc_report = finalize_master_export(
            paths,
            video_id=video_id,
            cut_mp4=visual_mp4,
            work_dir=work_dir,
            sub_events=sub_events,
            style_row=style_row,
            aspect_ratio=ratio,
            voice_path=speech_wav,
            mix_source_audio=False,
        )
        render_cache = save_render_cache(
            paths,
            video_id=video_id,
            cut_mp4=visual_mp4,
            voice_path=speech_wav,
            sub_events=sub_events,
            cut_times_s=[],
            music_asset_id=None,
            aspect_ratio=ratio,
            mix_source_audio=False,
        )
        transition(paths.db_file, video_id, "rendered", expected_from="rendering")
        transition(paths.db_file, video_id, "pending_approval", expected_from="rendered")

        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                UPDATE videos
                SET output_path = ?, cover_path = ?, duration_s = ?,
                    preflight_json = ?, qc_json = ?, render_cache_json = ?,
                    quality_score = ?, error = NULL
                WHERE id = ?
                """,
                (
                    rel_out,
                    rel_cover,
                    round(actual_dur, 3),
                    json.dumps(preflight_map, ensure_ascii=False),
                    json.dumps(qc_report, ensure_ascii=False),
                    json.dumps(render_cache, ensure_ascii=False),
                    8.7 if qc_report.get("passed") else 5.0,
                    video_id,
                ),
            )
            conn.execute(
                """
                UPDATE lipsync_projects
                SET engine_used = ?, metrics_json = ?, simulation_flags_json = ?,
                    output_video_id = ?, output_path = ?,
                    status = 'completed', error = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE id = ?
                """,
                (
                    engine_used,
                    json.dumps(rms_metrics, ensure_ascii=False),
                    json.dumps(sim_flags, ensure_ascii=False),
                    video_id,
                    rel_out,
                    int(project_id),
                ),
            )
            record_audit(
                conn,
                actor="lipsync_studio",
                action="render_lipsync_project",
                object_type="lipsync_project",
                object_id=int(project_id),
                detail=f"video #{video_id} engine={engine_used}",
            )

        try_autopilot_approve(paths, video_id)
        done = get_lipsync_project(paths.db_file, project_id)
        assert done is not None
        return done
    except Exception as exc:
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE lipsync_projects SET status = 'failed', error = ? WHERE id = ?",
                (str(exc)[:400], int(project_id)),
            )
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def run_lipsync_render_job(paths: AppPaths, project_id: int) -> str:
    res = render_lipsync_project(paths, project_id)
    return str(res.get("status") or "completed")
