"""Muse Storyboard continuity, Image/TTS/Chat providers, content_policy, Admin secret-stripping & Sidecar E2E tests."""
from __future__ import annotations

import socket
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from fakes.fake_muse_gateway import FakeMuseGatewayServer
from videocreator.ai.providers import build_single_provider
from videocreator.app import create_app
from videocreator.config import load_settings, save_settings
from videocreator.db import migrate, query_one
from videocreator.muse_gateway.dispatcher import run_muse_dispatcher_tick
from videocreator.muse_gateway.sidecar import (
    ensure_muse_sidecar_running,
    stop_muse_sidecar,
)
from videocreator.muse_gateway.storyboard import (
    assemble_storyboard,
    create_storyboard,
    start_storyboard_generation,
)
from videocreator.paths import AppPaths
from videocreator.pipeline.ai_images import generate_ai_image
from videocreator.pipeline.broll_generate import generate_broll
from videocreator.pipeline.news_studio import create_news_project, render_news_project
from videocreator.pipeline.probe import probe_duration
from videocreator.transfer import export_config_bundle, import_config_bundle
from videocreator.tts.synthesizer import synthesize_speech_segments
from videocreator.workspaces import create_workspace

pytestmark = pytest.mark.local


class _SampleWriterSchema(BaseModel):
    headline: str
    score: int


def _setup_app_with_fake(tmp_path: Path, base_url: str) -> tuple[AppPaths, int]:
    paths = AppPaths(tmp_path / "studio_data")
    paths.ensure_dirs()
    migrate(paths.db_file)
    ws_ai = int(create_workspace(paths.db_file, name="Full AI Studio", content_policy="full_ai"))
    cfg = load_settings(paths.config_file)
    cfg.muse_gateway.enabled = True
    cfg.muse_gateway.base_url = base_url
    save_settings(paths.config_file, cfg)
    return paths, ws_ai


def test_storyboard_continuity_frame_bridging_and_qc_render(tmp_path: Path) -> None:
    # Scenario 9: Scene 1 sends thread + account + PNG data URL of scene 0's last frame, then assembles MP4
    with FakeMuseGatewayServer(tmp_path) as gw:
        paths, ws_ai = _setup_app_with_fake(tmp_path, gw.base_url)
        cfg = load_settings(paths.config_file)
        cfg.voice.vi_provider = "test_tone"
        save_settings(paths.config_file, cfg)

        sb = create_storyboard(
            paths,
            workspace_id=ws_ai,
            title="Hành trình 2 cảnh liền mạch",
            continuity=True,
            segments=[
                {"prompt": "Cảnh 1 mở đầu PARTIAL_CLIP", "duration_sec": 4, "caption": "Mở đầu câu chuyện hôm nay"},
                {"prompt": "Cảnh 2 nối tiếp khung cuối", "duration_sec": 4, "caption": "Tiếp nối diễn biến hấp dẫn"},
            ],
        )
        start_storyboard_generation(paths, int(sb["id"]))

        # Tick 1 submits scene 0; Tick 2 imports scene 0 -> hook extracts last frame & enqueues scene 1;
        # Tick 3 submits scene 1; Tick 4 imports scene 1 -> marks assembling!
        for _ in range(4):
            run_muse_dispatcher_tick(paths)

        assert len(gw.state.submitted_payloads) == 2
        scene1_payload = gw.state.submitted_payloads[1]
        assert scene1_payload["new_chat"] is False
        assert scene1_payload["thread"].startswith("https://muse.ai/t/")
        assert scene1_payload["account"] == "acc-1"
        assert scene1_payload["images"][0].startswith("data:image/png;base64,")

        assembled = assemble_storyboard(paths, int(sb["id"]))
        assert assembled["status"] == "completed"
        assert assembled["output_video_id"] is not None
        assert "muse_video_partial" in assembled["simulation_flags"]
        v_row = query_one(paths.db_file, "SELECT status, qc_json, output_path FROM videos WHERE id = ?", (assembled["output_video_id"],))
        assert v_row is not None
        assert (paths.media_dir / str(v_row["output_path"])).is_file()


def test_muse_image_fallback_tts_engine_and_chat_provider(tmp_path: Path) -> None:
    # Scenarios 10, 11, 12
    with FakeMuseGatewayServer(tmp_path) as gw:
        paths, ws_ai = _setup_app_with_fake(tmp_path, gw.base_url)

        # Scenario 10a: Imagen has no API key -> falls back to Muse Image with simulation_flags == []
        img = generate_ai_image(
            paths,
            workspace_id=ws_ai,
            prompt="Phòng thu hiện đại",
            aspect_ratio="9:16",
            animate_to_shot=False,
        )
        assert img["provider"] == "muse_image"
        assert img["simulation_flags"] == []
        assert (paths.media_dir / str(img["image_path"])).is_file()

        # Scenario 11: TTS vi_provider='muse' produces 48kHz trimmed WAV
        track, warnings = synthesize_speech_segments(
            [("Xin chào quý vị khán giả", 2.5)],
            lang="vi",
            voice="muse:Glad Kite",
            provider_name="muse",
            work_dir=tmp_path / "tts_muse",
            paths=paths,
        )
        assert track.provider == "muse"
        assert warnings == []
        assert track.audio_path.is_file()
        assert probe_duration(track.audio_path) > 0.1

        # Scenario 12: Chat provider returns validated Pydantic JSON & records $0 subscription usage
        gw.state.chat_reply_json = {"headline": "Điểm tin AI 2026", "score": 10}
        settings = load_settings(paths.config_file)
        chat_prov = build_single_provider("muse_gateway", paths, settings, role="writer")
        parsed = chat_prov.generate_json("Tóm tắt tin <cwd>C:\\secret</cwd>", _SampleWriterSchema)
        assert parsed.headline == "Điểm tin AI 2026"
        assert parsed.score == 10
        assert "secret" not in str(gw.state.submitted_payloads[-1])
        u_row = query_one(
            paths.db_file,
            "SELECT route, cost_usd FROM ai_usage WHERE provider = 'muse_gateway' ORDER BY id DESC LIMIT 1",
        )
        assert u_row is not None
        assert u_row["route"] == "subscription"
        assert float(u_row["cost_usd"]) == 0.0

    # Scenario 10b: Gateway now offline -> generate_ai_image falls back to local canvas with flag
    offline_img = generate_ai_image(
        paths,
        workspace_id=ws_ai,
        prompt="Khi gateway tắt",
        aspect_ratio="9:16",
        animate_to_shot=False,
    )
    assert offline_img["provider"] == "local_card"
    assert "ai_image_canvas_placeholder" in offline_img["simulation_flags"]

    # Scenario 11b: Gateway offline -> TTS 'muse' falls back cleanly to Edge/VieNeu
    import videocreator.tts.synthesizer as synth_mod
    from videocreator.tts.local_waveform import synthesize_local_waveform

    orig_edge = synth_mod.synthesize_edge_python_or_cli
    try:
        synth_mod.synthesize_edge_python_or_cli = lambda txt, voice, work_dir, **kw: synthesize_local_waveform(
            [(txt, 1.8)], work_dir=work_dir
        )
        fb_track, _ = synthesize_speech_segments(
            [("Dự phòng khi Muse tắt", 1.8)],
            lang="vi",
            voice="muse:Glad Kite",
            provider_name="muse",
            work_dir=tmp_path / "tts_muse_fb",
            paths=paths,
        )
        assert fb_track.audio_path.is_file()
    finally:
        synth_mod.synthesize_edge_python_or_cli = orig_edge


def test_content_policy_guards_news_nonblocking_resume_and_admin_secret_stripping(
    tmp_path: Path,
) -> None:
    # Scenarios 13 & 14 + News Studio non-blocking waiting_media -> completed resume + .vcx backup
    with FakeMuseGatewayServer(tmp_path) as gw:
        app = create_app(data_dir=tmp_path / "policy_app", start_worker=False)
        paths: AppPaths = app.state.paths
        ws_ai = int(create_workspace(paths.db_file, name="AI WS", content_policy="full_ai"))
        cfg = load_settings(paths.config_file)
        cfg.muse_gateway.enabled = True
        cfg.muse_gateway.base_url = gw.base_url
        cfg.muse_gateway.include_in_vcx_backup = True
        cfg.voice.vi_provider = "test_tone"
        save_settings(paths.config_file, cfg)

        # Scenario 13: strict_footage (workspace 1) blocks storyboard & product ref (403), allows B-roll!
        broll_res = generate_broll(
            paths, prompt="Cảnh mây trời thiên nhiên", seconds=6, source="muse", workspace_id=1
        )
        assert broll_res["mode"] == "muse_queued"

        with TestClient(app) as tc:
            sb_forbidden = tc.post(
                "/api/v1/muse/storyboards",
                json={
                    "workspace_id": 1,
                    "title": "Blocked on strict",
                    "segments": [{"prompt": "Test", "duration_sec": 6}],
                },
            )
            assert sb_forbidden.status_code == 403

            prod_forbidden = tc.post(
                "/api/v1/muse/tasks",
                json={
                    "workspace_id": 1,
                    "kind": "video",
                    "prompt": "Product AI forbidden",
                    "refs": [{"type": "product", "id": 1}],
                },
            )
            assert prod_forbidden.status_code == 403

            # Scenario 14: Admin accounts strips cookies & masks proxy credentials; settings strips telegram token
            acc_r = tc.get("/api/v1/muse/admin/accounts")
            assert acc_r.status_code == 200
            assert "SUPER_SECRET_COOKIE" not in acc_r.text
            assert "secretpass" not in acc_r.text
            assert "***@" in (acc_r.json()["accounts"][0]["proxy"] or "")

            set_r = tc.get("/api/v1/muse/admin/settings")
            assert set_r.status_code == 200
            assert "SECRET_INTERNAL_GW_TG_TOKEN" not in set_r.text

            keys_r = tc.get("/api/v1/muse/admin/keys")
            assert keys_r.status_code == 200

            # Remote mode rejects /api/v1/muse/admin/* with 403
            cfg_rem = load_settings(paths.config_file)
            cfg_rem.muse_gateway.mode = "remote"
            cfg_rem.muse_gateway.base_url = "https://muse.tailnet.ts.net"
            cfg_rem.muse_gateway.remote_hardened_confirmed = True
            save_settings(paths.config_file, cfg_rem)
            rem_r = tc.get("/api/v1/muse/admin/accounts")
            assert rem_r.status_code == 403

            # Restore local_sidecar mode
            cfg_rem.muse_gateway.mode = "local_sidecar"
            cfg_rem.muse_gateway.base_url = gw.base_url
            save_settings(paths.config_file, cfg_rem)

        # News Studio non-blocking waiting_media -> dispatcher tick -> completed render
        np = create_news_project(
            paths,
            workspace_id=ws_ai,
            title="Bản tin Muse",
            raw_text="Doanh thu ngành bán dẫn tăng 42% trong quý 4 năm 2026.",
            visual_source="muse_video",
        )
        parked = render_news_project(paths, int(np["id"]), build_pack=False)
        assert parked["status"] == "waiting_media"
        run_muse_dispatcher_tick(paths)
        run_muse_dispatcher_tick(paths)
        finished_np = render_news_project(paths, int(np["id"]), build_pack=False)
        assert finished_np["status"] == "completed"
        assert finished_np["output_video_id"] is not None

        # Encrypted .vcx export & restore with Muse Gateway backup embedded
        vcx_file = tmp_path / "bundle_with_muse.vcx"
        export_config_bundle(paths, "pass1234", vcx_file)
        raw_zip_bytes = vcx_file.read_bytes()
        assert b"SUPER_SECRET_COOKIE" not in raw_zip_bytes  # encrypted inside Fernet!
        import_config_bundle(paths, vcx_file, "pass1234")
        assert len(gw.state.backup_restores) == 1


@pytest.mark.slow
def test_sidecar_attaches_and_spawns_fake_node_entry(tmp_path: Path) -> None:
    # Scenario 15: Sidecar attach + spawn fake Node server
    with FakeMuseGatewayServer(tmp_path) as gw:
        paths = AppPaths(tmp_path / "sc_attach")
        paths.ensure_dirs()
        migrate(paths.db_file)
        cfg = load_settings(paths.config_file)
        cfg.muse_gateway.enabled = True
        cfg.muse_gateway.base_url = gw.base_url
        save_settings(paths.config_file, cfg)

        attached = ensure_muse_sidecar_running(paths, timeout_s=5.0)
        assert attached["running"] is True
        assert attached["attached"] is True
        assert stop_muse_sidecar(paths, only_if_owned=True) is False

    # Spawn a standalone fake Node.js gateway script
    fake_dir = tmp_path / "fake_gw_pkg" / "app"
    fake_dir.mkdir(parents=True, exist_ok=True)
    server_js = fake_dir / "server.js"
    server_js.write_text(
        """
const http = require('http');
const port = Number(process.env.PORT || 1412);
const srv = http.createServer((req, res) => {
  res.setHeader('Content-Type', 'application/json');
  if (req.url.startsWith('/api/health')) {
    res.end(JSON.stringify({ ok: true, service: 'muse' }));
  } else if (req.url.startsWith('/api/config')) {
    res.end(JSON.stringify({ cmdMode: process.env.MUSE_CMD_MODE || 'off', hardened: true, fork: 'vc-hardened' }));
  } else if (req.url.startsWith('/api/pair')) {
    res.end(JSON.stringify({ service: 'muse-gateway', version: '1.0.13-vc', accounts: { total: 1, ready: 1 } }));
  } else {
    res.statusCode = 404;
    res.end('{}');
  }
});
srv.listen(port, '127.0.0.1');
""",
        encoding="utf-8",
    )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        free_port = int(s.getsockname()[1])

    paths2 = AppPaths(tmp_path / "sc_spawn")
    paths2.ensure_dirs()
    migrate(paths2.db_file)
    cfg2 = load_settings(paths2.config_file)
    cfg2.muse_gateway.enabled = True
    cfg2.muse_gateway.sidecar.port = free_port
    cfg2.muse_gateway.base_url = f"http://127.0.0.1:{free_port}"
    cfg2.muse_gateway.sidecar.gateway_entry = str(server_js)
    save_settings(paths2.config_file, cfg2)

    try:
        spawned = ensure_muse_sidecar_running(paths2, timeout_s=10.0)
        assert spawned["running"] is True
        assert spawned["owned"] is True
        assert spawned["hardened"] is True
    finally:
        assert stop_muse_sidecar(paths2, only_if_owned=True) is True
