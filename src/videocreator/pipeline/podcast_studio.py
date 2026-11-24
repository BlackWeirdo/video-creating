"""Podcast Audio-Spectrum Studio (16:9 / 9:16 / 1:1) with Real Multi-Host TTS, Channel Voices & Turn-Synced Host Avatars (Stage R4)."""
from __future__ import annotations

import json
import logging
import re
import shutil
import wave
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from videocreator.approvals import try_autopilot_approve
from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.channel_voices import resolve_voice_id_to_tts_spec
from videocreator.pipeline.export import resolve_canvas_dimensions
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_duration
from videocreator.pipeline.render import _save_render_cache, finalize_master_export
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.pipeline.subtitles import SubtitleEvent
from videocreator.state import transition
from videocreator.tts import TTSUnavailableError, synthesize_speech_segments
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.pipeline.podcast_studio")

VALID_WAVEFORM_STYLES: frozenset[str] = frozenset({"bars", "line", "p2p", "cline", "spectrum"})
_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


def _clean_hex_color(color: str, fallback: str = "#38bdf8") -> str:
    raw = (color or "").strip()
    return raw if _HEX_COLOR_RE.match(raw) else fallback


def _hex_to_rgb(hex_col: str) -> tuple[int, int, int]:
    h = _clean_hex_color(hex_col).lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def synthesize_with_local_fallback(
    paths: AppPaths,
    *,
    lines: list[tuple[str, float]],
    lang: str,
    voice: str,
    work_dir: Path,
    tts_provider: str | None = None,
    used_providers_out: list[str] | None = None,
) -> Path:
    """Synthesizes mono 48kHz PCM WAV via Edge TTS, VieNeu CPU, or consented Channel Voice with honest test_tone fallback."""
    cfg = load_settings(paths.config_file)
    explicit = (tts_provider or "").strip().lower()
    base_prov = explicit or (cfg.voice.en_provider if lang == "en" else cfg.voice.vi_provider)

    work_dir.mkdir(parents=True, exist_ok=True)
    prov, resolved_voice, ref_audio = resolve_voice_id_to_tts_spec(
        paths,
        voice,
        lang=lang,
        default_provider=base_prov,
    )

    if prov in ("edge", "vieneu"):
        try:
            track, _ = synthesize_speech_segments(
                lines,
                lang=lang,
                voice=resolved_voice,
                provider_name=prov,
                work_dir=work_dir,
                max_atempo=1.15,
                ref_audio=ref_audio,
                paths=paths,
            )
            if used_providers_out is not None:
                used_providers_out.append(track.provider)
            return track.audio_path
        except TTSUnavailableError as exc:
            logger.warning("Podcast TTS (%s/%s) unavailable; falling back to test_tone: %s", prov, resolved_voice, exc)

    tone_prov = explicit if explicit in ("test_tone", "local") else "test_tone"
    track, _ = synthesize_speech_segments(
        lines,
        lang=lang,
        voice=resolved_voice,
        provider_name=tone_prov,
        work_dir=work_dir,
        max_atempo=1.15,
    )
    if used_providers_out is not None:
        used_providers_out.append(tone_prov)
    return track.audio_path


def _concat_podcast_turns_padded(
    turn_tracks: list[tuple[Path, str, str, str]],
    dest_wav: Path,
    *,
    min_total_s: float = 5.4,
) -> tuple[Path, list[SubtitleEvent], list[tuple[float, float, str]], float]:
    """Concatenates mono 48kHz PCM turn WAVs with sample-accurate subtitle & host-turn timings."""
    dest_wav.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 48000
    events: list[SubtitleEvent] = []
    turn_windows: list[tuple[float, float, str]] = []
    cursor_frames = 0
    gap_frames = int(0.18 * sample_rate)

    with wave.open(str(dest_wav), "wb") as out_wf:
        out_wf.setnchannels(1)
        out_wf.setsampwidth(2)
        out_wf.setframerate(sample_rate)

        for idx, (wav_path, speaker, text, host_slot) in enumerate(turn_tracks):
            norm_wav = wav_path.with_name(f"{wav_path.stem}_48k.wav")
            run_ffmpeg(
                [
                    "-i",
                    str(wav_path.resolve()),
                    "-ar",
                    str(sample_rate),
                    "-ac",
                    "1",
                    "-c:a",
                    "pcm_s16le",
                    str(norm_wav.resolve()),
                ]
            )
            with wave.open(str(norm_wav), "rb") as in_wf:
                frames = in_wf.readframes(in_wf.getnframes())
                n_frames = len(frames) // 2
                out_wf.writeframes(frames)

            start_s = cursor_frames / sample_rate
            cursor_frames += n_frames
            end_s = cursor_frames / sample_rate
            if end_s > start_s:
                turn_windows.append((round(start_s, 3), round(end_s, 3), host_slot))
            label = f"{speaker}: {text}" if speaker else text
            if label.strip() and end_s > start_s:
                events.append(
                    SubtitleEvent(
                        start_s=round(start_s, 3),
                        end_s=round(end_s, 3),
                        text=label.strip(),
                    )
                )
            if idx < len(turn_tracks) - 1:
                out_wf.writeframes(b"\x00\x00" * gap_frames)
                cursor_frames += gap_frames

        total_frames = cursor_frames
        min_frames = int(round(min_total_s * sample_rate))
        if total_frames < min_frames:
            pad_frames = min_frames - total_frames
            out_wf.writeframes(b"\x00\x00" * pad_frames)
            total_frames = min_frames

    return dest_wav, events, turn_windows, round(total_frames / sample_rate, 3)


def _concat_wavs_padded(
    turn_tracks: list[tuple[Path, str, str]],
    dest_wav: Path,
    *,
    min_total_s: float = 5.4,
) -> tuple[Path, list[SubtitleEvent], float]:
    out_wav, events, _tw, dur = _concat_podcast_turns_padded(
        [(w, spk, txt, "A") for w, spk, txt in turn_tracks],
        dest_wav,
        min_total_s=min_total_s,
    )
    return out_wav, events, dur


def _render_host_avatar_pair(
    out_dir: Path,
    *,
    slot: str,
    host_name: str,
    avatar_path: Path | None,
    size: int,
    accent_rgb: tuple[int, int, int],
) -> tuple[Path, Path]:
    """Renders `(dim_png, active_png)` avatar cards so the speaking host visibly illuminates."""
    dim_png = out_dir / f"host_{slot}_dim.png"
    act_png = out_dir / f"host_{slot}_active.png"

    portrait: Image.Image | None = None
    if avatar_path is not None and avatar_path.is_file():
        try:
            portrait = Image.open(avatar_path).convert("RGB").resize((size - 20, size - 20))
        except Exception:
            portrait = None

    for is_active, dst in ((False, dim_png), (True, act_png)):
        bg_col = (
            (min(255, accent_rgb[0] // 2 + 35), min(255, accent_rgb[1] // 2 + 45), min(255, accent_rgb[2] // 2 + 65))
            if is_active
            else (18, 25, 40)
        )
        border_col = accent_rgb if is_active else (52, 65, 85)
        border_w = 6 if is_active else 2

        card = Image.new("RGB", (size, size), bg_col)
        draw = ImageDraw.Draw(card)

        if portrait is not None:
            factor = 1.12 if is_active else 0.42
            lit = portrait.point(lambda px: max(0, min(255, int(px * factor))))
            card.paste(lit, (10, 10))
        else:
            # Draw clean geometric presenter silhouette when no custom avatar photo was uploaded
            sil_col = (240, 248, 255) if is_active else (75, 90, 112)
            cx, cy = size // 2, int(size * 0.38)
            r_head = max(12, int(size * 0.17))
            draw.ellipse((cx - r_head, cy - r_head, cx + r_head, cy + r_head), fill=sil_col)
            r_body_x = max(20, int(size * 0.30))
            r_body_y = max(16, int(size * 0.24))
            by_top = cy + r_head + 6
            draw.pieslice(
                (cx - r_body_x, by_top, cx + r_body_x, by_top + r_body_y * 2),
                start=180,
                end=360,
                fill=sil_col,
            )

        if is_active:
            # Bright glowing outer frame + speaking indicator dot
            draw.rectangle((2, 2, size - 3, size - 3), outline=border_col, width=border_w)
            draw.rectangle((8, 8, size - 9, size - 9), outline=(255, 255, 255), width=2)
            dot_r = max(5, size // 18)
            draw.ellipse((size - dot_r * 3 - 6, 8, size - 8, 8 + dot_r * 2), fill=(52, 211, 153))
        else:
            draw.rectangle((1, 1, size - 2, size - 2), outline=border_col, width=border_w)

        _ = host_name  # label is displayed in subtitles & UI
        card.save(dst, format="PNG")

    return dim_png, act_png


def _hydrate_podcast(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["dialogue"] = loads_or(row.get("dialogue_json"), [])
    out["simulation_flags"] = loads_or(row.get("simulation_flags_json"), [])
    out["video_url"] = (
        f"/files/{str(row['output_path']).lstrip('/')}" if row.get("output_path") else ""
    )
    return out


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
                spk = str(turn.get("speaker") or (host_a_name if idx % 2 == 0 else host_b_name)).strip()
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
    clean_accent = _clean_hex_color(accent_color)

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


def _build_spectrum_filter(waveform_style: str, width: int, height: int, hex_color: str) -> str:
    col_hex = "0x" + hex_color.lstrip("#")
    if waveform_style in ("bars", "spectrum"):
        ascale = "sqrt" if waveform_style == "spectrum" else "log"
        return (
            f"aformat=channel_layouts=stereo:sample_rates=48000,"
            f"showfreqs=s={width}x{height}:mode=bar:ascale={ascale}:fscale=log:win_size=1024:rate=30:colors={col_hex}|0xa855f7,"
            f"colorkey=0x000000:0.08:0.06,format=yuva420p"
        )
    return (
        f"aformat=channel_layouts=stereo:sample_rates=48000,"
        f"showwaves=s={width}x{height}:mode={waveform_style}:rate=30:colors={col_hex}|0xa855f7,"
        f"colorkey=0x000000:0.08:0.06,format=yuva420p"
    )


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
    hex_col = _clean_hex_color(str(proj.get("accent_color") or "#38bdf8"))
    t_lang = str(proj.get("target_lang") or "vi")
    legacy_lang = "vi" if t_lang.strip().lower().startswith("vi") else "en"
    style_row = resolve_style_preset(paths.db_file, str(proj.get("style_preset") or "minimal_bottom"))

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
        speech_wav = work_dir / "podcast_speech.wav"
        sub_events: list[SubtitleEvent] = []
        turn_windows: list[tuple[float, float, str]] = []
        used_tts_providers: list[str] = []
        host_a_name = str(proj.get("host_a_name") or "Host A").strip()
        host_b_name = str(proj.get("host_b_name") or "Host B").strip()

        audio_rel = str(proj.get("audio_source_path") or "").strip().lstrip("/")
        if audio_rel:
            src_audio = Path(audio_rel) if Path(audio_rel).is_absolute() else (paths.media_dir / audio_rel)
            if not src_audio.is_file():
                raise FileNotFoundError(f"Podcast audio missing: {src_audio}")
            _, sub_events, turn_windows, dur_s = _concat_podcast_turns_padded(
                [(src_audio, host_a_name, str(proj["title"]), "A")],
                speech_wav,
            )
        else:
            turns = list(proj.get("dialogue") or [])
            turn_wavs: list[tuple[Path, str, str, str]] = []
            for idx, turn in enumerate(turns):
                txt = str(turn.get("text") or "").strip()
                if not txt:
                    continue
                speaker = str(turn.get("speaker") or (host_a_name if idx % 2 == 0 else host_b_name)).strip()
                if speaker.lower() == host_b_name.lower() and host_b_name.lower() != host_a_name.lower():
                    slot = "B"
                elif speaker.lower() == host_a_name.lower() and host_b_name.lower() != host_a_name.lower():
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
            _, sub_events, turn_windows, dur_s = _concat_podcast_turns_padded(turn_wavs, speech_wav)

        sim_flags: list[str] = []
        if any(p in ("test_tone", "local") for p in used_tts_providers):
            sim_flags.append("tts_tone_placeholder")

        dur_s = max(5.4, probe_duration(speech_wav))
        wave_w = int(width * 0.80)
        wave_h = max(180, int(height * 0.24))
        wave_x = (width - wave_w) // 2
        wave_y = int(height * 0.46)
        panel_pad = 20

        av_size = max(96, min(int(width * 0.20), int(height * 0.22), 180))
        av_y = max(28, wave_y - panel_pad - av_size - 24)
        av_ax = wave_x + int(wave_w * 0.12)
        av_bx = max(av_ax + av_size + 24, wave_x + wave_w - int(wave_w * 0.12) - av_size)

        av_a_rel = str(proj.get("host_a_avatar_path") or "").strip().lstrip("/")
        av_b_rel = str(proj.get("host_b_avatar_path") or "").strip().lstrip("/")
        av_a_file = (paths.media_dir / av_a_rel) if av_a_rel else None
        av_b_file = (paths.media_dir / av_b_rel) if av_b_rel else None

        dim_a, act_a = _render_host_avatar_pair(
            work_dir,
            slot="a",
            host_name=host_a_name,
            avatar_path=av_a_file,
            size=av_size,
            accent_rgb=_hex_to_rgb(hex_col),
        )
        dim_b, act_b = _render_host_avatar_pair(
            work_dir,
            slot="b",
            host_name=host_b_name,
            avatar_path=av_b_file,
            size=av_size,
            accent_rgb=(192, 132, 252),
        )

        enable_a_terms = [f"between(t,{st:.3f},{en:.3f})" for st, en, sl in turn_windows if sl == "A"]
        enable_b_terms = [f"between(t,{st:.3f},{en:.3f})" for st, en, sl in turn_windows if sl == "B"]
        enable_a = "+".join(enable_a_terms) if enable_a_terms else "0"
        enable_b = "+".join(enable_b_terms) if enable_b_terms else "0"

        spec_filter = _build_spectrum_filter(w_style, wave_w, wave_h, hex_col)
        col_ff = "0x" + hex_col.lstrip("#")
        bar_y = wave_y + wave_h + 24

        visual_mp4 = work_dir / "podcast_visual.mp4"
        fc = (
            f"[0:v]drawbox=x={wave_x - panel_pad}:y={wave_y - panel_pad}:"
            f"w={wave_w + panel_pad * 2}:h={wave_h + panel_pad * 2}:color=0x1e293b@0.85:t=fill,"
            f"drawbox=x={wave_x - panel_pad}:y={wave_y - panel_pad}:"
            f"w={wave_w + panel_pad * 2}:h={wave_h + panel_pad * 2}:color={col_ff}@0.55:t=3,"
            f"drawbox=x={wave_x}:y={bar_y}:w={wave_w}:h=6:color=0x334155@0.9:t=fill[bg0];"
            f"[bg0][3:v]overlay=x={av_ax}:y={av_y}[bg1];"
            f"[bg1][4:v]overlay=x={av_bx}:y={av_y}[bg2];"
            f"[bg2][5:v]overlay=x={av_ax}:y={av_y}:enable='{enable_a}'[bg3];"
            f"[bg3][6:v]overlay=x={av_bx}:y={av_y}:enable='{enable_b}'[bg4];"
            f"[1:a]{spec_filter}[wave];"
            f"[bg4][wave]overlay=x={wave_x}:y={wave_y}:shortest=1[stage];"
            f"[stage][2:v]overlay=x='{wave_x}+({wave_w}-44)*min(1,t/{dur_s:.3f})':y={bar_y - 2}:shortest=1,"
            f"format=yuv420p[vout]"
        )
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                f"color=c=0x0b1120:s={width}x{height}:r=30:d={dur_s:.3f}",
                "-i",
                str(speech_wav.resolve()),
                "-f",
                "lavfi",
                "-i",
                f"color=c={col_ff}:s=44x10:r=30:d={dur_s:.3f}",
                "-i",
                str(dim_a.resolve()),
                "-i",
                str(dim_b.resolve()),
                "-i",
                str(act_a.resolve()),
                "-i",
                str(act_b.resolve()),
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
                            "podcast_project_id": project_id,
                            "title": proj["title"],
                            "waveform_style": w_style,
                            "avatar_layout": {
                                "size": av_size,
                                "y": av_y,
                                "host_a_x": av_ax,
                                "host_b_x": av_bx,
                            },
                            "turn_windows": [
                                {"start_s": s, "end_s": e, "slot": sl} for s, e, sl in turn_windows
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
        render_cache = _save_render_cache(
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
    res = render_podcast_project(paths, project_id)
    return str(res.get("status") or "completed")
