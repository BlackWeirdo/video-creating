"""Local tests for Studio: `.tsx` BR-PRD-02 scanner, script check, queued job flow, template render (Phase 17)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from videocreator.db import get_conn, migrate, query_one
from videocreator.jobs import JobRegistry, JobWorker
from videocreator.paths import get_paths
from videocreator.pipeline.ffmpeg import probe_video, run_ffmpeg
from videocreator.pipeline.planner import FactCheckResult
from videocreator.studio.agent import run_studio_job
from videocreator.studio.checks import (
    scan_scene_contract,
    scan_tsx_for_product_violations,
    validate_shell_command_allowed,
)
from videocreator.studio.plan import validate_plan
from videocreator.studio.session import (
    STUDIO_JOB_KIND,
    StudioBusyError,
    confirm_studio_plan,
    create_studio_session,
    enqueue_studio_job,
    recover_stuck_studio_sessions,
    request_studio_revision,
)
from videocreator.studio.templates import save_studio_template, start_render_from_template

STUDIO_SAMPLES_DIR = Path(__file__).parent / "samples" / "studio"
SAMPLE_CLIP_1 = Path(__file__).parent / "samples" / "clip1_6s.mp4"


@pytest.mark.local
def test_tsx_scanner_catches_all_br_prd_02_violations() -> None:
    clean_src = (STUDIO_SAMPLES_DIR / "CleanProductScene.tsx").read_text(encoding="utf-8")
    assert scan_tsx_for_product_violations(clean_src, "CleanProductScene.tsx") == []

    dirty_src = (STUDIO_SAMPLES_DIR / "DirtyProductScene.tsx").read_text(encoding="utf-8")
    violations = scan_tsx_for_product_violations(dirty_src, "DirtyProductScene.tsx")
    assert len(violations) == 4
    joined = "\n".join(violations)
    assert "CSS filter" in joined
    assert "mix-blend-mode" in joined
    assert "opacity < 1" in joined
    assert "playbackRate != 1" in joined


@pytest.mark.local
def test_studio_shell_command_allowlist_enforces_fr_std_10() -> None:
    assert validate_shell_command_allowed("rea-video decompose ref.mp4") is True
    assert validate_shell_command_allowed("npx remotion render src/index.ts Main out.mp4") is True
    assert validate_shell_command_allowed("npm ci") is True
    assert validate_shell_command_allowed("ffmpeg -i in.mp4 out.mp4") is True

    # Forbidden paid AI video generation or network/destructive commands
    assert validate_shell_command_allowed("rea-video remake-run ref.mp4") is False
    assert validate_shell_command_allowed("curl https://evil.example.com") is False
    assert validate_shell_command_allowed("npx remotion render && curl http://x") is False
    assert validate_shell_command_allowed("rm -rf /") is False


BRIEF: dict[str, Any] = {
    "shots": [
        {"shot_id": 1, "file": "footage_1.mp4", "start_s": 0.0, "end_s": 3.0, "product_ids": [7]},
        {"shot_id": 2, "file": "footage_1.mp4", "start_s": 3.0, "end_s": 6.0, "product_ids": []},
    ],
    "products": [
        {"id": 7, "name": "Nhẫn Lá Sen", "material": "bạc", "facts": {}},
        {"id": 8, "name": "Vòng Mây", "material": "bạc", "facts": {}},
    ],
}


@pytest.mark.local
def test_studio_plan_validation_checks_shot_ranges_and_product_names() -> None:
    scenes, problems = validate_plan(
        {
            "scenes": [
                {"shot_id": 1, "start_s": 0.5, "duration_s": 2.0, "text": "Nhẫn Lá Sen làm bằng tay"},
                {"shot_id": 2, "start_s": 3.0, "duration_s": 1.5, "text": ""},
            ]
        },
        BRIEF,
    )
    assert problems == []
    assert [(s["from_frame"], s["duration_frames"], s["file"]) for s in scenes] == [
        (0, 60, "footage_1.mp4"),
        (60, 45, "footage_1.mp4"),
    ]

    _, problems = validate_plan(
        {
            "scenes": [
                # runs past the end of the shot and names a product that is not in it
                {"shot_id": 1, "start_s": 2.0, "duration_s": 2.0, "text": "Vòng Mây tinh xảo"},
                {"shot_id": 9, "start_s": 0.0, "duration_s": 2.0, "text": ""},  # unknown shot
                {"shot_id": 2, "start_s": 3.0, "duration_s": 0.3, "text": ""},  # too short
            ]
        },
        BRIEF,
    )
    joined = "\n".join(problems)
    assert "nằm ngoài shot 1" in joined
    assert "Vòng Mây" in joined
    assert "shot_id=9" in joined
    assert "ngắn hơn" in joined


@pytest.mark.local
def test_scene_contract_requires_plan_driven_product_shots() -> None:
    good = (STUDIO_SAMPLES_DIR / "GoodScene.tsx").read_text(encoding="utf-8")
    assert scan_scene_contract(good) == []

    bad = "\n".join(scan_scene_contract((STUDIO_SAMPLES_DIR / "BadScene.tsx").read_text(encoding="utf-8")))
    assert "thẻ video trực tiếp" in bad
    assert "stock_gold_ring.mp4" in bad
    assert "./plan" in bad

    hard_coded = good.replace("startS={scene.startS}", "startS={1.5}")
    assert any("ghi cứng" in p for p in scan_scene_contract(hard_coded))


class _NoClaimsChecker:
    """Stand-in for the fact-check AI role only (no AI call in local tests)."""

    def generate_json(self, prompt: str, schema: type[FactCheckResult]) -> FactCheckResult:
        return schema(unverified_claims=[])


@pytest.mark.local
def test_studio_job_flow_confirmation_stop_repair_and_template_render(tmp_path: Path) -> None:
    if shutil.which("node") is None:
        pytest.skip("Node.js is required for the Studio Remotion render")
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    rel_ftg = "footage/clip1_6s.mp4"
    abs_ftg = paths.media_dir / rel_ftg
    abs_ftg.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SAMPLE_CLIP_1, abs_ftg)
    rel_sfx = "assets/tick.wav"
    (paths.media_dir / "assets").mkdir(parents=True, exist_ok=True)
    run_ffmpeg(["-f", "lavfi", "-i", "sine=frequency=880:duration=0.2", str(paths.media_dir / rel_sfx)])

    with get_conn(paths.db_file) as conn:
        conn.execute(
            """
            INSERT INTO footage (id, path, sha256, duration_s, width, height, orientation, status)
            VALUES (1, ?, 'sha_studio_1', 6.0, 1080, 1920, 'portrait', 'analysed')
            """,
            (rel_ftg,),
        )
        conn.execute(
            """
            INSERT INTO shots (id, footage_id, idx, start_s, end_s, description, tags_json, has_product, quality)
            VALUES (1, 1, 1, 0.0, 3.0, 'Cận cảnh nhẫn bạc', '["product"]', 1, 5),
                   (2, 1, 2, 3.0, 6.0, 'Nhẫn bạc trên nền xám', '["product"]', 1, 4)
            """
        )
        conn.execute("INSERT INTO assets (id, kind, path, duration_s) VALUES (1, 'sfx', ?, 0.2)", (rel_sfx,))

    # Stand-in for the agent only: it writes the files the real agent would write. Everything else is
    # real: job queue, script check, contract scan, Remotion render, audio mix, master export, preflight.
    good_src = (STUDIO_SAMPLES_DIR / "GoodScene.tsx").read_text(encoding="utf-8")
    bad_src = (STUDIO_SAMPLES_DIR / "BadScene.tsx").read_text(encoding="utf-8")
    seen: list[str] = []

    def _agent(proj_dir: Path, prompt: str, attempt: int, resume_ref: str | None) -> tuple[str, float]:
        if "viết kịch bản vào `plan.json`" in prompt:
            if "<sua>" in prompt:
                seen.append("replan")
                scenes = [
                    {"shot_id": 2, "start_s": 3.0, "duration_s": 2.0, "text": "Làm bằng tay"},
                    {"shot_id": 1, "start_s": 0.0, "duration_s": 2.0, "text": "Từng chiếc một"},
                ]
            elif attempt == 1:
                seen.append("plan_bad")  # runs past the end of shot 1
                scenes = [{"shot_id": 1, "start_s": 2.0, "duration_s": 3.0, "text": "Mở đầu"}]
            else:
                seen.append("plan_fixed")
                assert "nằm ngoài shot 1" in prompt
                scenes = [
                    {"shot_id": 1, "start_s": 0.0, "duration_s": 2.0, "text": "Mở đầu"},
                    {"shot_id": 2, "start_s": 3.0, "duration_s": 2.0, "text": "Kết"},
                ]
            (proj_dir / "plan.json").write_text(
                json.dumps({"title": "Nhẫn bạc", "scenes": scenes}, ensure_ascii=False), encoding="utf-8"
            )
        else:
            seen.append(f"scene_{attempt}")
            if attempt == 2:
                assert "stock_gold_ring.mp4" in prompt
            (proj_dir / "src" / "Scene.tsx").write_text(bad_src if attempt == 1 else good_src, encoding="utf-8")
        return "sess_ref_abc", 0.0

    registry = JobRegistry()
    registry.register(
        STUDIO_JOB_KIND,
        lambda ref_id: str(
            run_studio_job(paths, int(ref_id or 0), code_generator=_agent, checker_provider=_NoClaimsChecker()).get("status")
        ),
    )
    worker = JobWorker(paths.db_file, registry=registry)

    def _session(sid: int) -> dict[str, Any]:
        row = query_one(paths.db_file, "SELECT * FROM studio_sessions WHERE id = ?", (sid,))
        assert row is not None
        return row

    s1 = create_studio_session(paths, prompt="Dựng mở đầu cận cảnh nhẫn bạc", options={"sfx_asset_id": 1})
    enqueue_studio_job(paths.db_file, s1)
    # FR-STD-13: a second session cannot start while s1 is queued or running.
    with pytest.raises(StudioBusyError):
        create_studio_session(paths, prompt="Phiên thứ 2")

    # FR-STD-05: the job stops after the script; the bad first script was sent back once.
    assert worker.run_next_once() is True
    assert seen == ["plan_bad", "plan_fixed"]
    assert _session(s1)["status"] == "awaiting_confirm", _session(s1)["error"]
    video_id = int(_session(s1)["video_id"])
    plan = json.loads(query_one(paths.db_file, "SELECT plan_json FROM videos WHERE id = ?", (video_id,))["plan_json"])
    assert [s["shot_id"] for s in plan["shots"]] == [1, 2]

    # The user asks for a change to the script: it is re-planned and waits for confirmation again.
    request_studio_revision(paths, s1, "Đảo thứ tự hai cảnh")
    assert worker.run_next_once() is True
    assert seen[-1] == "replan"
    assert _session(s1)["status"] == "awaiting_confirm"

    # Confirm: scene code is written, the BR-PRD-02 violation is sent back once, then rendered (FR-STD-07).
    confirm_studio_plan(paths, s1)
    assert worker.run_next_once() is True
    assert seen[-2:] == ["scene_1", "scene_2"]
    sess_row = _session(s1)
    assert sess_row["status"] == "done", sess_row["error"]
    assert (paths.media_dir / "studio" / str(s1) / "out" / "v1.mp4").exists()
    studio_video = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (video_id,))
    assert studio_video["status"] == "pending_approval"
    assert studio_video["engine"] == "studio"
    assert [s["shot_id"] for s in json.loads(studio_video["plan_json"])["shots"]] == [2, 1]
    master = probe_video(paths.media_dir / str(studio_video["output_path"]))
    assert (master.width, master.height) == (1080, 1920)
    assert master.has_audio
    assert abs(master.duration_s - 4.0) < 0.2
    # FR-STD-06: the cut-point sound effect was mixed into a track for this version.
    assert (paths.media_dir / "studio" / str(s1) / "out" / "v1.audio.wav").exists()

    # FR-STD-09: save the scene as a template, then render new shots and text from it with no agent call.
    tpl_id = save_studio_template(paths, s1, name="Mẫu Nhẫn Bạc Tối Giản")
    calls_before = len(seen)
    s2 = start_render_from_template(
        paths, tpl_id, shot_ids=[1], subtitles=["Chế tác thủ công"], title="Video từ mẫu Studio"
    )
    assert worker.run_next_once() is True
    assert len(seen) == calls_before
    sess2 = _session(s2)
    assert sess2["status"] == "done", sess2["error"]
    v_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (sess2["video_id"],))
    assert v_row["status"] == "pending_approval"
    assert json.loads(v_row["plan_json"])["shots"][0]["text"] == "Chế tác thủ công"
    info = probe_video(paths.media_dir / str(v_row["output_path"]))
    assert (info.width, info.height) == (1080, 1920)
    assert abs(info.duration_s - 3.0) < 0.2


@pytest.mark.local
def test_studio_session_left_running_without_a_job_is_failed_on_startup(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    orphan = create_studio_session(paths, prompt="Phiên bị ngắt")  # 'planning', no job behind it
    assert recover_stuck_studio_sessions(paths.db_file) == 1
    assert query_one(paths.db_file, "SELECT status FROM studio_sessions WHERE id = ?", (orphan,))["status"] == "failed"

    queued = create_studio_session(paths, prompt="Phiên đang chờ chạy")
    enqueue_studio_job(paths.db_file, queued)
    assert recover_stuck_studio_sessions(paths.db_file) == 0
    assert query_one(paths.db_file, "SELECT status FROM studio_sessions WHERE id = ?", (queued,))["status"] == "planning"


@pytest.mark.local
def test_studio_page_shows_script_waiting_for_confirmation_and_queues_jobs(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from videocreator.app import create_app

    app = create_app(tmp_path, start_worker=False)
    paths = get_paths(tmp_path)
    with TestClient(app) as client:
        resp = client.post("/studio/create", data={"prompt": "Video nhẫn bạc", "voice_lang": "vi"}, follow_redirects=False)
        assert resp.status_code == 303
        sess = query_one(paths.db_file, "SELECT * FROM studio_sessions ORDER BY id DESC LIMIT 1")
        assert json.loads(sess["options_json"])["voice_lang"] == "vi"
        job = query_one(paths.db_file, "SELECT * FROM jobs WHERE kind = ? AND ref_id = ?", (STUDIO_JOB_KIND, sess["id"]))
        assert job is not None and job["status"] == "queued"

        # As if the planning stage had finished: the page shows the script table and the confirm button.
        plan = {"shots": [{"shot_id": 1, "start_s": 0.0, "duration_s": 2.0, "text": "Làm bằng tay"}]}
        with get_conn(paths.db_file) as conn:
            conn.execute("UPDATE studio_sessions SET status = 'awaiting_confirm' WHERE id = ?", (sess["id"],))
            conn.execute("UPDATE videos SET plan_json = ? WHERE id = ?", (json.dumps(plan, ensure_ascii=False), sess["video_id"]))
        page = client.get("/studio")
        assert page.status_code == 200
        assert "Làm bằng tay" in page.text
        assert f"/studio/{sess['id']}/confirm" in page.text

        assert client.post(f"/studio/{sess['id']}/confirm", follow_redirects=False).status_code == 303
        assert query_one(paths.db_file, "SELECT status FROM studio_sessions WHERE id = ?", (sess["id"],))["status"] == "rendering"
