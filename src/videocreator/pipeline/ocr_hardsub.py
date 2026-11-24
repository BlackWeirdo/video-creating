"""RapidOCR hardsub detector, Whisper+OCR cue aligner & LaMa ONNX high-quality inpaint (Stage R3)."""
from __future__ import annotations

import difflib
import gc
import logging
import re
from pathlib import Path
from typing import Any

import numpy as np

from videocreator.models_manager import get_local_model
from videocreator.paths import AppPaths
from videocreator.pipeline.ffmpeg import run_ffmpeg

logger = logging.getLogger("videocreator.pipeline.ocr_hardsub")

_NORM_SPACE_RE = re.compile(r"[\s\W_]+", flags=re.UNICODE)
_HAS_LETTER_RE = re.compile(r"[^\W\d_]", flags=re.UNICODE)


def _normalize_ocr_text(text: str) -> str:
    return _NORM_SPACE_RE.sub("", (text or "").lower()).strip()


def _text_similarity(a: str, b: str) -> float:
    na = _normalize_ocr_text(a)
    nb = _normalize_ocr_text(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _union_norm_boxes(boxes: list[dict[str, float]]) -> dict[str, float]:
    x1 = min(float(b["x"]) for b in boxes)
    y1 = min(float(b["y"]) for b in boxes)
    x2 = max(float(b["x"]) + float(b["w"]) for b in boxes)
    y2 = max(float(b["y"]) + float(b["h"]) for b in boxes)
    return {
        "x": round(max(0.0, x1), 4),
        "y": round(max(0.0, y1), 4),
        "w": round(min(1.0 - max(0.0, x1), x2 - x1), 4),
        "h": round(min(1.0 - max(0.0, y1), y2 - y1), 4),
    }


def extract_hardsub_ocr_cues(
    video_path: Path,
    *,
    sample_every_s: float = 0.5,
    bottom_ratio: float = 0.42,
    min_conf: float = 0.65,
) -> list[dict[str, Any]]:
    """Samples the bottom region of `video_path` with RapidOCR and merges repeated subtitle cues over time."""
    if not video_path.is_file():
        return []

    try:
        import cv2
        from rapidocr_onnxruntime import RapidOCR
    except Exception as exc:
        logger.warning("RapidOCR unavailable for %s: %s", video_path.name, exc)
        return []

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []

    ocr = RapidOCR()
    frame_samples: list[dict[str, Any]] = []
    try:
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
        if fps <= 1.0 or fps > 240.0:
            fps = 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
        if width < 32 or height < 32:
            return []

        step_frames = max(1, int(round(fps * max(0.2, sample_every_s))))
        roi_y0 = int(height * max(0.25, 1.0 - bottom_ratio))
        frame_idx = 0

        while True:
            if total_frames > 0 and frame_idx >= total_frames:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                break

            t_s = round(frame_idx / fps, 3)
            roi = frame[roi_y0:height, 0:width]
            res, _ = ocr(roi)
            if res:
                line_items: list[tuple[float, float, str, float, dict[str, float]]] = []
                for det in res:
                    if not isinstance(det, (list, tuple)) or len(det) < 3:
                        continue
                    pts, raw_txt, conf_raw = det[0], str(det[1] or "").strip(), float(det[2] or 0.0)
                    if not raw_txt or conf_raw < min_conf or not _HAS_LETTER_RE.search(raw_txt):
                        continue
                    xs = [float(p[0]) for p in pts]
                    ys = [float(p[1]) + roi_y0 for p in pts]
                    bx1, bx2 = max(0.0, min(xs)), min(float(width), max(xs))
                    by1, by2 = max(0.0, min(ys)), min(float(height), max(ys))
                    bw_px, bh_px = bx2 - bx1, by2 - by1
                    if bw_px < width * 0.035 or bh_px < height * 0.012 or bh_px > height * 0.28:
                        continue
                    pad_x = width * 0.018
                    pad_y = height * 0.012
                    nx = max(0.0, (bx1 - pad_x) / width)
                    ny = max(0.0, (by1 - pad_y) / height)
                    nw = min(1.0 - nx, (bw_px + 2 * pad_x) / width)
                    nh = min(1.0 - ny, (bh_px + 2 * pad_y) / height)
                    line_items.append(
                        (
                            by1,
                            bx1,
                            raw_txt,
                            conf_raw,
                            {
                                "x": round(nx, 4),
                                "y": round(ny, 4),
                                "w": round(nw, 4),
                                "h": round(nh, 4),
                            },
                        )
                    )

                if line_items:
                    line_items.sort(key=lambda it: (round(it[0] / max(8.0, height * 0.03)), it[1]))
                    joined_text = " ".join(it[2] for it in line_items).strip()
                    avg_conf = sum(it[3] for it in line_items) / len(line_items)
                    ubox = _union_norm_boxes([it[4] for it in line_items])
                    frame_samples.append(
                        {
                            "t_s": t_s,
                            "text": joined_text,
                            "confidence": round(avg_conf, 3),
                            "box": ubox,
                        }
                    )

            frame_idx += step_frames
    finally:
        cap.release()
        del ocr
        gc.collect()

    if not frame_samples:
        return []

    # Merge consecutive samples with matching text into timed cues
    cues: list[dict[str, Any]] = []
    half_win = round(sample_every_s, 3)
    for smp in frame_samples:
        st = max(0.0, round(float(smp["t_s"]) - 0.1, 3))
        en = round(float(smp["t_s"]) + half_win, 3)
        if cues:
            prev = cues[-1]
            gap = float(smp["t_s"]) - float(prev["end_s"])
            if gap <= sample_every_s * 1.6 and _text_similarity(str(prev["text"]), str(smp["text"])) >= 0.72:
                prev["end_s"] = max(float(prev["end_s"]), en)
                if len(str(smp["text"])) > len(str(prev["text"])) and float(smp["confidence"]) >= float(prev["confidence"]) - 0.05:
                    prev["text"] = smp["text"]
                prev["confidence"] = round(max(float(prev["confidence"]), float(smp["confidence"])), 3)
                prev["box"] = _union_norm_boxes([prev["box"], smp["box"]])
                continue

        cues.append(
            {
                "start_s": st,
                "end_s": max(st + 0.45, en),
                "text": str(smp["text"]),
                "confidence": float(smp["confidence"]),
                "box": dict(smp["box"]),
            }
        )

    # Filter out static corner watermarks that stay unchanged across >=85% of a multi-cue video
    if len(cues) == 1:
        return cues
    filtered: list[dict[str, Any]] = []
    for c in cues:
        b = c["box"]
        cx = float(b["x"]) + 0.5 * float(b["w"])
        is_centered = 0.22 <= cx <= 0.78
        if is_centered or float(b["w"]) >= 0.18:
            filtered.append(c)
    return filtered or cues


def align_ocr_and_whisper_segments(
    whisper_segments: list[dict[str, Any]],
    ocr_cues: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str]:
    """Merges OCR hardsub text with Whisper speech timestamps.

    When reliable OCR cues exist, uses OCR text as primary `source_text` snapped to overlapping
    Whisper boundaries, plus any uncovered Whisper speech turns.
    """
    valid_ocr = [c for c in ocr_cues if len(_normalize_ocr_text(str(c.get("text") or ""))) >= 1]
    valid_whisper = [
        s for s in whisper_segments
        if str(s.get("source_text") or "").strip()
        and not str(s.get("source_text") or "").startswith("Segment ")
    ]

    if not valid_ocr:
        return list(whisper_segments), ("whisper" if valid_whisper else "fallback")

    merged: list[dict[str, Any]] = []
    used_whisper_idxs: set[int] = set()

    for cue in valid_ocr:
        c_st = float(cue["start_s"])
        c_en = max(c_st + 0.5, float(cue["end_s"]))
        best_w_idx: int | None = None
        best_ov = 0.0
        for w_idx, w_seg in enumerate(valid_whisper):
            w_st = float(w_seg["start_s"])
            w_en = float(w_seg["end_s"])
            ov = min(c_en, w_en) - max(c_st, w_st)
            if ov > best_ov:
                best_ov = ov
                best_w_idx = w_idx

        if best_w_idx is not None and best_ov >= 0.25 and best_w_idx not in used_whisper_idxs:
            w_match = valid_whisper[best_w_idx]
            used_whisper_idxs.add(best_w_idx)
            # Snap start/end gently toward Whisper speech boundaries when close
            w_st = float(w_match["start_s"])
            w_en = float(w_match["end_s"])
            st = round(w_st if abs(w_st - c_st) <= 0.45 else c_st, 3)
            en = round(w_en if abs(w_en - c_en) <= 0.55 and w_en > st + 0.4 else max(st + 0.5, c_en), 3)
        else:
            st, en = round(c_st, 3), round(c_en, 3)

        merged.append(
            {
                "start_s": st,
                "end_s": en,
                "source_text": str(cue["text"]).strip(),
                "hardsub_box": dict(cue["box"]),
                "text_origin": "ocr",
            }
        )

    # Add Whisper speech segments that did not overlap any OCR cue
    for w_idx, w_seg in enumerate(valid_whisper):
        if w_idx in used_whisper_idxs:
            continue
        w_st = float(w_seg["start_s"])
        w_en = float(w_seg["end_s"])
        overlaps_any = any(
            (min(w_en, float(m["end_s"])) - max(w_st, float(m["start_s"]))) > 0.35
            for m in merged
        )
        if not overlaps_any:
            merged.append(
                {
                    "start_s": round(w_st, 3),
                    "end_s": round(max(w_st + 0.5, w_en), 3),
                    "source_text": str(w_seg["source_text"]).strip(),
                    "text_origin": "whisper",
                }
            )

    merged.sort(key=lambda x: (float(x["start_s"]), float(x["end_s"])))
    # Prevent accidental overlap between adjacent merged segments
    for idx in range(len(merged) - 1):
        if float(merged[idx]["end_s"]) > float(merged[idx + 1]["start_s"]):
            mid = round(0.5 * (float(merged[idx]["end_s"]) + float(merged[idx + 1]["start_s"])), 3)
            if mid > float(merged[idx]["start_s"]) + 0.35:
                merged[idx]["end_s"] = mid
                merged[idx + 1]["start_s"] = mid

    for idx, seg in enumerate(merged):
        seg["index"] = idx
    return merged, ("ocr+whisper" if valid_whisper else "ocr")


def inpaint_segment_with_lama(
    paths: AppPaths,
    src_mp4: Path,
    dst_mp4: Path,
    *,
    boxes: list[dict[str, float]],
    work_dir: Path,
) -> bool:
    """Inpaints subtitle bounding boxes on `src_mp4` using `lama_fp32.onnx` (`Carve/LaMa-ONNX`) on CPU."""
    lama_info = get_local_model(paths, "paddle_lama_inpaint")
    if not (lama_info and lama_info.get("status") == "ready" and lama_info.get("installed_on_disk")):
        return False
    if not boxes:
        return False

    try:
        import cv2
        import onnxruntime as ort
    except Exception:
        return False

    onnx_path = Path(str(lama_info["local_path"]))
    if onnx_path.is_dir():
        onnx_path = next(onnx_path.glob("*.onnx"))

    cap = cv2.VideoCapture(str(src_mp4))
    if not cap.isOpened():
        return False

    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    if width < 32 or height < 32:
        cap.release()
        return False

    # Build full-frame mask & crop ROI with generous context around union box
    full_mask = np.zeros((height, width), dtype=np.uint8)
    for b in boxes:
        x1 = max(0, int(width * float(b.get("x", 0.06))))
        y1 = max(0, int(height * float(b.get("y", 0.74))))
        x2 = min(width, x1 + max(16, int(width * float(b.get("w", 0.88)))))
        y2 = min(height, y1 + max(16, int(height * float(b.get("h", 0.16)))))
        full_mask[y1:y2, x1:x2] = 255

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
    full_mask = cv2.dilate(full_mask, kernel, iterations=1)
    ys, xs = np.nonzero(full_mask)
    if ys.size == 0:
        cap.release()
        return False

    ctx_pad = max(32, int(0.08 * max(width, height)))
    rx1 = max(0, int(xs.min()) - ctx_pad)
    ry1 = max(0, int(ys.min()) - ctx_pad)
    rx2 = min(width, int(xs.max()) + ctx_pad)
    ry2 = min(height, int(ys.max()) + ctx_pad)
    rw, rh = rx2 - rx1, ry2 - ry1

    roi_mask = full_mask[ry1:ry2, rx1:rx2]
    mask_512 = (cv2.resize(roi_mask, (512, 512), interpolation=cv2.INTER_NEAREST) > 127).astype(np.float32)[
        None, None, :, :
    ]
    soft_alpha = (cv2.GaussianBlur(roi_mask.astype(np.float32) / 255.0, (11, 11), 0))[:, :, None]

    raw_avi = work_dir / f"_lama_{dst_mp4.stem}.avi"
    writer = cv2.VideoWriter(
        str(raw_avi),
        cv2.VideoWriter_fourcc(*"MJPG"),
        fps if 5.0 <= fps <= 120.0 else 30.0,
        (width, height),
    )
    if not writer.isOpened():
        cap.release()
        return False

    sess_opts = ort.SessionOptions()
    sess_opts.intra_op_num_threads = 4
    sess_opts.inter_op_num_threads = 1
    sess = ort.InferenceSession(
        str(onnx_path),
        sess_options=sess_opts,
        providers=["CPUExecutionProvider"],
    )

    last_patch_bgr: np.ndarray | None = None
    frame_idx = 0
    # Run ONNX every 3rd frame (10 Hz on 30fps video) and reuse smooth patch on intermediate frames for CPU speed
    key_step = 3

    try:
        while True:
            ok, frame_bgr = cap.read()
            if not ok or frame_bgr is None:
                break
            if last_patch_bgr is None or (frame_idx % key_step == 0):
                roi_bgr = frame_bgr[ry1:ry2, rx1:rx2]
                roi_rgb_512 = cv2.resize(cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2RGB), (512, 512), interpolation=cv2.INTER_AREA)
                inp_img = (roi_rgb_512.astype(np.float32) / 255.0).transpose(2, 0, 1)[None]
                # Carve/LaMa-ONNX takes image in [0, 1], mask in {0, 1}, and outputs RGB in [0, 255]
                out_512 = sess.run(None, {"image": inp_img, "mask": mask_512})[0][0]  # (3, 512, 512)
                out_rgb = np.clip(out_512.transpose(1, 2, 0), 0.0, 255.0).astype(np.uint8)
                last_patch_bgr = cv2.resize(
                    cv2.cvtColor(out_rgb, cv2.COLOR_RGB2BGR),
                    (rw, rh),
                    interpolation=cv2.INTER_LINEAR,
                )

            roi_cur = frame_bgr[ry1:ry2, rx1:rx2].astype(np.float32)
            blended = (soft_alpha * last_patch_bgr.astype(np.float32) + (1.0 - soft_alpha) * roi_cur).astype(np.uint8)
            frame_bgr[ry1:ry2, rx1:rx2] = blended
            writer.write(frame_bgr)
            frame_idx += 1
    finally:
        cap.release()
        writer.release()
        del sess
        gc.collect()

    if frame_idx == 0 or not raw_avi.is_file():
        raw_avi.unlink(missing_ok=True)
        return False

    run_ffmpeg(
        [
            "-i",
            str(raw_avi.resolve()),
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
            str(dst_mp4.resolve()),
        ],
        cwd=work_dir,
    )
    raw_avi.unlink(missing_ok=True)
    return dst_mp4.is_file()
