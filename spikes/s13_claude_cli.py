"""S13: `claude -p` on the owner's subscription login.

Usage:
  python s13_claude_cli.py writer
  python s13_claude_cli.py vision <thumb1.jpg> <thumb2.jpg> <thumb3.jpg>

Calls claude.exe directly with list arguments: the npm shims (claude.cmd /
claude.ps1) mangle the quotes inside --json-schema on Windows.
Runs in an empty temp dir so no project CLAUDE.md, hooks or .mcp.json load.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

WRITER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["formula", "title", "shots", "caption"],
    "properties": {
        "formula": {"type": "string"},
        "title": {"type": "string"},
        "shots": {
            "type": "array",
            "minItems": 3,
            "maxItems": 6,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["shot_id", "duration_s", "text"],
                "properties": {
                    "shot_id": {"type": "integer"},
                    "duration_s": {"type": "number"},
                    "text": {"type": "string"},
                },
            },
        },
        "caption": {
            "type": "object",
            "additionalProperties": False,
            "required": ["text", "hashtags"],
            "properties": {
                "text": {"type": "string"},
                "hashtags": {"type": "array", "items": {"type": "string"}},
            },
        },
    },
}

WRITER_PROMPT = """Viết kịch bản video dọc 15-20 giây cho một thương hiệu trang sức bạc thủ công, bằng tiếng Việt.
Chỉ được dùng các shot sau (shot_id: mô tả, độ dài tối đa):
1: cận cảnh bàn tay thợ đang giũa mặt nhẫn, 4.0s
2: nhẫn bạc đặt trên mặt gỗ, ánh sáng tự nhiên, 3.5s
3: thợ hàn điểm nối bằng mỏ hàn nhỏ, 5.0s
4: nhẫn đeo trên ngón tay, xoay nhẹ, 4.5s
5: đánh bóng nhẫn bằng vải, 3.0s
Dữ liệu sản phẩm: KHÔNG CÓ. Vì vậy không được viết chất liệu, tuổi bạc, đá, kích thước, giá; chỉ viết về cảm xúc và quy trình.
Mỗi shot một dòng phụ đề ngắn (tối đa 8 từ). Kèm caption Instagram và 3-5 hashtag."""

VISION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["shots"],
    "properties": {
        "shots": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["file", "description", "tags", "has_product", "quality"],
                "properties": {
                    "file": {"type": "string"},
                    "description": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "has_product": {"type": "boolean"},
                    "quality": {"type": "integer", "minimum": 1, "maximum": 5},
                },
            },
        }
    },
}


def find_claude_exe() -> str:
    shim = shutil.which("claude")
    if not shim:
        sys.exit("claude not found on PATH")
    exe = Path(shim).parent / "node_modules/@anthropic-ai/claude-code/bin/claude.exe"
    return str(exe) if exe.exists() else shim


def run(prompt: str, schema: dict, workdir: Path, extra: list[str]) -> None:
    cmd = [
        find_claude_exe(), "-p",
        "--model", "sonnet",
        "--output-format", "json",
        "--json-schema", json.dumps(schema),
        "--permission-mode", "dontAsk",
        *extra,
    ]
    started = time.monotonic()
    proc = subprocess.run(
        cmd, input=prompt, capture_output=True, text=True, encoding="utf-8",
        cwd=workdir, timeout=300,
    )
    elapsed = time.monotonic() - started
    print(f"exit code : {proc.returncode}")
    print(f"seconds   : {elapsed:.1f}")
    if proc.stderr.strip():
        print(f"stderr    : {proc.stderr.strip()[:500]}")
    try:
        result = json.loads(proc.stdout)
    except json.JSONDecodeError:
        print(f"stdout (not JSON): {proc.stdout[:800]}")
        return
    usage = result.get("usage", {})
    print(f"is_error  : {result.get('is_error')}  subtype: {result.get('subtype')}  turns: {result.get('num_turns')}")
    print(f"cost est. : {result.get('total_cost_usd')} USD (client-side estimate)")
    print(f"usage     : in={usage.get('input_tokens')} out={usage.get('output_tokens')} "
          f"cache_read={usage.get('cache_read_input_tokens')} cache_create={usage.get('cache_creation_input_tokens')}")
    print(f"models    : {', '.join(result.get('modelUsage', {}))}")
    print(f"top keys  : {', '.join(result)}")
    if result.get("permission_denials"):
        print(f"denials   : {json.dumps(result['permission_denials'], ensure_ascii=False)[:400]}")
    print("--- structured_output ---")
    print(json.dumps(result.get("structured_output"), ensure_ascii=False, indent=2))
    if "structured_output" not in result:
        print("--- result ---")
        print(str(result.get("result"))[:800])


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    mode = sys.argv[1] if len(sys.argv) > 1 else "writer"
    workdir = Path(tempfile.mkdtemp(prefix="s13-"))
    try:
        if mode == "writer":
            run(WRITER_PROMPT, WRITER_SCHEMA, workdir, [])
        elif mode == "vision":
            names = []
            for src in sys.argv[2:]:
                shutil.copy(src, workdir / Path(src).name)
                names.append(Path(src).name)
            prompt = (
                "Đọc từng ảnh trong thư mục hiện tại: " + ", ".join(names) + ". "
                "Mỗi ảnh là khung giữa của một shot footage trang sức. Với mỗi ảnh, mô tả ngắn bằng tiếng Việt "
                "những gì THẤY được (không suy đoán chất liệu), gắn 2-5 thẻ, cho biết có sản phẩm trang sức "
                "trong khung không, và chấm chất lượng hình 1-5."
            )
            run(prompt, VISION_SCHEMA, workdir, ["--allowedTools", "Read"])
        else:
            sys.exit(f"unknown mode: {mode}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
