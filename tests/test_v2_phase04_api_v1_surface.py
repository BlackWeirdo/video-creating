"""End-to-end real-SQLite + real-FFmpeg tests for complete `/api/v1/*` JSON REST surface (Phase 04)."""
from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.db import get_conn
from videocreator.pipeline.ffmpeg import run_ffmpeg

pytestmark = pytest.mark.local

SAMPLE_CLIP_1 = Path(__file__).resolve().parent / "samples" / "clip1_6s.mp4"
SAMPLE_CLIP_2 = Path(__file__).resolve().parent / "samples" / "clip2_6s.mp4"


def test_v1_multi_workspace_isolation_across_all_resources(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    with TestClient(app) as client:
        # Create second workspace
        ws2_resp = client.post(
            "/api/v1/workspaces",
            json={
                "name": "Phân Xưởng Đá Quý",
                "niche": "gemstones",
                "content_policy": "hybrid_remix",
                "approval_mode": "bulk",
            },
        )
        assert ws2_resp.status_code == 201
        ws2_id = int(ws2_resp.json()["workspace"]["id"])

        # Products isolated per workspace
        p1 = client.post(
            "/api/v1/products",
            json={"workspace_id": 1, "name": "Nhẫn Bạc WS1", "material": "S925"},
        )
        p2 = client.post(
            "/api/v1/products",
            json={"workspace_id": ws2_id, "name": "Vòng Thạch Anh WS2", "material": "Thạch anh"},
        )
        assert p1.status_code == 201 and p2.status_code == 201
        p1_id = p1.json()["product"]["id"]
        p2_id = p2.json()["product"]["id"]

        assert [x["name"] for x in client.get("/api/v1/products", params={"workspace_id": 1}).json()["products"]] == ["Nhẫn Bạc WS1"]
        assert [x["name"] for x in client.get("/api/v1/products", params={"workspace_id": ws2_id}).json()["products"]] == ["Vòng Thạch Anh WS2"]

        # Footage + Shots isolated per workspace
        clip_a = tmp_path / "ws1_clip.mp4"
        clip_b = tmp_path / "ws2_clip.mp4"
        shutil.copy2(SAMPLE_CLIP_1, clip_a)
        shutil.copy2(SAMPLE_CLIP_2, clip_b)

        f1_resp = client.post(
            "/api/v1/footage/import-local",
            json={
                "source_path": str(clip_a),
                "workspace_id": 1,
                "product_ids": [p1_id],
                "enqueue_analysis": False,
            },
        )
        f2_resp = client.post(
            "/api/v1/footage/import-local",
            json={
                "source_path": str(clip_b),
                "workspace_id": ws2_id,
                "product_ids": [p2_id],
                "enqueue_analysis": False,
            },
        )
        assert f1_resp.status_code == 201 and f2_resp.status_code == 201
        fid1 = f1_resp.json()["footage"]["id"]
        fid2 = f2_resp.json()["footage"]["id"]

        with get_conn(app.state.paths.db_file) as conn:
            conn.execute(
                "INSERT INTO shots (id, footage_id, idx, start_s, end_s, description, has_product, product_ids_json) "
                "VALUES (101, ?, 1, 0.0, 3.0, 'Shot WS1', 1, ?), (102, ?, 1, 0.0, 3.0, 'Shot WS2', 1, ?)",
                (fid1, f"[{p1_id}]", fid2, f"[{p2_id}]"),
            )

        assert [s["id"] for s in client.get("/api/v1/shots", params={"workspace_id": 1}).json()["shots"]] == [101]
        assert [s["id"] for s in client.get("/api/v1/shots", params={"workspace_id": ws2_id}).json()["shots"]] == [102]

        # Watchlist isolated per workspace
        assert client.post(
            "/api/v1/watchlist",
            json={"workspace_id": 1, "source": "youtube", "kind": "keyword", "value": "nhẫn bạc s925"},
        ).status_code == 201
        assert client.post(
            "/api/v1/watchlist",
            json={"workspace_id": ws2_id, "source": "youtube", "kind": "keyword", "value": "đá phong thủy"},
        ).status_code == 201
        assert len(client.get("/api/v1/watchlist", params={"workspace_id": 1}).json()["watchlist"]) == 1
        assert len(client.get("/api/v1/watchlist", params={"workspace_id": ws2_id}).json()["watchlist"]) == 1

        # Accounts isolated per workspace
        assert client.post(
            "/api/v1/accounts",
            json={
                "workspace_id": 1,
                "platform": "tiktok",
                "external_id": "tt_ws1",
                "name": "TT Brand 1",
                "access_token": "tok_ws1_secret",
            },
        ).status_code == 201
        assert client.post(
            "/api/v1/accounts",
            json={
                "workspace_id": ws2_id,
                "platform": "youtube",
                "external_id": "yt_ws2",
                "name": "YT Gem 2",
                "access_token": "tok_ws2_secret",
            },
        ).status_code == 201

        accs_ws1 = client.get("/api/v1/accounts", params={"workspace_id": 1}).json()["accounts"]
        accs_ws2 = client.get("/api/v1/accounts", params={"workspace_id": ws2_id}).json()["accounts"]
        assert [a["external_id"] for a in accs_ws1] == ["tt_ws1"]
        assert [a["external_id"] for a in accs_ws2] == ["yt_ws2"]
        assert "tok_ws1_secret" not in json.dumps(accs_ws1)

        # Dashboard counts match workspace scope
        dash1 = client.get("/api/v1/dashboard", params={"workspace_id": 1}).json()
        assert dash1["counts"]["products"] == 1
        assert dash1["counts"]["footage"] == 1
        assert dash1["counts"]["shots"] == 1
        assert dash1["counts"]["accounts"] == 1


def test_v1_end_to_end_production_restyle_files_zip_and_bulk_publish(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    with TestClient(app) as client:
        # 1. Configure voice provider = local & upload audio asset
        assert client.put("/api/v1/voices", json={"vi_provider": "local", "vi_voice": "local-vi-studio"}).status_code == 200
        bgm_wav = tmp_path / "bgm.wav"
        run_ffmpeg(
            ["-f", "lavfi", "-i", "sine=frequency=240:sample_rate=48000:duration=6", "-ac", "2", str(bgm_wav)]
        )
        with bgm_wav.open("rb") as fh:
            asset_resp = client.post(
                "/api/v1/assets/upload",
                data={"workspace_id": "1", "kind": "music", "title": "LoFi Silver"},
                files={"file": ("bgm.wav", fh, "audio/wav")},
            )
        assert asset_resp.status_code == 201
        music_id = asset_resp.json()["asset"]["id"]

        # 2. Voice preview synthesis + /files playback
        preview_resp = client.post(
            "/api/v1/voices/preview",
            json={"text": "Nhẫn bạc S925 thủ công", "lang": "vi", "provider": "local"},
        )
        assert preview_resp.status_code == 200
        preview_data = preview_resp.json()
        assert preview_data["syllables"] == 5
        assert len(preview_data["word_timings"]) == 5
        assert client.get(preview_data["audio_url"]).status_code == 200

        # 3. Product + Footage + Shot + focus_x PATCH
        prod_id = client.post(
            "/api/v1/products", json={"name": "Nhẫn Xúc Xắc V2", "material": "Bạc S925"}
        ).json()["product"]["id"]
        with SAMPLE_CLIP_1.open("rb") as fh:
            ftg_resp = client.post(
                "/api/v1/footage/upload",
                data={"workspace_id": "1", "product_ids": str(prod_id), "enqueue_analysis": "false"},
                files={"file": ("clip1_6s.mp4", fh, "video/mp4")},
            )
        assert ftg_resp.status_code == 201
        fid = ftg_resp.json()["footage"]["id"]

        with get_conn(app.state.paths.db_file) as conn:
            conn.execute(
                "INSERT INTO shots (id, footage_id, idx, start_s, end_s, description, has_product, product_ids_json) "
                "VALUES (501, ?, 1, 0.0, 2.8, 'Mở đầu', 1, ?), (502, ?, 2, 2.8, 5.6, 'Cận cảnh', 1, ?)",
                (fid, f"[{prod_id}]", fid, f"[{prod_id}]"),
            )
        patch_shot = client.patch(
            "/api/v1/shots/501",
            json={"focus_x": 0.35, "quality": 5, "tags": ["hero", "closeup"]},
        )
        assert patch_shot.status_code == 200
        assert patch_shot.json()["shot"]["focus_x"] == pytest.approx(0.35)

        # 4. Create video -> edit script with syllable budget -> sync render -> sync restyle -> /files stream
        create_vid = client.post(
            "/api/v1/videos",
            json={
                "workspace_id": 1,
                "footage_id": fid,
                "product_ids": [prod_id],
                "voice_lang": "vi",
                "style_preset": "tiktok_karaoke",
                "aspect_ratio": "9:16",
                "plan": {
                    "title": "Nhẫn Xúc Xắc Thủ Công",
                    "shots": [
                        {"shot_id": 501, "start_s": 0.0, "duration_s": 2.6, "text": "Nhẫn bạc S925 nguyên khối"},
                        {"shot_id": 502, "start_s": 2.8, "duration_s": 2.6, "text": "Chạm khắc thủ công tinh xảo"},
                    ],
                },
            },
        )
        assert create_vid.status_code == 201
        vid_id = create_vid.json()["video"]["id"]

        patch_vid = client.patch(
            f"/api/v1/videos/{vid_id}",
            json={
                "captions": {
                    "tiktok": {"text": "Caption TikTok V2", "hashtags": ["#bacthucong"]},
                    "youtube": {"text": "Caption YouTube V2", "hashtags": ["#Shorts"]},
                }
            },
        )
        assert patch_vid.status_code == 200
        assert len(patch_vid.json()["video"]["syllable_budget"]) == 2

        render_resp = client.post(
            f"/api/v1/videos/{vid_id}/render?sync=true",
            json={"music_asset_id": music_id, "preset": "ultrafast", "sync": True},
        )
        assert render_resp.status_code == 200
        rendered_vid = render_resp.json()["video"]
        assert rendered_vid["status"] == "pending_approval"
        assert rendered_vid["qc"]["passed"] is True
        assert rendered_vid["output_url"].startswith("/files/")

        restyle_resp = client.post(
            f"/api/v1/videos/{vid_id}/restyle?sync=true",
            json={"style_preset": "neon_glow", "music_asset_id": music_id, "preset": "ultrafast", "sync": True},
        )
        assert restyle_resp.status_code == 200
        assert restyle_resp.json()["video"]["style_preset"] == "neon_glow"

        # Serve rendered MP4 via /files/* & block traversal
        mp4_resp = client.get(rendered_vid["output_url"])
        assert mp4_resp.status_code == 200 and len(mp4_resp.content) > 5_000
        assert client.get("/files/../../secrets.bin").status_code in (403, 404)

        # Download .zip Publish Pack
        pack_resp = client.get(f"/api/v1/videos/{vid_id}/publish-pack")
        assert pack_resp.status_code == 200
        assert pack_resp.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(pack_resp.content), "r") as zf:
            assert f"video_{vid_id}.mp4" in zf.namelist()
            assert "--- YOUTUBE ---" in zf.read("captions.txt").decode("utf-8")

        # Connect channel + bulk approve + verify scheduled post
        assert client.post(
            "/api/v1/accounts",
            json={
                "workspace_id": 1,
                "platform": "tiktok",
                "external_id": "tt_prod_shop",
                "name": "Shop Bạc",
                "access_token": "secret_tt_tok_abc",
            },
        ).status_code == 201
        assert len(client.get("/api/v1/approvals").json()["pending"]) == 1

        bulk = client.post("/api/v1/approvals/bulk-approve", json={"video_ids": [vid_id]})
        assert bulk.status_code == 200
        assert bulk.json()["approved_ids"] == [vid_id]
        assert len(client.get("/api/v1/posts").json()["posts"]) == 1


def test_v1_settings_secrets_masking_validation_and_v1_html_compatibility(tmp_path: Path) -> None:
    app = create_app(data_dir=tmp_path, start_worker=False)
    with TestClient(app) as client:
        # Secrets must be written securely and NEVER exposed in JSON
        put_sec = client.put(
            "/api/v1/secrets",
            json={"secrets": {"GOOGLE_CLIENT_ID": "super-secret-client-id-999"}},
        )
        assert put_sec.status_code == 200
        sec_list = client.get("/api/v1/secrets")
        assert sec_list.status_code == 200
        assert "super-secret-client-id-999" not in sec_list.text
        google_entry = next(
            x for x in sec_list.json()["secrets"] if x["name"] == "GOOGLE_CLIENT_ID"
        )
        assert google_entry["configured"] is True

        # Settings update validates & updates worker concurrency
        bad_tz = client.put(
            "/api/v1/settings",
            json={"schedule": {"timezone": "Invalid/Mars_Timezone"}},
        )
        assert bad_tz.status_code == 400

        upd_cfg = client.put(
            "/api/v1/settings",
            json={"worker": {"io_concurrency": 6, "compute_concurrency": 2}},
        )
        assert upd_cfg.status_code == 200
        assert upd_cfg.json()["settings"]["worker"]["io_concurrency"] == 6
        assert app.state.worker.io_concurrency == 6
        assert app.state.worker.compute_concurrency == 2

        # Validation 404 & 422
        assert client.get("/api/v1/videos/999999").status_code == 404
        assert client.patch("/api/v1/shots/1", json={"focus_x": 1.8}).status_code == 422
        assert client.delete("/api/v1/styles/tiktok_karaoke").status_code == 400

        # Trends/Studio/AI usage list endpoints respond cleanly
        assert client.get("/api/v1/trends").status_code == 200
        assert client.get("/api/v1/suggestions").status_code == 200
        assert client.get("/api/v1/studio/sessions").status_code == 200
        assert client.get("/api/v1/performance").status_code == 200
        assert client.get("/api/v1/ai/usage").status_code == 200

        # V1 HTMX/Jinja2 HTML routes continue working
        assert client.get("/products").status_code == 200
        assert client.get("/approval").status_code == 200
