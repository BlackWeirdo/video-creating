"""Trends page: manual analyse route, upload-reference queueing and status rendering."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.db import get_conn
from _trend_helpers import _add_item, _jobs, _make_app, _mark_analysed, _status


@pytest.mark.local
def test_analyse_route_and_upload_reference_enqueue(tmp_path: Path) -> None:
    app, paths = _make_app(tmp_path)
    a = _add_item(paths, "youtube", "a", 5)
    done = _add_item(paths, "youtube", "d", 4)
    _mark_analysed(paths, done)
    other = _add_item(paths, "youtube", "o", 3)
    with TestClient(app) as client:
        r = client.post(f"/trends/{a}/analyse", follow_redirects=False)
        assert r.status_code == 303 and "analysis_queued" in r.headers["location"]
        assert [j["ref_id"] for j in _jobs(paths, "queued")] == [a]
        assert _status(paths, a) == "queued"

        r = client.post("/trends/99999/analyse", follow_redirects=False)
        assert r.status_code == 404

        r = client.post(
            f"/trends/{other}/upload-reference",
            files={"file": ("x.mp4", b"not-a-real-video", "video/mp4")},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert other in [j["ref_id"] for j in _jobs(paths, "queued")]
        assert _status(paths, other) == "queued"
        assert (paths.media_dir / f"reference/ref_{other}.mp4").exists()

        r = client.post(
            f"/trends/{done}/upload-reference",
            files={"file": ("x.mp4", b"not-a-real-video", "video/mp4")},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert done not in [j["ref_id"] for j in _jobs(paths)]
        assert _status(paths, done) is None  # upload leaves an analysed item alone


@pytest.mark.local
def test_trends_page_shows_analysis_states(tmp_path: Path) -> None:
    app, paths = _make_app(tmp_path)
    none_id = _add_item(paths, "youtube", "n", 1)
    queued_id = _add_item(paths, "youtube", "q", 2)
    running_id = _add_item(paths, "youtube", "r", 3)
    failed_id = _add_item(paths, "youtube", "f", 4)
    with get_conn(paths.db_file) as conn:
        conn.execute("UPDATE trend_items SET analysis_status = 'queued' WHERE id = ?", (queued_id,))
        conn.execute("UPDATE trend_items SET analysis_status = 'running' WHERE id = ?", (running_id,))
        conn.execute(
            "UPDATE trend_items SET analysis_status = 'failed', analysis_error = 'boom-xyz' WHERE id = ?",
            (failed_id,),
        )
    with TestClient(app) as client:
        r = client.get("/trends?source=youtube")
    assert r.status_code == 200
    html = r.text
    assert "Đang chờ phân tích" in html
    assert "Đang phân tích" in html
    assert "Lỗi: boom-xyz" in html and "Phân tích lại" in html
    assert "Chưa phân tích" in html
    for tid in (none_id, failed_id):
        assert f'action="/trends/{tid}/analyse"' in html
    for tid in (queued_id, running_id):
        assert f'action="/trends/{tid}/analyse"' not in html
    # exactly 1 "Phân tích" plain button (NULL) and 1 retry button (failed)
    assert html.count(">Phân tích</button>") == 1
    assert html.count(">Phân tích lại</button>") == 1
