"""S13: Antigravity CLI (`agy -p`) on the owner's Google AI subscription login.

Usage:
  python s13_agy_cli.py writer [model]
  python s13_agy_cli.py video <clip.mp4> [model]

`agy -p` takes the prompt attached to the flag (-p=...), not from stdin.
Runs in an empty temp dir with --sandbox so the agent only sees files we copy in.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from s13_claude_cli import VISION_SCHEMA, WRITER_PROMPT, WRITER_SCHEMA

AGY = Path(os.environ["LOCALAPPDATA"]) / "agy/bin/agy.exe"
DEFAULT_MODEL = "gemini-3.8-flash-medium"


def run(prompt: str, schema: dict, workdir: Path, model: str) -> None:
    cmd = [
        str(AGY), f"-p={prompt}",
        "--model", model,
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--sandbox",
        "--print-timeout", "240s",
    ]
    started = time.monotonic()
    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
        cwd=workdir, timeout=300, stdin=subprocess.DEVNULL,
    )
    print(f"model     : {model}")
    print(f"exit code : {proc.returncode}")
    print(f"seconds   : {time.monotonic() - started:.1f}")
    if proc.stderr.strip():
        print(f"stderr    : {proc.stderr.strip()[:1500]}")
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(f"stdout (not JSON): {proc.stdout[:1500]}")
        return
    if isinstance(result, dict):
        print(f"top keys  : {', '.join(result)}")
    print("--- output ---")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:4000])


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    mode = sys.argv[1] if len(sys.argv) > 1 else "writer"
    workdir = Path(tempfile.mkdtemp(prefix="s13-agy-"))
    try:
        if mode == "writer":
            model = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_MODEL
            run(WRITER_PROMPT, WRITER_SCHEMA, workdir, model)
        elif mode == "video":
            src = Path(sys.argv[2])
            model = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_MODEL
            shutil.copy(src, workdir / "clip.mp4")
            prompt = (
                "Xem file video clip.mp4 trong thư mục hiện tại (xem trực tiếp video, không chạy lệnh trích khung hình). "
                "Chia video thành các shot theo điểm cắt hoặc thay đổi cảnh rõ rệt. Với mỗi shot: đặt file = "
                "'clip.mp4@<giây bắt đầu>-<giây kết thúc>', mô tả ngắn bằng tiếng Việt những gì THẤY được, "
                "gắn 2-5 thẻ, cho biết có sản phẩm trang sức không, chấm chất lượng hình 1-5. "
                "Nếu không xem được video trực tiếp thì trả shots rỗng."
            )
            run(prompt, VISION_SCHEMA, workdir, model)
        else:
            sys.exit(f"unknown mode: {mode}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
