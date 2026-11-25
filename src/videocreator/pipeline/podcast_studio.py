"""Podcast Audio-Spectrum Studio CRUD and episode render orchestration (Stage R4)."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from videocreator.approvals import try_autopilot_approve
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.db_rows import hydrate_row
from videocreator.job_store import report_active_job_progress
from videocreator.paths import AppPaths
from videocreator.pipeline.assembly import (
    concat_podcast_turns_padded,
    save_render_cache,
)
from videocreator.pipeline.compute_job import run_studio_project_job
from videocreator.pipeline.export import resolve_canvas_dimensions
from videocreator.pipeline.podcast_visuals import (
    VALID_WAVEFORM_STYLES,
    clean_hex_color,
    render_podcast_visual_mp4,
)
from videocreator.pipeline.probe import probe_duration
from videocreator.pipeline.render import finalize_master_export
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.pipeline.subtitles import SubtitleEvent
from videocreator.state import transition
from videocreator.tts import synthesize_with_local_fallback
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.pipeline.podcast_studio")


def _hydrate_podcast(row: dict[str, Any]) -> dict[str, Any]:
    return hydrate_row(
        row,
        json_fields={
            "dialogue": ("dialogue_json", []),
            "simulation_flags": ("simulation_flags_json", []),
        },
        media_url_from=("video_url", "output_path", ""),
    )


def get_podcast_project(db_file: Path, project_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM podcast_projects WHERE id = ?", (int(project_id),))
    return _hydrate_podcast(row) if row else None


def list_podcast_projects(db_file: Path, *, workspace_id: int) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        "SELECT * FROM podcast_projects WHERE workspace_id = ? ORDER BY id DESC LIMIT 100",
        (int(workspace_id),),
    )
    return [_hydrate_podcast(r) for r in rows]


def create_podcast_project(
    paths: AppPaths,
    *,
    workspace_id: int,
    title: str,
    dialogue: list[dict[str, Any]] | None = None,
    script_text: str = "",
    host_a_name: str = "Host A",
    host_b_name: str = "Host B",
    host_a_voice: str = "vi-VN-HoaiMyNeural",
    host_b_voice: str = "vi-VN-NamMinhNeural",
    host_a_avatar_path: str = "",
    host_b_avatar_path: str = "",
    audio_source_path: str = "",
    aspect_ratio: str = "16:9",
    waveform_style: str = "cline",
    accent_color: str = "#38bdf8",
    style_preset: str = "minimal_bottom",
    target_lang: str = "vi",
    actor: str = "api",
) -> dict[str, Any]:
    require_workspace(paths.db_file, workspace_id)
    w_style = (waveform_style or "cline").strip().lower()
    if w_style not in VALID_WAVEFORM_STYLES:
        raise ValueError(f"Unsupported waveform_style '{waveform_style}'")

    clean_turns: list[dict[str, Any]] = []
    if dialogue:
        for idx, turn in enumerate(dialogue):
            txt = str(turn.get("text") or "").strip()
            if txt:
                spk = str(
                    turn.get("speaker") or (host_a_name if idx % 2 == 0 else host_b_name)
                ).strip()
                default_v = host_a_voice if spk == host_a_name or idx % 2 == 0 else host_b_voice
                clean_turns.append(
                    {
                        "speaker": spk,
                        "voice": str(turn.get("voice") or default_v).strip(),
                        "text": txt,
                    }
                )
    elif (script_text or "").strip():
        lines = [ln.strip() for ln in script_text.splitlines() if ln.strip()]
        for idx, ln in enumerate(lines):
            speaker = host_a_name if idx % 2 == 0 else host_b_name
            voice = host_a_voice if idx % 2 == 0 else host_b_voice
            clean_turns.append({"speaker": speaker, "voice": voice, "text": ln})

    if not clean_turns and not (audio_source_path or "").strip():
        raise ValueError("Cần nhập nội dung hội thoại Podcast hoặc chọn file âm thanh nguồn")

    ratio = (aspect_ratio or "16:9").strip() or "16:9"
    resolve_canvas_dimensions(ratio)
    style = resolve_style_preset(paths.db_file, style_preset)["id"]
    clean_title = (title or "").strip() or "Podcast Studio Episode"
    clean_accent = clean_hex_color(accent_color)

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO podcast_projects (
                workspace_id, title, host_a_name, host_b_name, host_a_voice, host_b_voice,
                host_a_avatar_path, host_b_avatar_path,
                dialogue_json, audio_source_path, aspect_ratio, waveform_style,
                accent_color, style_preset, target_lang, status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft')
            """,
            (
                int(workspace_id),
                clean_title,
                host_a_name.strip() or "Host A",
                host_b_name.strip() or "Host B",
                host_a_voice.strip() or "vi-VN-HoaiMyNeural",
                host_b_voice.strip() or "vi-VN-NamMinhNeural",
                (host_a_avatar_path or "").strip(),
                (host_b_avatar_path or "").strip(),
                json.dumps(clean_turns, ensure_ascii=False),
                (audio_source_path or "").strip(),
                ratio,
                w_style,
                clean_accent,
                style,
                (target_lang or "vi").strip() or "vi",
            ),
        )
        proj_id = int(cur.lastrowid)
        record_audit(
            conn,
            actor=actor,
            action="create_podcast_project",
            object_type="podcast_project",
            object_id=proj_id,
            detail=f"{clean_title[:60]} ({ratio}, {w_style})",
        )
    proj = get_podcast_project(paths.db_file, proj_id)
    assert proj is not None
    return proj


def _build_podcast_speech_track(
    paths: AppPaths,
    proj: dict[str, Any],
    work_dir: Path,
    *,
    legacy_lang: str,
    tts_provider: str | None,
) -> tuple[Path, list[SubtitleEvent], list[tuple[float, float, str]], list[str]]:
    speech_wav = work_dir / "podcast_speech.wav"
    used_tts_providers: list[str] = []
    host_a_name = str(proj.get("host_a_name") or "Host A").strip()
    host_b_name = str(proj.get("host_b_name") or "Host B").strip()

    audio_rel = str(proj.get("audio_source_path") or "").strip().lstrip("/")
    if audio_rel:
        src_audio = (
            Path(audio_rel) if Path(audio_rel).is_absolute() else (paths.media_dir / audio_rel)
        )
        if not src_audio.is_file():
            raise FileNotFoundError(f"Podcast audio missing: {src_audio}")
        _, sub_events, turn_windows, _ = concat_podcast_turns_padded(
            [(src_audio, host_a_name, str(proj["title"]), "A")],
            speech_wav,
        )
        return speech_wav, sub_events, turn_windows, used_tts_providers

    turns = list(proj.get("dialogue") or [])
    total_turns = max(1, len(turns))
    turn_wavs: list[tuple[Path, str, str, str]] = []
    for idx, turn in enumerate(turns):
        txt = str(turn.get("text") or "").strip()
        if not txt:
            continue
        speaker = str(
            turn.get("speaker") or (host_a_name if idx % 2 == 0 else host_b_name)
        ).strip()
        report_active_job_progress(
            0.10 + 0.45 * (idx / total_turns),
            f"Đang tổng hợp giọng lượt {idx + 1}/{total_turns} ({speaker})...",
        )
        if (
            speaker.lower() == host_b_name.lower()
            and host_b_name.lower() != host_a_name.lower()
        ):
            slot = "B"
        elif (
            speaker.lower() == host_a_name.lower()
            and host_b_name.lower() != host_a_name.lower()
        ):
            slot = "A"
        else:
            slot = "A" if idx % 2 == 0 else "B"
        default_v = str(proj["host_a_voice"] if slot == "A" else proj["host_b_voice"])
        voice = str(turn.get("voice") or default_v).strip()
        est_dur = max(2.2, len(txt.split()) * 0.35)
        wav_p = synthesize_with_local_fallback(
            paths,
            lines=[(txt, est_dur)],
            lang=legacy_lang,
            voice=voice,
            work_dir=work_dir / f"turn_{idx:02d}",
            tts_provider=tts_provider,
            used_providers_out=used_tts_providers,
        )
        turn_wavs.append((wav_p, speaker, txt, slot))

    if not turn_wavs:
        raise ValueError("Không có lượt hội thoại hợp lệ để dựng Podcast")
    _, sub_events, turn_windows, _ = concat_podcast_turns_padded(turn_wavs, speech_wav)
    return speech_wav, sub_events, turn_windows, used_tts_providers


def render_podcast_project(
    paths: AppPaths,
    project_id: int,
    *,
    tts_provider: str | None = None,
) -> dict[str, Any]:
    """Renders a Podcast episode with real multi-host TTS, turn-synced illuminating avatars, spectrum, `-14 LUFS` & QC."""
    proj = get_podcast_project(paths.db_file, project_id)
    if proj is None:
        raise ValueError(f"Podcast project #{project_id} not found")

    ws_id = int(proj["workspace_id"])
    ratio = str(proj.get("aspect_ratio") or "16:9")
    width, height = resolve_canvas_dimensions(ratio)
    w_style = str(proj.get("waveform_style") or "cline")
    hex_col = clean_hex_color(str(proj.get("accent_color") or "#38bdf8"))
    t_lang = str(proj.get("target_lang") or "vi")
    legacy_lang = "vi" if t_lang.strip().lower().startswith("vi") else "en"
    style_row = resolve_style_preset(
        paths.db_file, str(proj.get("style_preset") or "minimal_bottom")
    )

    work_dir = paths.work_dir / f"podcast_{project_id}"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE podcast_projects SET status = 'rendering', error = NULL WHERE id = ?",
            (int(project_id),),
        )

    try:
        speech_wav, sub_events, turn_windows, used_tts_providers = _build_podcast_speech_track(
            paths,
            proj,
            work_dir,
            legacy_lang=legacy_lang,
            tts_provider=tts_provider,
        )
        sim_flags = (
            ["tts_tone_placeholder"]
            if any(p in ("test_tone", "local") for p in used_tts_providers)
            else []
        )

        dur_s = max(5.4, probe_duration(speech_wav))
        av_a_rel = str(proj.get("host_a_avatar_path") or "").strip().lstrip("/")
        av_b_rel = str(proj.get("host_b_avatar_path") or "").strip().lstrip("/")

        report_active_job_progress(
            0.62, "Đang dựng phổ sóng nhạc & avatar phát sáng theo lượt nói..."
        )
        visual_mp4, avatar_layout = render_podcast_visual_mp4(
            work_dir=work_dir,
            speech_wav=speech_wav,
            dur_s=dur_s,
            width=width,
            height=height,
            waveform_style=w_style,
            hex_col=hex_col,
            host_a_name=str(proj.get("host_a_name") or "Host A").strip(),
            host_b_name=str(proj.get("host_b_name") or "Host B").strip(),
            av_a_file=(paths.media_dir / av_a_rel) if av_a_rel else None,
            av_b_file=(paths.media_dir / av_b_rel) if av_b_rel else None,
            turn_windows=turn_windows,
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
                            "podcast_project_id": project_id,
                            "title": proj["title"],
                            "waveform_style": w_style,
                            "avatar_layout": avatar_layout,
                            "turn_windows": [
                                {"start_s": s, "end_s": e, "slot": sl}
                                for s, e, sl in turn_windows
                            ],
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
        report_active_job_progress(0.84, "Đang chuẩn hóa âm lượng -14 LUFS & kiểm định QC...")
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
                UPDATE podcast_projects
                SET output_video_id = ?, output_path = ?, simulation_flags_json = ?,
                    status = 'completed', error = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE id = ?
                """,
                (video_id, rel_out, json.dumps(sim_flags, ensure_ascii=False), int(project_id)),
            )
            record_audit(
                conn,
                actor="podcast_studio",
                action="render_podcast_project",
                object_type="podcast_project",
                object_id=int(project_id),
                detail=f"video #{video_id} ({ratio}, {w_style})",
            )

        try_autopilot_approve(paths, video_id)
        done = get_podcast_project(paths.db_file, project_id)
        assert done is not None
        return done
    except Exception as exc:
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE podcast_projects SET status = 'failed', error = ? WHERE id = ?",
                (str(exc)[:400], int(project_id)),
            )
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def run_podcast_render_job(paths: AppPaths, project_id: int) -> str:
    return run_studio_project_job(render_podcast_project, paths, project_id)


__all__ = [
    "VALID_WAVEFORM_STYLES",
    "create_podcast_project",
    "get_podcast_project",
    "list_podcast_projects",
    "render_podcast_project",
    "run_podcast_render_job",
    "synthesize_with_local_fallback",
]
