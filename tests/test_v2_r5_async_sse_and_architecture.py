"""Stage R5 tests: Async `sync: false` SSE job progress, `assembly.py` zero `_private` imports, package splits & ESLint."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.db import get_conn
from videocreator.job_store import update_job_progress
from videocreator.jobs import JobWorker
from videocreator.paths import (
    REPO_ROOT,
    find_ffmpeg_binary,
    find_node_runtime,
    find_python_runtime,
    find_uv_binary,
    find_yt_dlp_command,
    get_paths,
    is_port_available,
    pick_available_port,
)
from videocreator.pipeline.ffmpeg import run_ffmpeg

pytestmark = pytest.mark.local


def test_zero_cross_module_private_imports_in_src() -> None:
    """AST scan: `src/videocreator` must use absolute imports and have zero cross-module `_private` imports or exports."""
    src_root = REPO_ROOT / "src" / "videocreator"
    violations: list[str] = []
    for py_file in sorted(src_root.rglob("*.py")):
        rel = py_file.relative_to(REPO_ROOT).as_posix()
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    violations.append(
                        f"{rel}:{node.lineno} uses relative import (level={node.level}); use absolute `from videocreator...`"
                    )
                if (node.module and node.module.startswith("videocreator")) or (
                    node.level and node.level > 0
                ):
                    priv_names = [
                        alias.name
                        for alias in node.names
                        if (alias.name.startswith("_") and alias.name != "__version__")
                        or (
                            alias.asname
                            and alias.asname.startswith("_")
                            and not py_file.name.startswith("_")
                            and py_file.name == "__init__.py"
                        )
                    ]
                    if priv_names:
                        violations.append(
                            f"{rel}:{node.lineno} imports private {priv_names} from {node.module or '.' * node.level}"
                        )
            elif isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if (
                        isinstance(tgt, ast.Name)
                        and tgt.id == "__all__"
                        and isinstance(node.value, (ast.List, ast.Tuple))
                    ):
                        priv_exports = [
                            elt.value
                            for elt in node.value.elts
                            if isinstance(elt, ast.Constant)
                            and isinstance(elt.value, str)
                            and elt.value.startswith("_")
                            and elt.value != "__version__"
                        ]
                        if priv_exports:
                            violations.append(
                                f"{rel}:{node.lineno} exports private names in __all__: {priv_exports}"
                            )
    assert violations == [], "Architecture import violations found:\n" + "\n".join(violations)


def test_localize_and_autopilot_split_into_modular_packages() -> None:
    """`pipeline/localize/` and `autopilot/` must be clean multi-module packages with no monolithic file."""
    loc_pkg = REPO_ROOT / "src" / "videocreator" / "pipeline" / "localize"
    auto_pkg = REPO_ROOT / "src" / "videocreator" / "autopilot"
    assert not (REPO_ROOT / "src" / "videocreator" / "pipeline" / "localize.py").exists()
    assert not (REPO_ROOT / "src" / "videocreator" / "autopilot.py").exists()

    for expected in (
        "__init__.py",
        "project.py",
        "extract.py",
        "translate.py",
        "voice.py",
        "segments.py",
        "render.py",
    ):
        mod_file = loc_pkg / expected
        assert mod_file.is_file(), f"Missing localize submodule: {expected}"
        line_count = len(mod_file.read_text(encoding="utf-8").splitlines())
        assert line_count < 600, f"{expected} too large ({line_count} lines)"

    for expected in ("__init__.py", "sources.py", "rules.py"):
        mod_file = auto_pkg / expected
        assert mod_file.is_file(), f"Missing autopilot submodule: {expected}"


def test_web_next_uses_async_sync_false_sse_banner_and_real_eslint() -> None:
    """All Next.js UI pages must avoid `sync: true` and `web-next` must configure real ESLint."""
    web_src = REPO_ROOT / "web-next" / "src"
    sync_true_hits: list[str] = []
    for ts_file in sorted(web_src.rglob("*.ts*")):
        txt = ts_file.read_text(encoding="utf-8")
        if "sync: true" in txt or '"sync": true' in txt:
            sync_true_hits.append(ts_file.relative_to(REPO_ROOT).as_posix())
    assert sync_true_hits == [], f"Found blocking `sync: true` in UI files: {sync_true_hits}"

    app_shell = (web_src / "components" / "AppShell.tsx").read_text(encoding="utf-8")
    assert "vc:queue-snapshot" in app_shell
    assert (web_src / "components" / "JobProgressBanner.tsx").is_file()

    pkg_json = json.loads((REPO_ROOT / "web-next" / "package.json").read_text(encoding="utf-8"))
    assert "eslint" in pkg_json["scripts"]["lint"]
    assert "eslint" in pkg_json.get("devDependencies", {})
    assert (REPO_ROOT / "web-next" / "eslint.config.mjs").is_file()


def test_consolidated_runtime_and_port_discovery_in_paths() -> None:
    """`videocreator.paths` consolidates FFmpeg, Node, Python, uv, yt-dlp, and TCP port discovery."""
    assert Path(find_ffmpeg_binary("ffmpeg")).name.lower().startswith("ffmpeg")
    assert find_node_runtime() is not None
    assert Path(find_python_runtime()).is_file()
    ytdlp_cmd = find_yt_dlp_command()
    assert isinstance(ytdlp_cmd, list) and len(ytdlp_cmd) >= 1
    _ = find_uv_binary()
    chosen_port = pick_available_port("127.0.0.1", 39810)
    assert is_port_available("127.0.0.1", chosen_port) is True


def test_async_novel_and_editor_renders_emit_step_progress_and_sse_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`sync: false` enqueues compute job, records per-chapter steps, and streams `done` over `/api/v1/events`."""
    paths = get_paths(tmp_path / "data")
    paths.config_file.write_text('[voice]\nvi_provider = "test_tone"\n', encoding="utf-8")

    recorded_steps: list[tuple[float, str]] = []
    orig_update = update_job_progress

    def _spy_progress(db_file: Path, job_id: int, *, progress: float, step: str = "") -> None:
        recorded_steps.append((round(float(progress), 3), step))
        orig_update(db_file, job_id, progress=progress, step=step)

    monkeypatch.setattr("videocreator.job_store.update_job_progress", _spy_progress)

    app = create_app(paths.data_dir, start_worker=False)
    with TestClient(app) as client:
        # Create full_ai workspace
        ws_res = client.post(
            "/api/v1/workspaces",
            json={
                "name": "Async Studio WS",
                "niche": "story",
                "content_policy": "full_ai",
                "approval_mode": "single",
            },
        )
        assert ws_res.status_code in (200, 201)
        ws_id = int(ws_res.json()["workspace"]["id"])

        # 1. Async 2-chapter Novel render (`sync: false`)
        cr_nov = client.post(
            "/api/v1/novels/projects",
            json={
                "workspace_id": ws_id,
                "title": "Truyen Bat Dong Bo",
                "source_text": (
                    "Chương 1: Khởi hành\nĐoàn tàu rời ga lúc bình minh rực rỡ.\n\n"
                    "Chương 2: Đích đến\nThành phố biển hiện ra cuối chân trời xanh."
                ),
            },
        )
        assert cr_nov.status_code == 201
        nov_id = int(cr_nov.json()["project"]["id"])

        rn_nov = client.post(
            f"/api/v1/novels/projects/{nov_id}/render",
            json={"sync": False, "force": False},
        )
        assert rn_nov.status_code == 202
        nov_job_id = int(rn_nov.json()["job_id"])

        worker: JobWorker = app.state.worker
        assert worker.run_next_once(lane="compute") is True

        # Verify real per-chapter step messages were reported during worker execution
        chapter_steps = [s for _, s in recorded_steps if "Đang dựng chương" in s]
        assert any("1/2" in s for s in chapter_steps), recorded_steps
        assert any("2/2" in s for s in chapter_steps), recorded_steps

        # Verify SSE `/api/v1/events?once=true` streams the completed job snapshot
        sse_resp = client.get(f"/api/v1/events?once=true&workspace_id={ws_id}")
        assert sse_resp.status_code == 200
        assert "event: queue_snapshot" in sse_resp.text
        data_line = next(
            ln[len("data: ") :]
            for ln in sse_resp.text.splitlines()
            if ln.startswith("data: ")
        )
        snap = json.loads(data_line)
        matched_job = next(j for j in snap["recent_jobs"] if int(j["id"]) == nov_job_id)
        assert matched_job["status"] == "done"
        assert float(matched_job["progress"]) == 1.0

        nov_done = client.get(f"/api/v1/novels/projects/{nov_id}").json()["project"]
        assert nov_done["status"] == "completed"
        assert nov_done["ready_chapters"] == 2

        # 2. Async Timeline Editor render (`sync: false`)
        sample_clip = paths.footage_dir / "ed_async_clip.mp4"
        sample_clip.parent.mkdir(parents=True, exist_ok=True)
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "testsrc2=s=360x640:r=30:d=5.4",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=5.4",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                str(sample_clip),
            ]
        )
        with get_conn(paths.db_file) as conn:
            conn.execute(
                "INSERT INTO footage (workspace_id, path, sha256, orientation, width, height, duration_s) VALUES (?, 'footage/ed_async_clip.mp4', 'sha_ed_async_1', 'portrait', 360, 640, 5.4)",
                (ws_id,),
            )

        cr_ed = client.post(
            "/api/v1/editor/projects",
            json={
                "workspace_id": ws_id,
                "title": "Async Timeline",
                "tracks": {
                    "video_clips": [
                        {"source_path": "footage/ed_async_clip.mp4", "start_s": 0.0, "duration_s": 5.2}
                    ],
                    "audio_clips": [],
                    "subtitles": [{"start_s": 0.2, "end_s": 4.8, "text": "Timeline Async SSE"}],
                },
            },
        )
        assert cr_ed.status_code == 201
        ed_id = int(cr_ed.json()["project"]["id"])

        rn_ed = client.post(
            f"/api/v1/editor/projects/{ed_id}/render",
            json={"style_preset": "tiktok_karaoke", "sync": False},
        )
        assert rn_ed.status_code == 202
        assert int(rn_ed.json()["job_id"]) > 0

        assert worker.run_next_once(lane="compute") is True
        ed_done = client.get(f"/api/v1/editor/projects/{ed_id}").json()["project"]
        assert ed_done["status"] == "completed"
        assert ed_done["output_video_id"] is not None
