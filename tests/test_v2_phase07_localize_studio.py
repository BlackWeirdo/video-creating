"""Tests for Phase 07: Localize, Reup, Hybrid Remix & Internationalize Studio."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.db import get_conn, query_one
from videocreator.paths import get_paths
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.pipeline.probe import probe_video

pytestmark = [pytest.mark.local, pytest.mark.slow]


def _make_motion_av(dest: Path, *, width: int = 360, height: int = 640, duration_s: float = 2.6) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=s={width}x{height}:r=30:d={duration_s}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=520:sample_rate=48000:duration={duration_s}",
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


def test_localize_policy_gating_and_intl_export(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        # Default workspace #1 has strict_footage policy
        r_reup = client.post(
            "/api/v1/localize/projects",
            json={"workspace_id": 1, "title": "Blocked Reup", "mode": "reup_vi"},
        )
        assert r_reup.status_code == 403

        r_hyb = client.post(
            "/api/v1/localize/projects",
            json={"workspace_id": 1, "title": "Blocked Hybrid", "mode": "hybrid_remix"},
        )
        assert r_hyb.status_code == 403

        # Prepare a real rendered source_video_id inside workspace 1 for intl_export (vi -> en)
        src_clip = _make_motion_av(paths.footage_dir / "brand_clip.mp4", duration_s=2.4)
        master_clip = _make_motion_av(paths.output_dir / "brand_master.mp4", duration_s=2.4)
        with get_conn(paths.db_file) as conn:
            f_id = int(
                conn.execute(
                    "INSERT INTO footage (workspace_id, path, sha256, orientation, width, height, duration_s) VALUES (1, 'footage/brand_clip.mp4', 'sha_brand_clip_01', 'portrait', 360, 640, 2.4)"
                ).lastrowid
            )
            s_id = int(
                conn.execute(
                    "INSERT INTO shots (footage_id, start_s, end_s, description, has_product, quality) VALUES (?, 0.0, 2.2, 'Handcrafted ring', 1, 5)",
                    (f_id,),
                ).lastrowid
            )
            v_id = int(
                conn.execute(
                    """
                    INSERT INTO videos (workspace_id, footage_id, engine, status, plan_json, voice_lang, caption_lang, output_path, duration_s)
                    VALUES (1, ?, 'ffmpeg', 'pending_approval', ?, 'vi', 'vi', 'output/brand_master.mp4', 2.4)
                    """,
                    (
                        f_id,
                        json.dumps({"shots": [{"shot_id": s_id, "duration_s": 2.2, "text": "Nhan bac 925 tinh xao"}]}),
                    ),
                ).lastrowid
            )

        r_intl = client.post(
            "/api/v1/localize/projects",
            json={
                "workspace_id": 1,
                "title": "Brand Ring EN Export",
                "mode": "intl_export",
                "source_video_id": v_id,
                "source_lang": "vi",
                "target_lang": "en",
                "hardsub_mode": "none",
                "style_preset": "bilingual_stack",
            },
        )
        assert r_intl.status_code == 201
        pid = int(r_intl.json()["project"]["id"])

        ext = client.post(f"/api/v1/localize/projects/{pid}/extract", json={"sync": True})
        assert ext.status_code == 200
        assert ext.json()["project"]["status"] == "ready_to_edit"
        assert len(ext.json()["project"]["segments"]) >= 1

        ren = client.post(f"/api/v1/localize/projects/{pid}/render", json={"sync": True})
        assert ren.status_code == 200
        done = ren.json()["project"]
        assert done["status"] == "completed"
        out_vid = int(done["output_video_id"])

        v_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (out_vid,))
        assert v_row is not None
        assert v_row["target_lang"] == "en"
        assert v_row["voice_lang"] == "en"
        assert json.loads(v_row["qc_json"])["passed"] is True
        assert (paths.media_dir / str(v_row["output_path"])).is_file()


def test_localize_reup_vi_all_three_hardsub_modes(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        ws_res = client.post(
            "/api/v1/workspaces",
            json={"name": "Traffic Full AI", "content_policy": "full_ai"},
        )
        assert ws_res.status_code == 201
        ws_id = int(ws_res.json()["workspace"]["id"])

        raw_src = _make_motion_av(tmp_path / "src_reup.mp4", duration_s=2.6)
        with raw_src.open("rb") as fh:
            up = client.post(
                "/api/v1/localize/upload",
                files={"file": ("src_reup.mp4", fh, "video/mp4")},
            )
        assert up.status_code == 201
        rel_src = up.json()["source_media_path"]

        for mode_idx, hs_mode in enumerate(["blur_bar", "crop_frame", "ocr_inpaint"], start=1):
            c_res = client.post(
                "/api/v1/localize/projects",
                json={
                    "workspace_id": ws_id,
                    "title": f"Reup {hs_mode}",
                    "mode": "reup_vi",
                    "source_media_path": rel_src,
                    "target_lang": "vi",
                    "hardsub_mode": hs_mode,
                    "anti_dup": {"mirror": (mode_idx == 1), "zoom": 1.05, "color_eq": True},
                    "style_preset": "tiktok_karaoke",
                    "aspect_ratio": "9:16",
                },
            )
            assert c_res.status_code == 201
            pid = int(c_res.json()["project"]["id"])

            # Patch deterministic 2 segments so extract/render both work smoothly
            segs = [
                {"index": 0, "start_s": 0.0, "end_s": 1.3, "source_text": "Original sub line 1", "translated_text": "Mở đầu cực cuốn"},
                {"index": 1, "start_s": 1.3, "end_s": 2.6, "source_text": "Original sub line 2", "translated_text": "Xem ngay bí quyết"},
            ]
            p_res = client.patch(f"/api/v1/localize/projects/{pid}", json={"segments": segs})
            assert p_res.status_code == 200

            r_res = client.post(f"/api/v1/localize/projects/{pid}/render", json={"sync": True})
            assert r_res.status_code == 200, r_res.text
            proj = r_res.json()["project"]
            assert proj["status"] == "completed"
            v_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (proj["output_video_id"],))
            assert v_row is not None
            assert json.loads(v_row["qc_json"])["passed"] is True
            out_file = paths.media_dir / str(v_row["output_path"])
            assert out_file.is_file()
            assert probe_video(out_file).duration_s > 2.0

        # Also check Trends -> send-to-localize bridge
        ref_file = paths.reference_dir / "trend_99.mp4"
        _make_motion_av(ref_file, duration_s=2.0)
        with get_conn(paths.db_file) as conn:
            t_id = int(
                conn.execute(
                    """
                    INSERT INTO trend_items (workspace_id, source, external_id, url, caption, published_at, score)
                    VALUES (?, 'youtube', 'yt_loc_99', 'https://example.com/v99', 'Hot Trend Demo', '2026-11-24T00:00:00Z', 9.2)
                    """,
                    (ws_id,),
                ).lastrowid
            )
            conn.execute(
                "INSERT INTO reference_videos (trend_item_id, path, downloaded_at) VALUES (?, 'reference/trend_99.mp4', '2026-11-24T00:00:00Z')",
                (t_id,),
            )

        bridge = client.post(
            f"/api/v1/trends/{t_id}/send-to-localize",
            json={"workspace_id": ws_id, "mode": "reup_vi", "sync_extract": True},
        )
        assert bridge.status_code == 201
        assert bridge.json()["project"]["source_trend_id"] == t_id
        assert bridge.json()["project"]["status"] == "ready_to_edit"


def test_localize_hybrid_remix_splices_real_product_shot(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        ws_res = client.post(
            "/api/v1/workspaces",
            json={"name": "Hybrid Shop", "content_policy": "hybrid_remix"},
        )
        ws_id = int(ws_res.json()["workspace"]["id"])

        # reup_vi is rejected on hybrid_remix workspace
        blocked = client.post(
            "/api/v1/localize/projects",
            json={"workspace_id": ws_id, "title": "Nope", "mode": "reup_vi"},
        )
        assert blocked.status_code == 403

        real_shot_clip = _make_motion_av(paths.footage_dir / "real_product.mp4", duration_s=2.2)
        src_clip = _make_motion_av(paths.media_dir / "localize" / "viral.mp4", duration_s=2.4)
        with get_conn(paths.db_file) as conn:
            prod_id = int(
                conn.execute(
                    "INSERT INTO products (workspace_id, name, material) VALUES (?, 'Nhan Bac 925', 'Bac S925')",
                    (ws_id,),
                ).lastrowid
            )
            f_id = int(
                conn.execute(
                    "INSERT INTO footage (workspace_id, path, sha256, orientation, width, height, duration_s) VALUES (?, 'footage/real_product.mp4', 'sha_real_prod_01', 'portrait', 360, 640, 2.2)",
                    (ws_id,),
                ).lastrowid
            )
            shot_id = int(
                conn.execute(
                    "INSERT INTO shots (footage_id, start_s, end_s, description, has_product, product_ids_json, quality) VALUES (?, 0.0, 2.0, 'Close-up real ring', 1, ?, 5)",
                    (f_id, json.dumps([prod_id])),
                ).lastrowid
            )

        c_res = client.post(
            "/api/v1/localize/projects",
            json={
                "workspace_id": ws_id,
                "title": "Hybrid Ring Remix",
                "mode": "hybrid_remix",
                "source_media_path": "localize/viral.mp4",
                "product_ids": [prod_id],
                "hardsub_mode": "blur_bar",
                "style_preset": "bilingual_stack",
            },
        )
        assert c_res.status_code == 201
        pid = int(c_res.json()["project"]["id"])

        # Missing real shot replacement with product_ids should fail cleanly
        client.patch(
            f"/api/v1/localize/projects/{pid}",
            json={
                "segments": [
                    {"index": 0, "start_s": 0.0, "end_s": 1.2, "source_text": "Clip 1", "translated_text": "Mở đầu", "replace_shot_id": 0},
                ]
            },
        )
        bad_ren = client.post(f"/api/v1/localize/projects/{pid}/render", json={"sync": True})
        assert bad_ren.status_code == 400

        # Auto extract assigns replace_shot_id and renders spliced video cleanly
        ext = client.post(f"/api/v1/localize/projects/{pid}/extract", json={"sync": True})
        assert ext.status_code == 200
        segs = ext.json()["project"]["segments"]
        assert any(int(s.get("replace_shot_id") or 0) == shot_id for s in segs)

        ren = client.post(f"/api/v1/localize/projects/{pid}/render", json={"sync": True})
        assert ren.status_code == 200
        done = ren.json()["project"]
        assert done["status"] == "completed"
        v_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (done["output_video_id"],))
        assert v_row is not None
        assert json.loads(v_row["qc_json"])["passed"] is True
        assert (paths.media_dir / str(v_row["output_path"])).is_file()
