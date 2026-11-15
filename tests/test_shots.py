"""Real footage probe, import, rea-video shot detection, thumbnail extraction, and UI tests (no mocks)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.db import migrate, query_all, query_one
from videocreator.paths import get_paths
from videocreator.pipeline.footage_analyse import run_analyse_footage
from videocreator.pipeline.footage_import import DuplicateFootageError, import_footage_file
from videocreator.pipeline.probe import probe_video
from videocreator.pipeline.shots import ShotSpan, postprocess_shot_spans
from videocreator.products import create_product

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
CLIP_PORTRAIT = SAMPLES_DIR / "clip1_6s.mp4"
CLIP_LANDSCAPE = SAMPLES_DIR / "clip_landscape_5s.mp4"


@pytest.mark.local
def test_postprocess_shot_spans_rules() -> None:
    raw = [
        ShotSpan(0.0, 0.4),    # < 0.7s -> dropped
        ShotSpan(0.4, 2.5),    # 2.1s -> kept
        ShotSpan(2.5, 13.5),   # 11.0s (> 8.0s) -> split into 3 equal ~3.67s segments
    ]
    processed = postprocess_shot_spans(raw, total_duration_s=13.5)
    assert len(processed) == 4
    assert processed[0] == ShotSpan(0.4, 2.5)
    for prev, curr in zip(processed, processed[1:]):
        assert curr.start_s >= prev.end_s
    for span in processed:
        assert 0.7 <= span.duration_s <= 8.0
        assert 0.0 <= span.start_s < span.end_s <= 13.5


@pytest.mark.local
def test_probe_portrait_and_landscape_samples() -> None:
    assert CLIP_PORTRAIT.exists(), f"Missing sample {CLIP_PORTRAIT}"
    assert CLIP_LANDSCAPE.exists(), f"Missing sample {CLIP_LANDSCAPE}"

    p_info = probe_video(CLIP_PORTRAIT)
    assert p_info.width == 1080
    assert p_info.height == 1920
    assert p_info.orientation == "portrait"
    assert not p_info.is_landscape
    assert not p_info.is_low_res
    assert 5.5 <= p_info.duration_s <= 6.5

    l_info = probe_video(CLIP_LANDSCAPE)
    assert l_info.width == 1280
    assert l_info.height == 720
    assert l_info.orientation == "landscape"
    assert l_info.is_landscape
    assert l_info.is_low_res  # short edge 720 < 1080


@pytest.mark.local
def test_import_validation_dedup_and_real_analyse(tmp_path: Path) -> None:
    paths = get_paths(tmp_path)
    migrate(paths.db_file)

    pid = create_product(
        paths.db_file,
        name="Nhẫn Bạc Xúc Xắc",
        material="Bạc S925",
        facts={"stone": "Không đính đá", "craftsmanship": "Chạm khắc thủ công"},
    )

    # FR-FTG-03: importing without product_ids and no_product=False must fail
    with pytest.raises(ValueError, match="FR-FTG-03"):
        import_footage_file(paths, CLIP_PORTRAIT, product_ids=[], no_product=False)

    # Valid import with product_ids
    fid1 = import_footage_file(
        paths,
        CLIP_PORTRAIT,
        product_ids=[pid],
        no_product=False,
        enqueue_analysis=False,
    )
    assert fid1 == 1

    # Duplicate SHA-256 must be rejected
    with pytest.raises(DuplicateFootageError):
        import_footage_file(
            paths,
            CLIP_PORTRAIT,
            product_ids=[pid],
            no_product=False,
            enqueue_analysis=False,
        )

    # Landscape import sets default blur_pad crop_json
    fid2 = import_footage_file(
        paths,
        CLIP_LANDSCAPE,
        product_ids=[],
        no_product=True,
        enqueue_analysis=False,
    )
    row2 = query_one(paths.db_file, "SELECT * FROM footage WHERE id = ?", (fid2,))
    assert row2 is not None
    assert row2["orientation"] == "landscape"
    assert json.loads(row2["crop_json"]) == {"mode": "blur_pad", "x_offset_ratio": 0.5}

    # Real shot detection + thumbnail extraction on fid1 via rea-video & ffmpeg
    log_out = run_analyse_footage(paths, fid1)
    assert "Detected" in log_out

    row1 = query_one(paths.db_file, "SELECT * FROM footage WHERE id = ?", (fid1,))
    assert row1 is not None
    assert row1["status"] == "analysed"

    shots = query_all(
        paths.db_file,
        "SELECT * FROM shots WHERE footage_id = ? ORDER BY idx ASC",
        (fid1,),
    )
    assert len(shots) >= 1
    total_dur = float(row1["duration_s"])
    prev_end = 0.0
    for s in shots:
        start_s = float(s["start_s"])
        end_s = float(s["end_s"])
        assert start_s >= prev_end - 1e-3
        assert 0.0 <= start_s < end_s <= total_dur + 0.05
        assert s["has_product"] == 1
        assert json.loads(s["product_ids_json"]) == [pid]
        thumb_file = paths.media_dir / str(s["thumb_path"])
        assert thumb_file.exists() and thumb_file.stat().st_size > 500
        prev_end = end_s


@pytest.mark.local
def test_footage_shots_and_media_traversal_routes(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    paths = app.state.paths
    pid = create_product(
        paths.db_file,
        name="Nhẫn Bạc Nhẫn Mới",
        material="Bạc S925",
        facts={"stone": "Không đính đá"},
    )
    fid = import_footage_file(
        paths,
        CLIP_LANDSCAPE,
        product_ids=[pid],
        enqueue_analysis=False,
    )

    with TestClient(app) as client:
        # Update landscape crop mode
        resp = client.post(
            f"/footage/{fid}/crop",
            data={"mode": "crop", "x_offset_ratio": "0.35"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        row = query_one(paths.db_file, "SELECT crop_json FROM footage WHERE id = ?", (fid,))
        assert row is not None
        assert json.loads(row["crop_json"]) == {"mode": "crop", "x_offset_ratio": 0.35}

        # Valid media request succeeds
        media_ok = client.get(f"/media/footage/{fid}.mp4")
        assert media_ok.status_code == 200
        assert len(media_ok.content) > 1000

        # Path traversal attempt must be rejected (NFR-SEC-05)
        traversal = client.get("/media/..%2Fvideocreator.db")
        assert traversal.status_code in (403, 404)


@pytest.mark.local
def test_import_copies_outside_the_db_write_lock(tmp_path: Path) -> None:
    """While a (multi-GB) footage file is being copied, other jobs must still be able to write to SQLite."""
    import shutil
    import sqlite3

    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    pid = create_product(paths.db_file, name="Nhẫn Bạc", material="Bạc S925", facts={})
    writes_during_copy: list[str] = []

    def copy_while_another_connection_writes(src: Path, dst: Path) -> None:
        shutil.copy2(src, dst)
        # busy_timeout=0: fails at once with "database is locked" if the import held the write lock
        other = sqlite3.connect(str(paths.db_file), timeout=0)
        try:
            other.execute("INSERT INTO settings (key, value) VALUES ('probe_write', 'ok')")
            other.commit()
            writes_during_copy.append("ok")
        finally:
            other.close()

    fid = import_footage_file(
        paths,
        CLIP_PORTRAIT,
        product_ids=[pid],
        enqueue_analysis=False,
        copy_file=copy_while_another_connection_writes,
    )
    assert writes_during_copy == ["ok"]
    row = query_one(paths.db_file, "SELECT path FROM footage WHERE id = ?", (fid,))
    assert row is not None and row["path"] == f"footage/{fid}.mp4"
    assert (paths.media_dir / row["path"]).stat().st_size == CLIP_PORTRAIT.stat().st_size
    incoming = paths.media_dir / "footage" / ".incoming"
    assert list(incoming.iterdir()) == []

    # A failed copy leaves neither a temporary file nor a 'pending' row behind
    def failing_copy(src: Path, dst: Path) -> None:
        dst.write_bytes(b"partial")
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        import_footage_file(
            paths, CLIP_LANDSCAPE, product_ids=[pid], enqueue_analysis=False, copy_file=failing_copy
        )
    assert list(incoming.iterdir()) == []
    assert query_all(paths.db_file, "SELECT id FROM footage WHERE path = 'pending'") == []
