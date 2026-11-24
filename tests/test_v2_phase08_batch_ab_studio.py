"""Tests for Phase 08: Batch & Product A/B Studio with Checkpoint Resume."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.db import get_conn, query_all
from videocreator.paths import get_paths
from videocreator.pipeline.ffmpeg import run_ffmpeg

pytestmark = pytest.mark.local


def _make_portrait_shot(dest: Path, *, duration_s: float = 2.4) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=s=360x640:r=30:d={duration_s}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=480:sample_rate=48000:duration={duration_s}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ac",
            "2",
            str(dest),
        ]
    )
    return dest


def test_batch_products_ab_variants_and_strict_policy(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        # strict_footage workspace #1 with 0 shots rejects batch creation cleanly (403)
        blocked = client.post(
            "/api/v1/batches",
            json={
                "workspace_id": 1,
                "title": "Prompt No Footage",
                "source_kind": "prompts",
                "items": ["Test prompt"],
                "ab_count": 1,
            },
        )
        assert blocked.status_code == 403

        # Add real footage + shot + product in workspace #1
        _make_portrait_shot(paths.footage_dir / "silver_ring.mp4", duration_s=2.4)
        with get_conn(paths.db_file) as conn:
            prod_id = int(
                conn.execute(
                    "INSERT INTO products (workspace_id, name, material, facts_json) VALUES (1, 'Nhan Bac 925', 'Bac S925', ?)",
                    (json.dumps({"weight": "4.2g"}),),
                ).lastrowid
            )
            f_id = int(
                conn.execute(
                    "INSERT INTO footage (workspace_id, path, sha256, orientation, width, height, duration_s) VALUES (1, 'footage/silver_ring.mp4', 'sha_ring_batch_01', 'portrait', 360, 640, 2.4)"
                ).lastrowid
            )
            conn.execute(
                "INSERT INTO shots (footage_id, start_s, end_s, description, has_product, product_ids_json, quality) VALUES (?, 0.0, 2.2, 'Ring macro', 1, ?, 5)",
                (f_id, json.dumps([prod_id])),
            )

        res = client.post(
            "/api/v1/batches",
            json={
                "workspace_id": 1,
                "title": "Ring AB Launch",
                "source_kind": "products",
                "items": [prod_id],
                "ab_count": 2,
                "style_presets": ["tiktok_karaoke", "box_highlight"],
                "sync": True,
            },
        )
        assert res.status_code == 201, res.text
        batch = res.json()["batch"]
        assert batch["status"] == "completed"
        items = batch["items"]
        assert len(items) == 2
        assert [i["variant_label"] for i in items] == ["A", "B"]
        assert [i["style_preset"] for i in items] == ["tiktok_karaoke", "box_highlight"]
        assert items[0]["hook_angle"] != items[1]["hook_angle"]
        for item in items:
            assert item["step"] == "completed"
            assert item["video_id"] is not None
            assert item["video_qc"]["passed"] is True
            assert (paths.media_dir / str(item["video_output_path"])).is_file()


def test_batch_prompts_full_ai_trends_and_checkpoint_resume(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        ws_res = client.post(
            "/api/v1/workspaces",
            json={"name": "Traffic Batch AI", "content_policy": "full_ai"},
        )
        ws_id = int(ws_res.json()["workspace"]["id"])

        # Simulate checkpoint resume deterministically without racing background worker
        from videocreator.pipeline.batch_studio import (
            _plan_batch_item,
            create_batch_run,
            get_batch_run,
            run_batch_run,
        )

        created_b = create_batch_run(
            paths,
            workspace_id=ws_id,
            title="AI Prompts AB",
            source_kind="prompts",
            items=["Meo chup trang suc", "Bi quyet phoi nhan"],
            ab_count=1,
            style_presets=["neon_glow"],
        )
        batch_id = int(created_b["id"])

        batch_before = get_batch_run(paths.db_file, batch_id)
        assert batch_before is not None
        vid1 = _plan_batch_item(paths, batch_before, batch_before["items"][0])
        vid2 = _plan_batch_item(paths, batch_before, batch_before["items"][1])
        assert vid1 != vid2

        # Temporarily rename the generated broll file so item 2's planned render fails (or break plan shot)
        canvas = next(paths.assets_dir.glob(f"ai_canvas_ws{ws_id}_*.mp4"))
        backup = tmp_path / "canvas_backup.mp4"
        shutil.move(str(canvas), str(backup))

        failed_res = run_batch_run(paths, batch_id)
        assert failed_res["status"] == "failed"
        assert failed_res["items"][0]["step"] == "failed"
        assert failed_res["items"][1]["step"] == "failed"
        assert failed_res["items"][0]["video_id"] == vid1
        assert failed_res["items"][1]["video_id"] == vid2

        # Restore canvas and retry failed items via REST API -> exact same video_ids reused!
        shutil.move(str(backup), str(canvas))
        retry_res = client.post(
            f"/api/v1/batches/{batch_id}/retry",
            json={"failed_only": True, "sync": True},
        )
        assert retry_res.status_code == 200
        recovered = retry_res.json()["batch"]
        assert recovered["status"] == "completed", recovered["items"]
        assert recovered["items"][0]["video_id"] == vid1
        assert recovered["items"][1]["video_id"] == vid2
        assert recovered["items"][0]["step"] == "completed"
        assert recovered["items"][1]["step"] == "completed"

        all_vids = query_all(
            paths.db_file, "SELECT id FROM videos WHERE workspace_id = ?", (ws_id,)
        )
        assert len(all_vids) == 2

        # Trends -> send-to-batch bridge
        with get_conn(paths.db_file) as conn:
            t_id = int(
                conn.execute(
                    """
                    INSERT INTO trend_items (workspace_id, source, external_id, url, caption, published_at, score)
                    VALUES (?, 'tiktok', 'tt_b_88', 'https://example.com/t88', 'Trend Ring Stack', '2026-11-24T00:00:00Z', 9.0)
                    """,
                    (ws_id,),
                ).lastrowid
            )
        tb = client.post(
            "/api/v1/trends/send-to-batch",
            json={
                "workspace_id": ws_id,
                "trend_ids": [t_id],
                "ab_count": 2,
                "style_presets": ["tiktok_karaoke", "minimal_bottom"],
                "sync": True,
            },
        )
        assert tb.status_code == 201
        assert tb.json()["batch"]["status"] == "completed"
        assert len(tb.json()["batch"]["items"]) == 2
