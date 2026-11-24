"""Tests for Phase 11: News / Article-to-Video Studio with Fact Preservation & Zip Pack."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.db import query_one
from videocreator.paths import get_paths
from videocreator.pipeline.probe import probe_video

pytestmark = pytest.mark.local


def test_news_html_extraction_fact_preservation_and_publish_pack(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        ws_res = client.post(
            "/api/v1/workspaces",
            json={"name": "Tech & Silver News", "content_policy": "full_ai"},
        )
        ws_id = int(ws_res.json()["workspace"]["id"])

        article_html = tmp_path / "article.html"
        article_html.write_text(
            """<!doctype html>
<html>
<head><title>Ignored Nav Wrapper</title><script>const x = 999;</script></head>
<body>
  <nav>Menu 1234</nav>
  <article>
    <h1>Thị trường trang sức bạc năm 2026 tăng trưởng 92.5%</h1>
    <p>Theo báo cáo quý mới nhất, nhu cầu chế tác thủ công đạt 1500 mẫu mới mỗi tháng trên toàn quốc.</p>
    <p>Người mua trẻ ưu tiên thiết kế tối giản bền vững và nguồn gốc rõ ràng.</p>
  </article>
  <footer>Copyright 2026</footer>
</body>
</html>
""",
            encoding="utf-8",
        )

        cr = client.post(
            "/api/v1/news/projects",
            json={
                "workspace_id": ws_id,
                "source_kind": "url",
                "source_url": article_html.as_uri(),
                "style_preset": "tiktok_karaoke",
            },
        )
        assert cr.status_code == 201
        pid = int(cr.json()["project"]["id"])

        sm = client.post(f"/api/v1/news/projects/{pid}/summarize")
        assert sm.status_code == 200
        summarized = sm.json()["project"]
        assert summarized["status"] == "summarized"
        assert "2026" in summarized["facts"]["preserved_tokens"]
        assert "92.5%" in summarized["facts"]["preserved_tokens"]
        assert "1500" in summarized["facts"]["preserved_tokens"]
        # Ignored script/nav/footer boilerplate tokens must NOT pollute preserved facts
        assert "999" not in summarized["facts"]["preserved_tokens"]

        combined_script = " ".join(s["text"] for s in summarized["script"])
        assert "2026" in combined_script
        assert "92.5%" in combined_script
        assert "1500" in combined_script

        rn = client.post(
            f"/api/v1/news/projects/{pid}/render",
            json={"sync": True, "build_pack": True},
        )
        assert rn.status_code == 200, rn.text
        done = rn.json()["project"]
        assert done["status"] == "completed"
        vid_id = int(done["output_video_id"])

        v_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (vid_id,))
        assert v_row is not None
        assert json.loads(v_row["qc_json"])["passed"] is True
        mp4 = paths.media_dir / str(v_row["output_path"])
        assert mp4.is_file()
        assert probe_video(mp4).duration_s >= 5.0

        pack_path = paths.media_dir / str(done["publish_pack_path"])
        assert pack_path.is_file()
        with zipfile.ZipFile(pack_path, "r") as zf:
            names = set(zf.namelist())
            assert f"video_{vid_id}.mp4" in names
            assert f"cover_{vid_id}.jpg" in names
            assert "captions.txt" in names
            assert "metadata.json" in names
