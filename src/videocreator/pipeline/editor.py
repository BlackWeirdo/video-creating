"""Multi-track Timeline Editor composer rendering via FFmpeg (V2-EDT-04..05)."""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.job_store import report_active_job_progress
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.pipeline.assembly import load_shot_source, save_render_cache
from videocreator.pipeline.export import resolve_canvas_dimensions
from videocreator.pipeline.ffmpeg import RenderError, run_ffmpeg
from videocreator.pipeline.probe import probe_duration, probe_video
from videocreator.pipeline.render import finalize_master_export
from videocreator.pipeline.render_steps import concat_segments
from videocreator.pipeline.styles import resolve_style_preset
from videocreator.pipeline.subtitles import SubtitleEvent
from videocreator.state import transition
from videocreator.workspaces import require_workspace

logger = logging.getLogger("videocreator.pipeline.editor")


def list_editor_media(db_file: Path, *, workspace_id: int) -> dict[str, Any]:
    """Lists workspace media items (videos, footage, shots, assets, ai_images) for timeline import."""
    videos = query_all(
        db_file,
        "SELECT id, status, output_path, cover_path, duration_s, aspect_ratio FROM videos WHERE workspace_id = ? AND output_path IS NOT NULL ORDER BY id DESC LIMIT 40",
        (int(workspace_id),),
    )
    shots = query_all(
        db_file,
        """
        SELECT s.id, s.start_s, s.end_s, s.description, s.has_product,
               COALESCE(f.path, a.path) AS media_path
        FROM shots s
        LEFT JOIN footage f ON s.footage_id = f.id
        LEFT JOIN assets a ON s.asset_id = a.id
        WHERE COALESCE(f.workspace_id, a.workspace_id, 1) = ?
        ORDER BY s.id DESC LIMIT 60
        """,
        (int(workspace_id),),
    )
    assets = query_all(
        db_file,
        "SELECT id, kind, path, duration_s FROM assets WHERE workspace_id = ? ORDER BY id DESC LIMIT 40",
        (int(workspace_id),),
    )
    images = query_all(
        db_file,
        "SELECT id, prompt, image_path, cutout_path, motion_shot_id FROM ai_images WHERE workspace_id = ? ORDER BY id DESC LIMIT 30",
        (int(workspace_id),),
    )
    return {
        "workspace_id": int(workspace_id),
        "videos": [
            {**v, "url": f"/files/{str(v['output_path']).lstrip('/')}"}
            for v in videos
        ],
        "shots": [
            {**s, "url": f"/files/{str(s['media_path']).lstrip('/')}"}
            for s in shots
            if s.get("media_path")
        ],
        "assets": [
            {**a, "url": f"/files/{str(a['path']).lstrip('/')}"}
            for a in assets
        ],
        "images": [
            {**im, "url": f"/files/{str(im['image_path']).lstrip('/')}"}
            for im in images
            if im.get("image_path")
        ],
    }


def _hydrate_editor_project(row: dict[str, Any]) -> dict[str, Any]:
    out = dict(row)
    out["tracks"] = loads_or(
        row.get("tracks_json"),
        {"video_clips": [], "audio_clips": [], "subtitles": []},
    )
    return out


def get_editor_project(db_file: Path, project_id: int) -> dict[str, Any] | None:
    row = query_one(db_file, "SELECT * FROM editor_projects WHERE id = ?", (int(project_id),))
    return _hydrate_editor_project(row) if row else None


def list_editor_projects(db_file: Path, *, workspace_id: int) -> list[dict[str, Any]]:
    rows = query_all(
        db_file,
        "SELECT * FROM editor_projects WHERE workspace_id = ? ORDER BY id DESC LIMIT 100",
        (int(workspace_id),),
    )
    return [_hydrate_editor_project(r) for r in rows]


def create_editor_project(
    paths: AppPaths,
    *,
    workspace_id: int,
    title: str,
    source_video_id: int | None = None,
    aspect_ratio: str = "9:16",
    fps: int = 30,
    tracks: dict[str, Any] | None = None,
    actor: str = "api",
) -> dict[str, Any]:
    ws = require_workspace(paths.db_file, workspace_id)
    clean_title = (title or "").strip() or "Timeline Project"
    initial_tracks = tracks or {"video_clips": [], "audio_clips": [], "subtitles": []}

    if source_video_id and not initial_tracks.get("video_clips"):
        v_row = query_one(
            paths.db_file,
            "SELECT * FROM videos WHERE id = ? AND workspace_id = ?",
            (int(source_video_id), int(workspace_id)),
        )
        if v_row and v_row.get("output_path"):
            dur = max(1.0, float(v_row.get("duration_s") or 3.0))
            initial_tracks = {
                "video_clips": [
                    {
                        "source_path": str(v_row["output_path"]),
                        "start_s": 0.0,
                        "duration_s": round(dur, 3),
                    }
                ],
                "audio_clips": [],
                "subtitles": [],
            }

    ratio = (aspect_ratio or str(ws.get("default_aspect_ratio") or "9:16")).strip() or "9:16"
    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO editor_projects (
                workspace_id, title, source_video_id, aspect_ratio, fps, tracks_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(workspace_id),
                clean_title,
                int(source_video_id) if source_video_id else None,
                ratio,
                max(24, min(60, int(fps))),
                json.dumps(initial_tracks, ensure_ascii=False),
            ),
        )
        pid = int(cur.lastrowid)
        record_audit(
            conn,
            actor=actor,
            action="create_editor_project",
            object_type="editor_project",
            object_id=pid,
            detail=clean_title,
        )
    proj = get_editor_project(paths.db_file, pid)
    assert proj is not None
    return proj


def update_editor_project(
    paths: AppPaths,
    project_id: int,
    *,
    title: str | None = None,
    aspect_ratio: str | None = None,
    tracks: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if get_editor_project(paths.db_file, project_id) is None:
        return None
    sets: list[str] = ["updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"]
    params: list[Any] = []
    if title is not None and title.strip():
        sets.append("title = ?")
        params.append(title.strip())
    if aspect_ratio is not None and aspect_ratio.strip():
        sets.append("aspect_ratio = ?")
        params.append(aspect_ratio.strip())
    if tracks is not None:
        sets.append("tracks_json = ?")
        params.append(json.dumps(tracks, ensure_ascii=False))
    params.append(int(project_id))
    with get_conn(paths.db_file) as conn:
        conn.execute(f"UPDATE editor_projects SET {', '.join(sets)} WHERE id = ?", params)
    return get_editor_project(paths.db_file, project_id)


def render_editor_project(
    paths: AppPaths,
    project_id: int,
    *,
    style_preset: str = "tiktok_karaoke",
) -> dict[str, Any]:
    """Composes timeline `video_clips` + `audio_clips` + `subtitles` into a master MP4 & Video row."""
    proj = get_editor_project(paths.db_file, project_id)
    if proj is None:
        raise ValueError(f"Editor project #{project_id} not found")

    tracks = dict(proj.get("tracks") or {})
    video_clips: list[dict[str, Any]] = list(tracks.get("video_clips") or [])
    if not video_clips:
        raise ValueError("Timeline project requires at least 1 video clip")

    ws_id = int(proj["workspace_id"])
    ratio = str(proj.get("aspect_ratio") or "9:16")
    canvas_w, canvas_h = resolve_canvas_dimensions(ratio)
    style_row = resolve_style_preset(paths.db_file, style_preset)

    work_dir = paths.work_dir / f"editor_{project_id}"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    with get_conn(paths.db_file) as conn:
        conn.execute(
            "UPDATE editor_projects SET status = 'rendering', error = NULL WHERE id = ?",
            (int(project_id),),
        )

    try:
        seg_files: list[str] = []
        cut_times: list[float] = []
        cursor_s = 0.0
        total_clips = max(1, len(video_clips))
        for idx, clip in enumerate(video_clips, start=1):
            report_active_job_progress(
                0.1 + 0.55 * ((idx - 1) / total_clips),
                f"Đang cắt clip timeline {idx}/{total_clips}...",
            )
            shot_id = int(clip.get("shot_id") or 0)
            if shot_id > 0:
                shot_row, src_file = load_shot_source(paths, shot_id)
                st = max(0.0, float(clip.get("start_s", shot_row.get("start_s") or 0.0)))
            else:
                rel_p = str(clip.get("source_path") or "").strip().lstrip("/")
                src_file = Path(rel_p)
                if not src_file.is_absolute():
                    src_file = paths.media_dir / rel_p
                st = max(0.0, float(clip.get("start_s") or 0.0))

            if not src_file.exists():
                raise FileNotFoundError(f"Timeline clip source missing: {src_file}")

            src_dur = max(0.5, probe_duration(src_file))
            dur = max(0.5, float(clip.get("duration_s") or min(3.0, src_dur)))
            in_args: list[str] = []
            if st + dur > max(0.5, src_dur - 0.05):
                in_args.extend(["-stream_loop", "-1"])
                st = 0.0 if st >= src_dur - 0.2 else st
            in_args.extend(["-ss", f"{st:.3f}", "-t", f"{dur:.3f}", "-i", str(src_file.resolve())])

            seg_name = f"ed_seg_{idx:02d}.mp4"
            seg_path = work_dir / seg_name
            vf = (
                f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
                f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30,format=yuv420p"
            )
            has_audio = probe_video(src_file).has_audio
            if has_audio:
                audio_in: list[str] = []
                audio_out = ["-map", "0:v:0", "-map", "0:a:0", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k"]
            else:
                audio_in = ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
                audio_out = ["-map", "0:v:0", "-map", "1:a:0", "-c:a", "aac", "-ar", "48000", "-ac", "2", "-b:a", "128k", "-shortest"]

            run_ffmpeg(
                [
                    *in_args,
                    *audio_in,
                    "-vf",
                    vf,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "16",
                    "-pix_fmt",
                    "yuv420p",
                    "-r",
                    "30",
                    *audio_out,
                    str(seg_path.resolve()),
                ],
                cwd=work_dir,
            )
            seg_files.append(seg_name)
            cursor_s += dur
            if idx < len(video_clips):
                cut_times.append(round(cursor_s, 3))

        cut_mp4 = concat_segments(seg_files, work_dir)
        sub_events: list[SubtitleEvent] = []
        for s_item in tracks.get("subtitles") or []:
            txt = str(s_item.get("text") or "").strip()
            if txt:
                sub_events.append(
                    SubtitleEvent(
                        start_s=max(0.0, float(s_item.get("start_s") or 0.0)),
                        end_s=max(0.3, float(s_item.get("end_s") or 1.5)),
                        text=txt,
                        secondary_text=str(s_item.get("secondary_text") or ""),
                    )
                )

        voice_path: Path | None = None
        music_path: Path | None = None
        for ac in tracks.get("audio_clips") or []:
            a_rel = str(ac.get("source_path") or "").strip().lstrip("/")
            if not a_rel:
                continue
            cand = Path(a_rel) if Path(a_rel).is_absolute() else (paths.media_dir / a_rel)
            if not cand.exists():
                continue
            if str(ac.get("kind") or "music") == "voice" and voice_path is None:
                voice_path = cand
            elif music_path is None:
                music_path = cand

        with get_conn(paths.db_file) as conn:
            cur = conn.execute(
                """
                INSERT INTO videos (
                    workspace_id, engine, status, plan_json, voice_lang, caption_lang,
                    style_preset, aspect_ratio, auto_render
                )
                VALUES (?, 'ffmpeg', 'planned', ?, 'none', 'vi', ?, ?, 0)
                """,
                (
                    ws_id,
                    json.dumps({"title": proj["title"], "editor_project_id": project_id, "shots": []}, ensure_ascii=False),
                    style_row["id"],
                    ratio,
                ),
            )
            video_id = int(cur.lastrowid)

        transition(paths.db_file, video_id, "rendering", expected_from="planned")
        report_active_job_progress(0.75, "Đang ghép timeline master -14 LUFS & kiểm định QC...")
        rel_out, rel_cover, actual_dur, preflight_map, qc_report = finalize_master_export(
            paths,
            video_id=video_id,
            cut_mp4=cut_mp4,
            work_dir=work_dir,
            sub_events=sub_events,
            style_row=style_row,
            aspect_ratio=ratio,
            music_path=music_path,
            voice_path=voice_path,
            cut_times_s=cut_times,
            mix_source_audio=True,
        )
        render_cache = save_render_cache(
            paths,
            video_id=video_id,
            cut_mp4=cut_mp4,
            voice_path=voice_path,
            sub_events=sub_events,
            cut_times_s=cut_times,
            music_asset_id=None,
            aspect_ratio=ratio,
            mix_source_audio=True,
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
                    8.6 if qc_report.get("passed") else 5.0,
                    video_id,
                ),
            )
            conn.execute(
                """
                UPDATE editor_projects
                SET output_video_id = ?, status = 'completed', error = NULL,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE id = ?
                """,
                (video_id, int(project_id)),
            )
            record_audit(
                conn,
                actor="timeline_editor",
                action="render_editor_project",
                object_type="editor_project",
                object_id=int(project_id),
                detail=f"video #{video_id} ({rel_out})",
            )
        done = get_editor_project(paths.db_file, project_id)
        assert done is not None
        return done
    except Exception as exc:
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE editor_projects SET status = 'failed', error = ? WHERE id = ?",
                (str(exc)[:400], int(project_id)),
            )
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def run_editor_render_job(paths: AppPaths, project_id: int) -> str:
    proj = get_editor_project(paths.db_file, project_id)
    tracks = dict((proj or {}).get("tracks") or {})
    style_preset = str(tracks.get("style_preset") or "tiktok_karaoke")
    done = render_editor_project(paths, project_id, style_preset=style_preset)
    return str(done.get("status") or "completed")
