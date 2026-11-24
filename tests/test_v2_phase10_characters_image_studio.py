"""Tests for Phase 10: Consistent Characters, AI Image Studio, RGBA Cutout & Motion Shots."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.db import get_conn, query_one
from videocreator.paths import find_ffmpeg_binary, get_paths
from videocreator.pipeline.ffmpeg import ALLOWED_FILTERS, run_ffmpeg, validate_filtergraph_allowed
from videocreator.pipeline.probe import probe_video
from videocreator.pipeline.render import render_video

pytestmark = pytest.mark.local


def _probe_pix_fmt(path: Path) -> str:
    proc = subprocess.run(
        [
            find_ffmpeg_binary("ffprobe"),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=pix_fmt",
            "-of",
            "default=nw=1:nk=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    return proc.stdout.strip()


def test_characters_consistent_seed_cutout_and_motion_shot(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        # Strict footage workspace blocks AI product image generation (BR-PRD-01)
        blocked = client.post(
            "/api/v1/images",
            json={
                "workspace_id": 1,
                "prompt": "Fake silver ring AI photo",
                "is_product_shot": True,
            },
        )
        assert blocked.status_code == 403
        assert "colorkey" not in ALLOWED_FILTERS
        with pytest.raises(ValueError):
            validate_filtergraph_allowed("colorkey=0x111827")

        # Create character in workspace #1 (allowed for non-product presenter avatar)
        c_res = client.post(
            "/api/v1/characters",
            json={
                "workspace_id": 1,
                "name": "MC Linh",
                "appearance_prompt": "Ao dai xanh pastel, toc bui gon, nu cuoi than thien",
                "seed": 778899,
                "voice_id": "vi-VN-HoaiMyNeural",
                "style_tags": ["presenter", "studio"],
            },
        )
        assert c_res.status_code == 201
        char_id = int(c_res.json()["character"]["id"])
        assert c_res.json()["character"]["seed"] == 778899

        # Upload a real ref PNG onto dark background and run RGBA cutout
        ref_png = tmp_path / "char_ref.png"
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "color=c=#111827:s=240x320:d=1",
                "-vf",
                "drawbox=x=60:y=60:w=120:h=200:color=#38bdf8:t=fill",
                "-frames:v",
                "1",
                "-c:v",
                "png",
                str(ref_png),
            ],
            allow_creative_filters=True,
        )
        with ref_png.open("rb") as fh:
            up = client.post(
                f"/api/v1/characters/{char_id}/upload-ref",
                files={"file": ("char_ref.png", fh, "image/png")},
            )
        assert up.status_code == 200
        assert up.json()["character"]["ref_image_path"]

        cut = client.post(f"/api/v1/characters/{char_id}/cutout")
        assert cut.status_code == 200
        cut_rel = cut.json()["character"]["cutout_image_path"]
        assert cut_rel
        assert "rgba" in _probe_pix_fmt(paths.media_dir / cut_rel)

        # Generate two scene images bound to character -> inherits seed 778899 + appearance_prompt + motion shot
        img1_res = client.post(
            "/api/v1/images",
            json={
                "workspace_id": 1,
                "character_id": char_id,
                "prompt": "Dung trong studio anh sang am",
                "is_product_shot": False,
                "animate_to_shot": True,
            },
        )
        img2_res = client.post(
            "/api/v1/images",
            json={
                "workspace_id": 1,
                "character_id": char_id,
                "prompt": "Gioi thieu meo bao quan trang suc",
                "is_product_shot": False,
                "animate_to_shot": False,
            },
        )
        assert img1_res.status_code == 201, img1_res.text
        assert img2_res.status_code == 201, img2_res.text
        img1 = img1_res.json()["image"]
        img2 = img2_res.json()["image"]
        assert img1["seed"] == 778899
        assert img2["seed"] == 778899
        assert "Ao dai xanh pastel" in img1["prompt"]
        assert img1["motion_shot_id"] is not None

        # Cutout on generated image produces RGBA PNG
        ic = client.post(f"/api/v1/images/{img2['id']}/cutout")
        assert ic.status_code == 200
        assert "rgba" in _probe_pix_fmt(paths.media_dir / ic.json()["image"]["cutout_path"])

        # Motion shot generated by animate_to_shot renders cleanly inside FFmpeg master video
        shot_id = int(img1["motion_shot_id"])
        shot_row = query_one(paths.db_file, "SELECT has_product FROM shots WHERE id = ?", (shot_id,))
        assert shot_row is not None and int(shot_row["has_product"]) == 0

        with get_conn(paths.db_file) as conn:
            vid_id = int(
                conn.execute(
                    """
                    INSERT INTO videos (
                        workspace_id, engine, status, plan_json, voice_lang, caption_lang,
                        style_preset, aspect_ratio, auto_render
                    )
                    VALUES (1, 'ffmpeg', 'planned', ?, 'vi', 'vi', 'tiktok_karaoke', '9:16', 0)
                    """,
                    (
                        json.dumps(
                            {
                                "shots": [
                                    {
                                        "shot_id": shot_id,
                                        "duration_s": 5.0,
                                        "text": "Chao ban den voi studio bac 925.",
                                    }
                                ]
                            }
                        ),
                    ),
                ).lastrowid
            )
        render_video(paths, vid_id, auto_score=False)
        rendered = query_one(paths.db_file, "SELECT output_path, qc_json FROM videos WHERE id = ?", (vid_id,))
        assert rendered is not None
        assert json.loads(rendered["qc_json"])["passed"] is True
        assert probe_video(paths.media_dir / rendered["output_path"]).duration_s >= 4.5
