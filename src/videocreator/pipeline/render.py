"""5-step FFmpeg 9:16 renderer with ASS subtitles, landscape blur-pad/crop, music mix, and preflight (Phase 05)."""
from __future__ import annotations

import json
import logging
import random
import shutil
from pathlib import Path
from typing import Any

from videocreator.config import load_settings
from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.paths import AppPaths
from videocreator.pipeline.export import extract_cover_frame, normalize_to_master
from videocreator.pipeline.ffmpeg import RenderError, run_ffmpeg
from videocreator.pipeline.preflight import check_all_platforms
from videocreator.pipeline.probe import probe_duration
from videocreator.pipeline.subtitles import FONTS_DIR, SubtitleEvent, build_ass, parse_srt
from videocreator.state import transition
from videocreator.telegram_bot import notify_pending

logger = logging.getLogger("videocreator.pipeline.render")


def build_segment_filter_args(
    *,
    orientation: str,
    width: int,
    height: int,
    crop_cfg: dict[str, Any] | None,
) -> list[str]:
    """Builds `-vf` or `-filter_complex` arguments to convert a source shot to 1080x1920 30fps without violating BR-PRD-03."""
    if orientation == "landscape" and width > 0 and height > 0:
        mode = str((crop_cfg or {}).get("mode") or "blur_pad")
        if mode == "crop":
            x_ratio = max(0.0, min(1.0, float((crop_cfg or {}).get("x_offset_ratio", 0.5))))
            crop_w = int(round(height * 9 / 16))
            crop_w = max(2, crop_w - (crop_w % 2))
            crop_w = min(width, crop_w)
            max_x = max(0, width - crop_w)
            x_off = int(round(max_x * x_ratio))
            vf = f"crop={crop_w}:{height}:{x_off}:0,scale=1080:1920,setsar=1,fps=30"
            return ["-vf", vf]

        # Default landscape handling: full frame centered on a blurred 9:16 background (never center-cropped)
        fc = (
            "split[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:5[bgb];"
            "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fgs];"
            "[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1,fps=30"
        )
        return ["-filter_complex", fc]

    vf = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
        "setsar=1,"
        "fps=30"
    )
    return ["-vf", vf]


def _pick_music_asset(paths: AppPaths, music_asset_id: int | None = None) -> Path | None:
    if music_asset_id is not None:
        row = query_one(
            paths.db_file,
            "SELECT path FROM assets WHERE id = ? AND kind = 'music'",
            (music_asset_id,),
        )
        if row and row.get("path"):
            p = paths.media_dir / str(row["path"])
            if p.exists():
                return p
    rows = query_all(paths.db_file, "SELECT path FROM assets WHERE kind = 'music' ORDER BY id ASC")
    valid_paths = [paths.media_dir / str(r["path"]) for r in rows if r.get("path") and (paths.media_dir / str(r["path"])).exists()]
    if not valid_paths:
        return None
    return random.choice(valid_paths)


def render_video(
    paths: AppPaths,
    video_id: int,
    *,
    preset: str = "veryfast",
    music_asset_id: int | None = None,
    mpt_client: Any = None,
    auto_score: bool = False,
    score_provider: Any = None,
    score_override: float | None = None,
) -> str:
    """Executes the 5-step FFmpeg (or MPT + FFmpeg fallback) render pipeline for `video_id`."""
    video_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    if video_row is None:
        raise LookupError(f"Video #{video_id} not found")

    cur_status = str(video_row["status"])
    if cur_status in ("planned", "failed", "pending_approval", "rendered"):
        if cur_status != "planned":
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    "UPDATE videos SET status = 'planned', error = NULL WHERE id = ?",
                    (video_id,),
                )
        transition(paths.db_file, video_id, "rendering", expected_from="planned", error=None)
    elif cur_status != "rendering":
        raise RenderError(f"Cannot render video #{video_id} from status '{cur_status}'")

    settings = load_settings(paths.config_file)
    work_dir = paths.work_dir / f"render_{video_id}"
    if work_dir.exists():
        shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        try:
            plan = json.loads(video_row.get("plan_json") or "{}")
        except json.JSONDecodeError as exc:
            raise RenderError(f"Invalid plan_json on video #{video_id}: {exc}") from exc

        planned_shots = plan.get("shots") or []
        if not planned_shots:
            raise RenderError(f"Video #{video_id} plan has no shots")

        seg_files: list[str] = []
        sub_events: list[SubtitleEvent] = []
        cursor_s = 0.0

        # Step 1: Cut each shot into a 1080x1920 30fps segment
        for idx, ps in enumerate(planned_shots, start=1):
            shot_id = int(ps.get("shot_id") or 0)
            shot_row = query_one(
                paths.db_file,
                """
                SELECT s.*, f.path AS footage_path, f.orientation, f.width, f.height, f.crop_json,
                       a.path AS asset_path
                FROM shots s
                LEFT JOIN footage f ON s.footage_id = f.id
                LEFT JOIN assets a ON s.asset_id = a.id
                WHERE s.id = ?
                """,
                (shot_id,),
            )
            if shot_row is None:
                raise RenderError(f"Shot #{shot_id} does not exist in shots library")

            rel_src = shot_row.get("footage_path") or shot_row.get("asset_path")
            if not rel_src:
                raise RenderError(f"Shot #{shot_id} has no backing video file")
            src_file = paths.media_dir / str(rel_src)
            if not src_file.exists():
                raise RenderError(f"Backing video file missing on disk: {src_file}")

            start_s = max(0.0, float(ps.get("start_s", shot_row["start_s"])))
            duration_s = max(0.5, float(ps.get("duration_s", float(shot_row["end_s"]) - start_s)))
            try:
                crop_cfg = json.loads(shot_row["crop_json"]) if shot_row.get("crop_json") else None
            except Exception:
                crop_cfg = None

            filter_args = build_segment_filter_args(
                orientation=str(shot_row.get("orientation") or "portrait"),
                width=int(shot_row.get("width") or 1080),
                height=int(shot_row.get("height") or 1920),
                crop_cfg=crop_cfg,
            )

            seg_name = f"seg_{idx:02d}.mp4"
            seg_path = work_dir / seg_name
            run_ffmpeg(
                [
                    "-ss",
                    f"{start_s:.3f}",
                    "-t",
                    f"{duration_s:.3f}",
                    "-i",
                    str(src_file.resolve()),
                    *filter_args,
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "14",
                    "-pix_fmt",
                    "yuv420p",
                    "-r",
                    "30",
                    "-an",
                    str(seg_path.resolve()),
                ],
                cwd=work_dir,
            )
            seg_files.append(seg_name)

            text_line = str(ps.get("text") or "").strip()
            if text_line:
                sub_events.append(
                    SubtitleEvent(
                        start_s=round(cursor_s, 3),
                        end_s=round(cursor_s + duration_s, 3),
                        text=text_line,
                    )
                )
            cursor_s += duration_s

        # Step 2: Concatenate segments via concat demuxer
        concat_list = work_dir / "concat.txt"
        concat_list.write_text(
            "\n".join(f"file '{name}'" for name in seg_files) + "\n",
            encoding="utf-8",
        )
        cut_mp4 = work_dir / "cut.mp4"
        run_ffmpeg(
            [
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                "concat.txt",
                "-c",
                "copy",
                "cut.mp4",
            ],
            cwd=work_dir,
        )

        # Step 3: Optional voice-over (MoneyPrinterTurbo). With a voice, subtitles follow the
        # voice timing instead of the shot timing (FR-REN-07).
        engine_mode = str(video_row.get("engine") or "ffmpeg")
        voice_lang = str(video_row.get("voice_lang") or plan.get("voice_lang") or "none")
        voice_track = None
        if voice_lang in ("vi", "en") and (engine_mode == "mpt" or mpt_client is not None):
            from videocreator.engines.mpt_engine import add_quality_note, try_voice_with_mpt

            voice_track = try_voice_with_mpt(
                paths,
                video_id,
                script_lines=[str(ps.get("text") or "") for ps in planned_shots],
                voice_lang=voice_lang,
                work_dir=work_dir,
                mpt_client=mpt_client,
            )
            if voice_track is not None:
                sub_events = [ev for ev in parse_srt(voice_track.srt_path.read_text(encoding="utf-8")) if ev.start_s < cursor_s]
                voice_dur = probe_duration(voice_track.audio_path)
                if voice_dur > cursor_s + 0.3:
                    add_quality_note(
                        paths,
                        video_id,
                        f"Lời đọc dài {voice_dur:.1f}s nhưng hình chỉ {cursor_s:.1f}s: phần lời cuối bị cắt, nên rút lời hoặc thêm shot",
                    )

        # Write UTF-8 ASS subtitle file in work_dir
        ass_content = build_ass(
            sub_events,
            safe_bottom_ratio=settings.safe_zone.bottom,
            safe_right_ratio=settings.safe_zone.right,
        )
        ass_file = work_dir / "sub.ass"
        ass_file.write_text(ass_content, encoding="utf-8")
        shutil.copytree(FONTS_DIR, work_dir / "fonts", dirs_exist_ok=True)

        # Step 4: Burn ASS subtitles, mix music/silent track, and normalize to Master MP4 + cover.jpg
        rel_out = f"output/video_{video_id}.mp4"
        rel_cover = f"output/cover_{video_id}.jpg"
        abs_out = paths.media_dir / rel_out
        abs_cover = paths.media_dir / rel_cover

        music_path = _pick_music_asset(paths, music_asset_id=music_asset_id)
        actual_duration_s = normalize_to_master(
            cut_mp4,
            abs_out,
            music_path=music_path,
            voice_path=voice_track.audio_path if voice_track is not None else None,
            ass_filename="sub.ass" if sub_events else None,
            cwd=work_dir,
            preset=preset,
            crf=18,
        )
        extract_cover_frame(abs_out, abs_cover, at_s=1.0)

        # Step 5: Run platform preflight checks
        preflight_map = check_all_platforms(abs_out, settings)

        transition(paths.db_file, video_id, "rendered", expected_from="rendering")

        with get_conn(paths.db_file) as conn:
            conn.execute(
                """
                UPDATE videos
                SET output_path = ?,
                    cover_path = ?,
                    duration_s = ?,
                    preflight_json = ?,
                    error = NULL
                WHERE id = ?
                """,
                (
                    rel_out,
                    rel_cover,
                    round(actual_duration_s, 3),
                    json.dumps(preflight_map, ensure_ascii=False),
                    video_id,
                ),
            )
            record_audit(
                conn,
                actor="worker",
                action="video.rendered",
                object_type="video",
                object_id=video_id,
                detail=f"duration={actual_duration_s:.2f}s, out={rel_out}",
            )

        shutil.rmtree(work_dir, ignore_errors=True)

        final_status = "pending_approval"
        should_score = (
            auto_score
            or score_provider is not None
            or score_override is not None
            or int(video_row.get("auto_render") or 0) == 1
        )
        if should_score:
            try:
                from videocreator.tg.progress import score_rendered_video

                final_status, _active_id, _sc = score_rendered_video(
                    paths,
                    video_id,
                    provider=score_provider,
                    score_override=score_override,
                )
            except Exception as sc_exc:
                logger.warning("Auto quality score skipped for video #%d: %s", video_id, sc_exc)
                cur_row = query_one(paths.db_file, "SELECT status FROM videos WHERE id = ?", (video_id,))
                cur_st = str(cur_row["status"]) if cur_row else "rendered"
                if cur_st in ("rendered", "scoring"):
                    transition(paths.db_file, video_id, "pending_approval", expected_from=cur_st)
                final_status = "pending_approval"
        else:
            transition(paths.db_file, video_id, "pending_approval", expected_from="rendered")

        if final_status == "pending_approval":
            try:
                notify_pending(paths, video_id)
            except Exception as tg_exc:
                logger.warning("notify_pending hook warning for video #%d: %s", video_id, tg_exc)
        return f"Rendered video #{video_id} ({actual_duration_s:.2f}s) -> {rel_out}"

    except Exception as exc:
        err_msg = str(exc)[:500]
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "UPDATE videos SET status = 'failed', error = ? WHERE id = ?",
                (err_msg, video_id),
            )
        raise


def enqueue_batch_render(db_file: Path) -> list[int]:
    """Enqueues sequential `render` jobs for all videos currently in `planned` status (`FR-REN-09`)."""
    from videocreator.jobs import enqueue_job

    rows = query_all(
        db_file,
        "SELECT id FROM videos WHERE status = 'planned' ORDER BY id ASC",
    )
    job_ids: list[int] = []
    for r in rows:
        vid = int(r["id"])
        jid = enqueue_job(db_file, "render", ref_id=vid)
        job_ids.append(jid)
    return job_ids

