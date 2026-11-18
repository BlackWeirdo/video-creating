"""Static `.tsx` product-accuracy scanner (`BR-PRD-02`) and shell command allowlist (`FR-STD-07`, `FR-STD-10`)."""
from __future__ import annotations

import re
from pathlib import Path

# BR-PRD-02 patterns forbidden on product footage components in Remotion (.tsx / .ts)
CSS_FILTER_RE = re.compile(
    r"""(?:\bfilter\s*:\s*['"`]?[^'"`;\n{}]*(?:brightness|contrast|saturate|hue-rotate|sepia|grayscale|invert|blur)\s*\()""",
    re.IGNORECASE,
)
MIX_BLEND_RE = re.compile(
    r"""(?:\bmixBlendMode\s*:\s*['"`](?!normal['"`])\w+|mix-blend-mode\s*:\s*(?!normal\b)[a-z-]+)""",
    re.IGNORECASE,
)
OPACITY_LT_ONE_RE = re.compile(
    r"""\bopacity\s*[:=]\s*\{?\s*(?:0(?:\.\d+)?|\.\d+)\s*\}?(?![.\d])""",
    re.IGNORECASE,
)
PLAYBACK_RATE_NE_ONE_RE = re.compile(
    r"""\bplaybackRate\s*[:=]\s*\{?\s*(?!1(?:\.0+)?(?![.\d]))(\d+(?:\.\d+)?)\s*\}?""",
    re.IGNORECASE,
)
COLOR_OVERLAY_MARKER_RE = re.compile(
    r"""data-product-color-overlay|productColorOverlay""",
    re.IGNORECASE,
)
FORBIDDEN_AI_CALL_RE = re.compile(
    r"""\b(?:remake-run|capsule-cinema)\b""",
    re.IGNORECASE,
)
VIDEO_SRC_RE = re.compile(
    r"""staticFile\(\s*['"`]([^'"`]+\.(?:mp4|mov|webm))['"`]\s*\)""",
    re.IGNORECASE,
)


def scan_tsx_for_product_violations(tsx_source: str, filename: str = "Scene.tsx") -> list[str]:
    """Scans a Remotion `.tsx` / `.ts` source string for `BR-PRD-02` product accuracy violations.

    Returns a list of human-readable violation descriptions (empty if clean).
    """
    violations: list[str] = []

    if CSS_FILTER_RE.search(tsx_source):
        violations.append(
            f"{filename}: Forbidden CSS filter (brightness/contrast/saturate/hue-rotate/sepia/blur) on video component (BR-PRD-02)"
        )
    if MIX_BLEND_RE.search(tsx_source):
        violations.append(
            f"{filename}: Forbidden mix-blend-mode / mixBlendMode on video component (BR-PRD-02)"
        )
    if OPACITY_LT_ONE_RE.search(tsx_source):
        violations.append(
            f"{filename}: Forbidden opacity < 1 on product footage component (BR-PRD-02)"
        )
    if PLAYBACK_RATE_NE_ONE_RE.search(tsx_source):
        violations.append(
            f"{filename}: Forbidden playbackRate != 1 on product footage component (BR-PRD-02)"
        )
    if COLOR_OVERLAY_MARKER_RE.search(tsx_source):
        violations.append(
            f"{filename}: Forbidden color overlay over product footage component (BR-PRD-02)"
        )
    if FORBIDDEN_AI_CALL_RE.search(tsx_source):
        violations.append(
            f"{filename}: Forbidden paid AI video generation reference (remake-run / capsule-cinema) (FR-STD-10)"
        )

    return violations


RAW_VIDEO_TAG_RE = re.compile(r"\b(?:OffthreadVideo|Html5Video|Video)\b|<video\b")
MEDIA_LITERAL_RE = re.compile(r"""['"`]([^'"`\s]+\.(?:mp4|mov|webm|mkv))['"`]""", re.IGNORECASE)
IMPORT_FROM_RE = re.compile(r"""\bfrom\s+['"]([^'"]+)['"]|\brequire\(\s*['"]([^'"]+)['"]\s*\)""")
DYNAMIC_EXEC_OR_NET_RE = re.compile(
    r"""\b(?:import|eval|Function)\s*\(|\b(?:fetch|XMLHttpRequest|WebSocket|EventSource)\b"""
)
SCENE_ALLOWED_IMPORTS: frozenset[str] = frozenset({"react", "remotion", "./lib", "./plan"})
LITERAL_SHOT_PROP_RE = re.compile(r"""\b(?:startS|file)\s*=\s*(?:\{\s*[\d.'"`]|['"])""")


def scan_scene_contract(scene_source: str) -> list[str]:
    """Checks the agent-written `Scene.tsx` against the Studio contract.

    Footage may only appear through the app's `ProductShot` (full frame, untouched) and only with
    the file and time range of a scene in the app-checked `./plan`, so the scene must not use a raw
    video element, other modules, a file name or a hard-coded time.
    """
    problems: list[str] = []
    if RAW_VIDEO_TAG_RE.search(scene_source):
        problems.append("Scene.tsx: dùng thẻ video trực tiếp; hình sản phẩm chỉ được hiện qua ProductShot của './lib' (BR-PRD-02)")
    if DYNAMIC_EXEC_OR_NET_RE.search(scene_source):
        problems.append("Scene.tsx: không được gọi dynamic import/eval hoặc kết nối mạng (fetch/WebSocket) (FR-STD-10)")
    imported: set[str] = set()
    for match in IMPORT_FROM_RE.finditer(scene_source):
        module = match.group(1) or match.group(2)
        imported.add(module)
        if module not in SCENE_ALLOWED_IMPORTS:
            problems.append(f"Scene.tsx: import '{module}' không được phép (chỉ react, remotion, ./lib, ./plan)")
    if "./plan" not in imported:
        problems.append("Scene.tsx: phải lấy các cảnh từ `PLAN` của './plan'")
    for match in MEDIA_LITERAL_RE.finditer(scene_source):
        problems.append(f"Scene.tsx: ghi cứng tên file '{match.group(1)}'; file phải lấy từ PLAN.scenes")
    if LITERAL_SHOT_PROP_RE.search(scene_source):
        problems.append("Scene.tsx: `file` và `startS` của ProductShot phải lấy từ PLAN.scenes, không ghi cứng")
    if not re.search(r"\bexport\s+const\s+Scene\b", scene_source):
        problems.append("Scene.tsx: thiếu `export const Scene`")
    return problems


def _unapproved_video_refs(src: str, rel_name: str, allowed_video_filenames: set[str]) -> list[str]:
    """Video files referenced by the source that are not in the approved shot library."""
    violations: list[str] = []
    for match in VIDEO_SRC_RE.finditer(src):
        ref_file = Path(match.group(1)).name
        if ref_file not in allowed_video_filenames:
            violations.append(
                f"{rel_name}: Video file '{ref_file}' is not in the approved shot library ({sorted(allowed_video_filenames)})"
            )
    return violations


def check_studio_project_dir(
    project_dir: Path,
    *,
    allowed_video_filenames: set[str] | None = None,
) -> list[str]:
    """Scans all `.tsx` / `.ts` files in `project_dir` for `BR-PRD-02` violations and unauthorized video sources."""
    if not project_dir.exists():
        return [f"Project directory does not exist: {project_dir}"]

    all_violations: list[str] = []
    tsx_files = sorted(
        list(project_dir.rglob("*.tsx")) + list(project_dir.rglob("*.ts"))
    )
    if not tsx_files:
        return ["No .tsx or .ts files found in Studio project directory"]

    for fpath in tsx_files:
        if "node_modules" in fpath.parts:
            continue
        src = fpath.read_text(encoding="utf-8", errors="replace")
        rel_name = str(fpath.relative_to(project_dir))
        all_violations.extend(scan_tsx_for_product_violations(src, filename=rel_name))

        if allowed_video_filenames is not None:
            all_violations.extend(_unapproved_video_refs(src, rel_name, allowed_video_filenames))

    return all_violations
