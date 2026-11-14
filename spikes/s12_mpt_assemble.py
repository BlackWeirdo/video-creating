"""S12: MoneyPrinterTurbo as an assembly engine (ordered local segments + our script + Vietnamese voice).

Prerequisite: MPT API running from tools/mpt (uv run --frozen python main.py). Usage:
  python s12_mpt_assemble.py [--base http://127.0.0.1:8080] [--script short|long]

Cuts 3 real segments (1080x1920, 30 fps, CRF 14) from tests/samples, drops them into
MPT's storage/local_videos, submits one task, then measures the result:
resolution, duration, where the cuts land (scene detection), audio stream.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MPT = REPO / "tools" / "mpt"
LOCAL_VIDEOS = MPT / "storage" / "local_videos"
OUT = REPO / "spikes" / "out" / "s12"

# (source clip, start second, duration): order matters, durations differ on purpose.
SEGMENTS = [
    ("clip2_6s.mp4", 0.5, 2.0),
    ("clip1_6s.mp4", 1.0, 3.5),
    ("clip2_6s.mp4", 3.0, 2.5),
]
SCRIPTS = {
    # ~8 s of footage. "short" is a voice-over shorter than the footage, "long" is longer.
    "short": "Từng đường giũa, từng chút kiên nhẫn. Đeo lên tay, mang theo cả tâm hồn.",
    "long": (
        "Từng đường giũa, từng chút kiên nhẫn. Ngọn lửa nhỏ nối liền hai đầu kim loại. "
        "Người thợ đánh bóng cho đến khi bề mặt sáng dịu. Một chiếc nhẫn ra đời từ đôi bàn tay. "
        "Đeo lên tay, mang theo cả tâm hồn của người làm ra nó."
    ),
}


def run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        sys.exit(f"command failed: {' '.join(cmd)}\n{proc.stderr[-800:]}")
    return proc.stdout + proc.stderr


def api(base: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        sys.exit(f"HTTP {exc.code} from {path}: {exc.read().decode('utf-8', 'replace')[:1500]}")


def probe(path: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)])
    return json.loads(out)


def scene_cuts(path: Path) -> list[float]:
    out = run(["ffmpeg", "-hide_banner", "-i", str(path), "-vf", "select='gt(scene,0.25)',showinfo", "-an", "-f", "null", "-"])
    return [round(float(line.split("pts_time:")[1].split()[0]), 2) for line in out.splitlines() if "pts_time:" in line]


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8080")
    parser.add_argument("--script", choices=list(SCRIPTS), default="short")
    args = parser.parse_args()

    LOCAL_VIDEOS.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    names = []
    for idx, (src, start, dur) in enumerate(SEGMENTS, start=1):
        name = f"s12_seg_{idx:02d}.mp4"
        run(["ffmpeg", "-hide_banner", "-y", "-ss", str(start), "-i", str(REPO / "tests" / "samples" / src),
             "-t", str(dur), "-vf", "scale=1080:1920,fps=30", "-c:v", "libx264", "-crf", "14",
             "-pix_fmt", "yuv420p", "-an", str(LOCAL_VIDEOS / name)])
        names.append(name)
    total = sum(d for _, _, d in SEGMENTS)
    print(f"segments  : {[d for _, _, d in SEGMENTS]} s, total {total} s, expected cuts at "
          f"{[round(sum(d for _, _, d in SEGMENTS[:i]), 2) for i in range(1, len(SEGMENTS))]}")

    payload = {
        "video_subject": "s12 spike",
        "video_script": SCRIPTS[args.script],
        "video_terms": [],
        "video_aspect": "9:16",
        "video_concat_mode": "sequential",
        "video_transition_mode": None,
        "video_clip_duration": 15,
        "video_clip_speed": 1.0,
        "video_count": 1,
        "video_source": "local",
        "video_materials": [{"provider": "local", "url": n, "duration": 0} for n in names],
        "video_language": "vi-VN",
        "voice_name": "vi-VN-HoaiMyNeural-Female",
        "voice_rate": 1.0,
        "bgm_type": "",
        "subtitle_enabled": True,
        "subtitle_position": "custom",
        "custom_position": 70.0,
        "font_name": "BeVietnamPro-Bold.ttf",
        "font_size": 56,
        "stroke_width": 2.0,
    }
    started = time.monotonic()
    task_id = api(args.base, "/api/v1/videos", payload)["data"]["task_id"]
    print(f"task      : {task_id}")
    while True:
        time.sleep(3)
        task = api(args.base, f"/api/v1/tasks/{task_id}")["data"]
        state, progress = task.get("state"), task.get("progress")
        if state in (1, -1) or time.monotonic() - started > 900:
            break
    elapsed = time.monotonic() - started
    print(f"state     : {state} progress={progress} seconds={elapsed:.0f}")
    print(f"task keys : {sorted(task)}")
    if state != 1:
        print(json.dumps(task, ensure_ascii=False, indent=2)[:2000])
        sys.exit(1)

    task_dir = MPT / "storage" / "tasks" / task_id
    print(f"task files: {sorted(p.name for p in task_dir.iterdir())}")
    final = sorted(task_dir.glob("final-*.mp4"))[0]
    info = probe(final)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    print(f"final     : {final.name} {video['width']}x{video['height']} {video['r_frame_rate']} fps "
          f"{video['codec_name']} {video.get('pix_fmt')} duration={float(info['format']['duration']):.2f}s")
    print(f"audio     : {audio['codec_name']} {audio['sample_rate']} Hz ch={audio['channels']}" if audio else "audio     : NONE")
    for wav in task_dir.glob("audio.*"):
        print(f"voice     : {wav.name} {float(probe(wav)['format']['duration']):.2f}s")
    print(f"cuts found: {scene_cuts(final)}")
    for srt in task_dir.glob("*.srt"):
        print(f"--- {srt.name} ---\n{srt.read_text(encoding='utf-8')[:700]}")
    copy = OUT / f"final_{args.script}.mp4"
    copy.write_bytes(final.read_bytes())
    for i, t in enumerate((1.0, total / 2, total - 0.5), start=1):
        run(["ffmpeg", "-hide_banner", "-y", "-ss", str(t), "-i", str(copy), "-frames:v", "1", "-update", "1",
             str(OUT / f"final_{args.script}_frame{i}.png")])
    print(f"saved     : {copy}")


if __name__ == "__main__":
    main()
