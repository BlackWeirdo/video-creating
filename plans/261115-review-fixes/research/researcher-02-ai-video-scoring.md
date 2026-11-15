# Research 02: AI video scoring (2026-11-15)

Saved by main agent from the researcher's returned report. [MEM] = from model memory, not verified this session (two doc URLs redirected and were not followed).

## 1. Frames for an image-only LLM (`claude -p`)
- KISS: one labeled contact sheet per video (single image, one Read call, model sees the whole arc). Optional extra full-res hook frame.
- Timestamps for 15–30s: hook 0.3s, 1.3s, 2.3s (avoid black first frame), then one frame per ~2s or one per shot; 8–12 cells total.
- Label cells with timestamps so the model can cite evidence.
- [MEM] Claude: long edge ~1568px resize threshold; tokens ≈ w*h/750 (~3.3k for 1568²); API allows many images/request. Verify: platform.claude.com/docs/en/build-with-claude/vision.
- Cell ~270x480, tile 4x3 → ~1080x1440 sheet.

## 2. FFmpeg
- Filters needed (whitelist): `fps`, `scale`, `select`, `tile`, `pad`; `drawtext` only if labels burned in (needs fontfile; app already ships Be Vietnam Pro).
- Single frame: `ffmpeg -ss 0.3 -i in.mp4 -frames:v 1 -q:v 3 f.jpg` (already how `pipeline/thumbs.extract_thumbnail` works).
- Simpler alternative avoiding new filters: extract N frames with existing `extract_thumbnail` (one ffmpeg call each, ~0.2s each on 20s clip) and pass them as separate thumbnails — no whitelist change, no escaping risk. Grid: `fps=1/2,scale=270:480:...,pad=...,tile=4x3 -frames:v 1`.
- Sources: https://ffmpeg.org/ffmpeg-filters.html, https://techearl.com/ffmpeg-contact-sheet-preview, https://www.baeldung.com/linux/generate-video-thumbnails-gallery

## 3. Gemini API video [MEM]
- Default 1 fps sampling; ~258 tokens/frame + ~32 tokens/s audio (~300 tok/s); `media_resolution` LOW ≈ 66 tok/frame.
- Inline ≤ ~20 MB/request; Files API ≤ 2 GB, kept 48h. Supports MM:SS references.
- 20s clip ≈ 6k input tokens → fractions of a cent on flash tier.
- Gemini needs no frame step; only Claude does.

## 4. LLM-as-judge reliability
- Rubric order/position bias; anchored rubrics + extractive evidence improve robustness (arxiv 2602.02219, 2601.08654); single-prompt multi-criterion works well, repeat-agreement = confidence (aclanthology 2026.aacl-long.207).
- Calibrate against 10–20 human-rated videos before gating (barkingiguana.com, non-peer-reviewed).
- Recommendations:
  - Anchored per-criterion rubric; evidence (timestamp + what is visible) before each score.
  - Measure deterministic things in code, not LLM: subtitle safe zone (already guaranteed by ASS margins), duration, black first frame.
  - Threshold 8/10 + auto-regenerate: noisy (±1 point). Better: cap attempts, keep BEST attempt not last, gate on per-criterion floor, pass concrete fix hint ("hook weak: product in 0–2s") to the regeneration.

## Unresolved
- Exact Claude image limits; does `claude -p` Read downscale images?
- Exact Gemini `media_resolution` SDK field and $ rates.
- No human-labeled calibration set exists in the repo.
