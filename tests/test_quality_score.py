"""Automatic quality scoring from frames: frame choice, unjudged videos, best attempt kept, fix hint.

Real FFmpeg on tests/samples, real SQLite, real redo/replan code. The vision provider is an
injected object that returns recorded answers in order and records what it was given. No mocks.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from videocreator.app import create_app
from videocreator.db import get_conn, query_all, query_one
from videocreator.pipeline.plan_schema import FactCheckResult
from videocreator.pipeline.quality_frames import extract_score_frames, frame_times
from videocreator.pipeline.quality_score import VideoQualityScore, overall_from, score_rendered_video, weakest_hint

SAMPLE = Path(__file__).resolve().parent / "samples" / "clip1_6s.mp4"


def _answer(hook: int, clarity: int, text: int, pacing: int, *, can_judge: bool = True) -> dict:
    def crit(score: int, what: str) -> dict:
        return {"evidence": what, "score": score}

    return {
        "can_judge": can_judge,
        "cannot_judge_reason": "" if can_judge else "Ảnh đen toàn bộ",
        "hook": crit(hook, "0.3s-2.3s chưa thấy sản phẩm"),
        "product_clarity": crit(clarity, "6.5s nhẫn nét"),
        "text_safe_zone": crit(text, "chữ nằm giữa khung"),
        "pacing_sync": crit(pacing, "lời khớp cảnh"),
        "notes": "Nhận xét ngắn",
    }


class _RecordedVision:
    """Vision provider object answering with recorded scores, one per call, recording its inputs."""

    name = "claude_cli"
    route_kind = "subscription"

    def __init__(self, answers: list[dict]) -> None:
        self.answers = list(answers)
        self.calls: list[dict] = []

    def describe_video(self, video, prompt, schema, *, thumbnails=None):  # type: ignore[no-untyped-def]
        self.calls.append({"video": video, "prompt": prompt, "thumbs": [Path(t) for t in thumbnails or []]})
        assert all(Path(t).is_file() for t in thumbnails or [])
        return schema.model_validate(self.answers.pop(0))


def _rendered_video(paths, *, supersedes: int | None = None, auto_retry: int = 0) -> int:  # type: ignore[no-untyped-def]
    plan = {"title": "V", "formula": "hook-first", "shots": [
        {"shot_id": 1, "start_s": 0.0, "duration_s": 2.0, "text": "Mở đầu"},
        {"shot_id": 2, "start_s": 2.0, "duration_s": 4.0, "text": "Cận cảnh nhẫn"},
    ]}
    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            "INSERT INTO videos (status, plan_json, captions_json, supersedes_id, auto_retry_count) "
            "VALUES ('rendered', ?, '{}', ?, ?)",
            (json.dumps(plan, ensure_ascii=False), supersedes, auto_retry),
        )
        vid = int(cur.lastrowid or 0)
        rel = f"output/video_{vid}.mp4"
        (paths.media_dir / "output").mkdir(parents=True, exist_ok=True)
        shutil.copy2(SAMPLE, paths.media_dir / rel)
        conn.execute("UPDATE videos SET output_path = ? WHERE id = ?", (rel, vid))
    return vid


@pytest.mark.local
def test_frame_times_hook_plus_one_per_shot() -> None:
    plan = {"shots": [{"duration_s": 4}, {"duration_s": 5}, {"duration_s": 6}]}
    assert frame_times(plan, 15.0) == [0.3, 1.3, 2.3, 6.5, 12.0]  # shot 1 middle (2.0) too close to 2.3

    many = {"shots": [{"duration_s": 1.5} for _ in range(20)]}
    times = frame_times(many, 30.0)
    assert len(times) <= 12 and times[:3] == [0.3, 1.3, 2.3] and times == sorted(times)

    assert all(t <= 1.95 for t in frame_times({"shots": [{"duration_s": 2}]}, 2.0))  # never past the end
    assert len(frame_times({}, 18.0)) >= 6  # no plan timing: frames spread over the video


@pytest.mark.local
def test_extract_score_frames_with_real_ffmpeg(tmp_path: Path) -> None:
    frames = extract_score_frames(SAMPLE, [0.3, 1.3, 2.3, 4.5, 30.0], tmp_path / "f")
    assert [t for t, _ in frames][:4] == [0.3, 1.3, 2.3, 4.5]  # 30 s is past the end of the 6 s clip
    assert all(p.stat().st_size > 1000 for _, p in frames)


@pytest.mark.local
def test_overall_is_computed_and_weakest_criterion_named() -> None:
    res = VideoQualityScore.model_validate(_answer(4, 9, 8, 7))
    assert overall_from(res) == 7.0
    assert weakest_hint(res) == "Mở đầu 4/10: 0.3s-2.3s chưa thấy sản phẩm"


@pytest.mark.local
def test_provider_gets_labeled_frames_and_good_video_goes_to_approval(tmp_path: Path) -> None:
    paths = create_app(data_dir=tmp_path, start_worker=False).state.paths
    vid = _rendered_video(paths)
    vision = _RecordedVision([_answer(9, 9, 8, 8)])

    status, active, score = score_rendered_video(paths, vid, provider=vision)
    assert (status, active, score) == ("pending_approval", vid, 8.5)
    call = vision.calls[0]
    assert 3 <= len(call["thumbs"]) <= 12
    assert "Ảnh 1 = 0.3s (mở đầu)" in call["prompt"] and "Cận cảnh nhẫn" in call["prompt"]
    assert not (paths.work_dir / f"score_{vid}").exists()  # frames cleaned up


@pytest.mark.local
def test_unjudged_video_is_never_redone(tmp_path: Path) -> None:
    paths = create_app(data_dir=tmp_path, start_worker=False).state.paths

    # Missing master file: provider not called, no redo, approval with no score
    missing = _rendered_video(paths)
    (paths.media_dir / f"output/video_{missing}.mp4").unlink()
    vision = _RecordedVision([])
    assert score_rendered_video(paths, missing, provider=vision) == ("pending_approval", missing, None)
    assert vision.calls == []

    # The model says it cannot judge
    blind = _rendered_video(paths)
    status, active, score = score_rendered_video(paths, blind, provider=_RecordedVision([_answer(1, 1, 1, 1, can_judge=False)]))
    assert (status, active, score) == ("pending_approval", blind, None)

    for vid in (missing, blind):
        row = query_one(paths.db_file, "SELECT status, quality_score, quality_notes FROM videos WHERE id = ?", (vid,))
        assert row["status"] == "pending_approval" and row["quality_score"] is None
        assert row["quality_notes"].startswith("Chưa chấm được")
    assert query_all(paths.db_file, "SELECT id FROM videos WHERE supersedes_id IS NOT NULL") == []


@pytest.mark.local
def test_best_attempt_of_the_chain_goes_to_approval(tmp_path: Path) -> None:
    paths = create_app(data_dir=tmp_path, start_worker=False).state.paths
    v1 = _rendered_video(paths)

    # 7.5 < 8 -> redo #1
    status, v2, _ = score_rendered_video(paths, v1, provider=_RecordedVision([_answer(6, 8, 8, 8)]))
    assert status == "superseded"
    assert query_one(paths.db_file, "SELECT supersedes_id, auto_retry_count FROM videos WHERE id = ?", (v2,)) == {
        "supersedes_id": v1, "auto_retry_count": 1}
    # Stand in for the replan + render jobs of the replacement: same master, status rendered
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE videos SET status = 'rendered', output_path = ? WHERE id = ?", (f"output/video_{v2}.mp4", v2))
    shutil.copy2(SAMPLE, paths.media_dir / f"output/video_{v2}.mp4")

    # 6.0 -> redo #2
    status, v3, _ = score_rendered_video(paths, v2, provider=_RecordedVision([_answer(5, 6, 7, 6)]))
    assert status == "superseded"
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE videos SET status = 'rendered', output_path = ? WHERE id = ?", (f"output/video_{v3}.mp4", v3))
    shutil.copy2(SAMPLE, paths.media_dir / f"output/video_{v3}.mp4")

    # 7.0, no redo left -> the 7.5 attempt (v1) is sent for approval instead of the last one
    status, active, score = score_rendered_video(paths, v3, provider=_RecordedVision([_answer(7, 7, 7, 7)]))
    assert (status, active, score) == ("superseded", v1, 7.0)
    statuses = {r["id"]: r["status"] for r in query_all(paths.db_file, "SELECT id, status FROM videos")}
    assert statuses == {v1: "pending_approval", v2: "superseded", v3: "superseded"}
    audit = query_all(paths.db_file, "SELECT object_id FROM audit_log WHERE action = 'video.best_attempt_restored'")
    assert audit == [{"object_id": v1}]


class _HintWriter:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate_json(self, prompt, schema):  # type: ignore[no-untyped-def]
        if schema is FactCheckResult:
            return schema.model_validate({"unverified_claims": []})
        self.prompts.append(prompt)
        return schema.model_validate({"plans": []})


@pytest.mark.local
def test_redo_script_request_names_the_weak_criterion(tmp_path: Path) -> None:
    from videocreator.pipeline.replan import replan_video

    paths = create_app(data_dir=tmp_path, start_worker=False).state.paths
    with get_conn(paths.db_file) as conn:
        conn.execute(
            "INSERT INTO footage (id, path, sha256, duration_s, width, height, orientation, product_ids_json, status) "
            "VALUES (1, 'footage/1.mp4', 'sha1', 12, 1080, 1920, 'portrait', '[]', 'analysed')"
        )
        conn.execute(
            "INSERT INTO shots (id, footage_id, idx, start_s, end_s, description, has_product, product_ids_json) "
            "VALUES (1, 1, 1, 0, 6, 'Nhẫn', 0, '[]')"
        )
        conn.execute(
            "INSERT INTO videos (id, footage_id, status, plan_json, quality_score, quality_notes) VALUES "
            "(1, 1, 'superseded', '{}', 6.0, 'Mở đầu 4/10: 0.3s-2.3s chưa thấy sản phẩm | Nhận xét')"
        )
        conn.execute(
            "INSERT INTO videos (id, footage_id, status, plan_json, supersedes_id) VALUES (2, 1, 'planned', '{}', 1)"
        )
    writer = _HintWriter()
    replan_video(paths, 2, writer_provider=writer, checker_provider=writer)
    assert "LẦN DỰNG TRƯỚC BỊ CHẤM THẤP VÌ: Mở đầu 4/10: 0.3s-2.3s chưa thấy sản phẩm" in writer.prompts[0]


@pytest.mark.local
def test_attempt_a_reviewer_redid_is_never_restored(tmp_path: Path) -> None:
    from videocreator.redo import redo_video

    paths = create_app(data_dir=tmp_path, start_worker=False).state.paths
    v1 = _rendered_video(paths)
    assert score_rendered_video(paths, v1, provider=_RecordedVision([_answer(9, 9, 9, 9)]))[0] == "pending_approval"
    v2 = redo_video(paths.db_file, v1, by="ui")  # the reviewer turns down the 9.0 video

    def rendered(vid: int) -> None:
        with get_conn(paths.db_file) as conn:
            conn.execute("UPDATE videos SET status = 'rendered', output_path = ? WHERE id = ?", (f"output/video_{vid}.mp4", vid))
        shutil.copy2(SAMPLE, paths.media_dir / f"output/video_{vid}.mp4")

    rendered(v2)
    _, v3, _ = score_rendered_video(paths, v2, provider=_RecordedVision([_answer(6, 6, 6, 6)]))
    rendered(v3)
    _, v4, _ = score_rendered_video(paths, v3, provider=_RecordedVision([_answer(5, 5, 5, 5)]))
    rendered(v4)
    status, active, _ = score_rendered_video(paths, v4, provider=_RecordedVision([_answer(4, 4, 4, 4)]))

    assert (status, active) == ("superseded", v2)  # best automatic attempt (6.0), not the redone 9.0
    statuses = {r["id"]: r["status"] for r in query_all(paths.db_file, "SELECT id, status FROM videos")}
    assert statuses[v1] == "superseded" and statuses[v2] == "pending_approval"
