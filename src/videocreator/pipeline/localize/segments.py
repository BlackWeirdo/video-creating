"""Segment cutting, anti-duplicate transforms, and dynamic OCR/LaMa hardsub masking for Localize Studio."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from videocreator.models_manager import get_local_model
from videocreator.paths import AppPaths
from videocreator.pipeline.assembly import load_shot_source
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.ocr_hardsub import inpaint_segment_with_lama
from videocreator.pipeline.probe import probe_duration
from videocreator.pipeline.render_inputs import build_segment_filter_args


def clamp_box_pixels(
    box: dict[str, Any], src_w: int, src_h: int, *, inset: int = 0
) -> tuple[int, int, int, int]:
    bx = max(inset, min(src_w - 16 - inset, (int(src_w * float(box.get("x", 0.06))) // 2) * 2))
    by = max(inset, min(src_h - 16 - inset, (int(src_h * float(box.get("y", 0.74))) // 2) * 2))
    bw = max(16, min(src_w - bx - inset, (int(src_w * float(box.get("w", 0.88))) // 2) * 2))
    bh = max(16, min(src_h - by - inset, (int(src_h * float(box.get("h", 0.16))) // 2) * 2))
    return bx, by, bw, bh


def anti_dup_filter_steps(anti_dup: dict[str, Any], mode: str) -> list[str]:
    if mode != "reup_vi":
        return []
    steps: list[str] = []
    if anti_dup.get("mirror"):
        steps.append("hflip")
    zoom = float(anti_dup.get("zoom") or 1.0)
    if zoom > 1.005:
        z = min(1.25, max(1.01, zoom))
        steps.append(f"crop=trunc(iw/{z:.3f}/2)*2:trunc(ih/{z:.3f}/2)*2")
    if anti_dup.get("color_eq", True):
        steps.append("eq=contrast=1.03:saturation=1.04")
    return steps


def boxes_for_segment_window(
    seg: dict[str, Any],
    ocr_cues: list[dict[str, Any]],
    fallback_box: dict[str, Any],
) -> tuple[list[dict[str, float]], bool]:
    """Resolve active hardsub bounding boxes for `[seg.start_s, seg.end_s]`."""
    st = float(seg.get("start_s") or 0.0)
    en = float(seg.get("end_s") or (st + 1.5))
    matched: list[dict[str, float]] = []
    for cue in ocr_cues:
        c_st = float(cue.get("start_s") or 0.0)
        c_en = float(cue.get("end_s") or 0.0)
        if (
            min(en + 0.12, c_en) - max(st - 0.12, c_st) > 0.08
            and isinstance(cue.get("box"), dict)
        ):
            matched.append(dict(cue["box"]))
    if matched:
        return matched, True
    if isinstance(seg.get("hardsub_box"), dict):
        return [dict(seg["hardsub_box"])], True
    if ocr_cues:
        return [], False
    return [dict(fallback_box)], True


def cut_localized_segment(
    paths: AppPaths,
    src_mp4: Path,
    seg_path: Path,
    *,
    start_s: float,
    duration_s: float,
    src_duration_s: float,
    src_w: int,
    src_h: int,
    canvas_w: int,
    canvas_h: int,
    hardsub_mode: str,
    active_boxes: list[dict[str, float]],
    fallback_box: dict[str, Any],
    anti_dup: dict[str, Any],
    mode: str,
    work_dir: Path,
) -> bool:
    """Cut & process hardsubs on a single segment. Return `True` if LaMa ONNX ran."""
    anti_steps = anti_dup_filter_steps(anti_dup, mode)
    scale_tail = (
        f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=decrease,"
        f"pad={canvas_w}:{canvas_h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps=30,format=yuv420p"
    )
    need_loop = start_s + duration_s > max(0.5, src_duration_s - 0.05)
    seek_s = 0.0 if start_s >= max(0.0, src_duration_s - 0.25) else start_s

    input_args: list[str] = []
    if need_loop:
        input_args.extend(["-stream_loop", "-1"])
    input_args.extend(
        ["-ss", f"{seek_s:.3f}", "-t", f"{duration_s:.3f}", "-i", str(src_mp4.resolve())]
    )
    extra_meta = ["-map_metadata", "-1"] if mode == "reup_vi" else []

    if hardsub_mode == "ocr_inpaint" and active_boxes:
        lama_info = get_local_model(paths, "paddle_lama_inpaint")
        if (
            lama_info
            and lama_info.get("status") == "ready"
            and lama_info.get("installed_on_disk")
        ):
            raw_clip = work_dir / f"_raw_{seg_path.name}"
            inpainted_clip = work_dir / f"_inp_{seg_path.name}"
            run_ffmpeg(
                [
                    *input_args,
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
                    "-an",
                    str(raw_clip.resolve()),
                ],
                cwd=work_dir,
            )
            ok_lama = inpaint_segment_with_lama(
                paths,
                raw_clip,
                inpainted_clip,
                boxes=active_boxes,
                work_dir=work_dir,
            )
            raw_clip.unlink(missing_ok=True)
            if ok_lama and inpainted_clip.is_file():
                vf_post = [*anti_steps, scale_tail]
                run_ffmpeg(
                    [
                        "-i",
                        str(inpainted_clip.resolve()),
                        "-vf",
                        ",".join(vf_post),
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
                        "-an",
                        *extra_meta,
                        str(seg_path.resolve()),
                    ],
                    cwd=work_dir,
                    allow_creative_filters=bool(anti_steps),
                )
                inpainted_clip.unlink(missing_ok=True)
                return True
            inpainted_clip.unlink(missing_ok=True)

    union_box: dict[str, Any] | None = None
    if active_boxes:
        x1 = min(float(b["x"]) for b in active_boxes)
        y1 = min(float(b["y"]) for b in active_boxes)
        x2 = max(float(b["x"]) + float(b["w"]) for b in active_boxes)
        y2 = max(float(b["y"]) + float(b["h"]) for b in active_boxes)
        union_box = {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}

    if hardsub_mode == "blur_bar" and union_box is not None:
        bx, by, bw, bh = clamp_box_pixels(union_box, src_w, src_h, inset=0)
        luma_r = max(2, min(16, min(bw, bh) // 4 - 1))
        chroma_r = max(1, min(8, min(bw, bh) // 8 - 1))
        anti_chain = ("," + ",".join(anti_steps)) if anti_steps else ""
        fc = (
            f"[0:v]split[base][sub];"
            f"[sub]crop={bw}:{bh}:{bx}:{by},boxblur={luma_r}:2:{chroma_r}:1,"
            f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.48:t=fill[blurred];"
            f"[base][blurred]overlay={bx}:{by}{anti_chain},{scale_tail}[vout]"
        )
        filter_args = ["-filter_complex", fc, "-map", "[vout]"]
    else:
        vf_steps: list[str] = []
        if hardsub_mode == "crop_frame":
            ref_b = union_box or fallback_box
            norm_y = float(ref_b.get("y", 0.74))
            norm_h = float(ref_b.get("h", 0.16))
            if norm_y >= 0.48:
                keep_h = max(32, (int(src_h * max(0.35, min(0.92, norm_y))) // 2) * 2)
                vf_steps.append(f"crop=iw:{keep_h}:0:0")
            else:
                cut_top = (int(src_h * min(0.55, norm_y + norm_h)) // 2) * 2
                keep_h = max(32, ((src_h - cut_top) // 2) * 2)
                vf_steps.append(f"crop=iw:{keep_h}:0:{cut_top}")
        elif hardsub_mode == "ocr_inpaint" and union_box is not None:
            bx, by, bw, bh = clamp_box_pixels(union_box, src_w, src_h, inset=2)
            vf_steps.append(f"delogo=x={bx}:y={by}:w={bw}:h={bh}:show=0")
        vf_steps.extend(anti_steps)
        vf_steps.append(scale_tail)
        filter_args = ["-vf", ",".join(vf_steps), "-map", "0:v:0"]

    run_ffmpeg(
        [
            *input_args,
            *filter_args,
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
            "-an",
            *extra_meta,
            str(seg_path.resolve()),
        ],
        cwd=work_dir,
        allow_creative_filters=(hardsub_mode != "none" or bool(anti_steps)),
    )
    return False


def cut_real_product_shot_segment(
    paths: AppPaths,
    shot_id: int,
    seg_path: Path,
    *,
    duration_s: float,
    canvas_w: int,
    canvas_h: int,
    work_dir: Path,
) -> None:
    """Cut a real `shots` clip strictly under BR-PRD-01 whitelist (zero creative/color filters)."""
    shot_row, src_file = load_shot_source(paths, shot_id)
    start_s = max(0.0, float(shot_row.get("start_s") or 0.0))
    src_dur = max(0.5, probe_duration(src_file))
    try:
        crop_cfg = json.loads(shot_row["crop_json"]) if shot_row.get("crop_json") else None
    except Exception:
        crop_cfg = None
    raw_focus = shot_row.get("focus_x")
    focus_x = float(raw_focus) if raw_focus is not None else None
    filter_args = build_segment_filter_args(
        orientation=str(shot_row.get("orientation") or "portrait"),
        width=int(shot_row.get("width") or 1080),
        height=int(shot_row.get("height") or 1920),
        crop_cfg=crop_cfg,
        focus_x=focus_x,
        target_width=canvas_w,
        target_height=canvas_h,
    )
    video_map = [] if filter_args[0] == "-filter_complex" else ["-map", "0:v:0"]
    in_args: list[str] = []
    if start_s + duration_s > max(0.5, src_dur - 0.05):
        in_args.extend(["-stream_loop", "-1"])
        start_s = 0.0 if start_s >= src_dur - 0.25 else start_s
    in_args.extend(
        ["-ss", f"{start_s:.3f}", "-t", f"{duration_s:.3f}", "-i", str(src_file.resolve())]
    )

    run_ffmpeg(
        [
            *in_args,
            *filter_args,
            *video_map,
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
        allow_creative_filters=False,
    )
