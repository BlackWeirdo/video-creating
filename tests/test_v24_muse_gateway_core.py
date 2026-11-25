"""Core Muse Gateway security, pairing, multi-lane dispatcher, retry, quota, import & webhook tests."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fakes.fake_muse_gateway import FakeMuseGatewayServer
from videocreator.app import create_app
from videocreator.config import load_settings, save_settings
from videocreator.db import migrate, query_one
from videocreator.muse_gateway.dispatcher import run_muse_dispatcher_tick
from videocreator.muse_gateway.security import sanitize_prompt
from videocreator.muse_gateway.store import (
    create_muse_task,
    get_muse_task,
    list_tasks_by_status,
)
from videocreator.paths import AppPaths
from videocreator.pipeline.probe import probe_video
from videocreator.secrets_store import SecretsStore
from videocreator.workspaces import create_workspace

pytestmark = pytest.mark.local


def _init_paths_for_fake(tmp_path: Path, base_url: str) -> AppPaths:
    paths = AppPaths(tmp_path / "app_data")
    paths.ensure_dirs()
    migrate(paths.db_file)
    cfg = load_settings(paths.config_file)
    cfg.muse_gateway.enabled = True
    cfg.muse_gateway.mode = "local_sidecar"
    cfg.muse_gateway.base_url = base_url
    cfg.muse_gateway.max_parallel = 4
    cfg.muse_gateway.renders_per_account = 2
    cfg.muse_gateway.max_attempts = 3
    save_settings(paths.config_file, cfg)
    return paths


def test_sanitize_prompt_and_unhardened_gateway_refusal(tmp_path: Path) -> None:
    # Scenario 2: sanitize_prompt strips <cwd> and <environment_context>
    dirty = "Tạo cảnh bàn trà <cwd>C:\\secret\\repo</cwd> <environment_context>KEY=123</environment_context>\x07 đẹp"
    cleaned = sanitize_prompt(dirty)
    assert "secret" not in cleaned
    assert "KEY=123" not in cleaned
    assert "\x07" not in cleaned
    assert "Tạo cảnh bàn trà" in cleaned

    # Scenario 1: assert_hardened refuses cmdMode=auto and submits zero tasks
    with FakeMuseGatewayServer(tmp_path) as gw:
        gw.state.cmd_mode = "auto"
        gw.state.hardened = False
        paths = _init_paths_for_fake(tmp_path, gw.base_url)
        create_muse_task(paths.db_file, workspace_id=1, kind="video", prompt="Test unsafe")

        res = run_muse_dispatcher_tick(paths)
        assert res["online"] is False
        assert "cmdMode" in res["error"] or "hardened" in res["error"]
        assert len(gw.state.submitted_payloads) == 0


def test_one_click_pairing_saves_secret_without_leaking_and_restricts_models(
    tmp_path: Path,
) -> None:
    # Scenario 3
    with FakeMuseGatewayServer(tmp_path) as gw:
        gw.state.combos.append({"id": "cb-1", "name": "muse-pro-combo", "accountIds": ["acc-1"], "strategy": "round-robin"})
        app = create_app(data_dir=tmp_path / "pair_app", start_worker=False)
        paths: AppPaths = app.state.paths
        cfg = load_settings(paths.config_file)
        cfg.muse_gateway.enabled = True
        cfg.muse_gateway.base_url = gw.base_url
        save_settings(paths.config_file, cfg)

        with TestClient(app) as tc:
            start_r = tc.post("/api/v1/muse/pair", json={"app_name": "Video Creator V2"})
            assert start_r.status_code == 200
            pair_id = start_r.json()["pair_id"]
            assert "secret" not in start_r.json()

            poll_r = tc.get(f"/api/v1/muse/pair/{pair_id}")
            assert poll_r.status_code == 200
            body = poll_r.json()
            assert body["status"] == "approved"
            assert body["key_saved"] is True
            assert "api_key" not in body
            assert "mgw_live_secret_key" not in poll_r.text

        sec = SecretsStore(paths.secrets_file)
        assert sec.has("MUSE_GATEWAY_API_KEY")
        assert sec.has("MUSE_GATEWAY_WEBHOOK_SECRET")
        assert gw.state.keys[-1]["access"]["restricted"] is True
        assert "muse-video" in gw.state.keys[-1]["access"]["models"]
        assert "muse-pro-combo" in gw.state.keys[-1]["access"]["models"]


def test_dispatcher_capacity_ceiling_workspace_fairness_and_priority(
    tmp_path: Path,
) -> None:
    # Scenario 4: 10 tasks across 2 workspaces with capacity 4 -> never > 4 submitted, interleaved fairly
    with FakeMuseGatewayServer(tmp_path) as gw:
        gw.state.polls_until_done = 5  # keep tasks running across initial ticks
        paths = _init_paths_for_fake(tmp_path, gw.base_url)
        ws2 = int(create_workspace(paths.db_file, name="WS Beta", content_policy="full_ai"))

        for i in range(5):
            create_muse_task(paths.db_file, workspace_id=1, kind="video", prompt=f"WS1 clip {i}")
        for i in range(4):
            create_muse_task(paths.db_file, workspace_id=ws2, kind="video", prompt=f"WS2 clip {i}")
        high = create_muse_task(
            paths.db_file, workspace_id=ws2, kind="video", prompt="WS2 URGENT", priority=99
        )

        tick1 = run_muse_dispatcher_tick(paths)
        assert tick1["submitted_now"] == 4
        submitted = list_tasks_by_status(paths.db_file, "submitted")
        assert len(submitted) == 4
        # Highest priority task must be picked first, and both workspaces must be represented!
        sub_ids = [int(r["id"]) for r in submitted]
        sub_ws = {int(r["workspace_id"]) for r in submitted}
        assert int(high["id"]) in sub_ids
        assert sub_ws == {1, ws2}

        # Second tick while all 4 are still running must submit 0 more tasks
        tick2 = run_muse_dispatcher_tick(paths)
        assert tick2["submitted_now"] == 0
        assert len(list_tasks_by_status(paths.db_file, "submitted")) == 4
        assert gw.state.max_running_observed <= 4


def test_retry_changes_idempotency_key_and_stops_at_max_attempts(tmp_path: Path) -> None:
    # Scenario 5
    with FakeMuseGatewayServer(tmp_path) as gw:
        paths = _init_paths_for_fake(tmp_path, gw.base_url)
        gw.state.fail_restart_remaining = 1

        t_recover = create_muse_task(
            paths.db_file, workspace_id=1, kind="video", prompt="Clip FAIL_ONCE_RESTART"
        )
        run_muse_dispatcher_tick(paths)  # submit attempt 0
        run_muse_dispatcher_tick(paths)  # poll -> fails restarted -> attempt=1, pending + submits attempt 1!
        run_muse_dispatcher_tick(paths)  # poll attempt 1 -> succeeds!

        done = get_muse_task(paths.db_file, int(t_recover["id"]))
        assert done is not None
        assert done["status"] == "succeeded"
        assert done["attempt"] == 1
        keys_sent = [p["idempotency_key"] for p in gw.state.submitted_payloads]
        assert f"vc-1-{t_recover['id']}-a0" in keys_sent
        assert f"vc-1-{t_recover['id']}-a1" in keys_sent

        # Task that always crashes on restart stops at max_attempts (3)
        t_always = create_muse_task(
            paths.db_file, workspace_id=1, kind="video", prompt="Clip FAIL_ALWAYS_RESTART"
        )
        for _ in range(7):
            run_muse_dispatcher_tick(paths)
        exhausted = get_muse_task(paths.db_file, int(t_always["id"]))
        assert exhausted is not None
        assert exhausted["status"] == "failed"
        assert exhausted["attempt"] == 2  # attempts 0, 1, 2 = 3 total tries


def test_quota_cooldown_and_daily_cap_parking(tmp_path: Path) -> None:
    # Scenario 6
    with FakeMuseGatewayServer(tmp_path) as gw:
        paths = _init_paths_for_fake(tmp_path, gw.base_url)
        gw.state.force_quota_429 = True
        t1 = create_muse_task(paths.db_file, workspace_id=1, kind="video", prompt="Quota test")
        run_muse_dispatcher_tick(paths)
        parked = get_muse_task(paths.db_file, int(t1["id"]))
        assert parked is not None
        assert parked["status"] == "waiting_quota"
        assert parked["retry_after"] is not None

        # Daily per-account cap enforcement
        gw.state.force_quota_429 = False
        cfg = load_settings(paths.config_file)
        cfg.muse_gateway.daily_cap_video_per_account = 1  # 2 accounts * 1 = 2 videos/day max
        save_settings(paths.config_file, cfg)

        c1 = create_muse_task(paths.db_file, workspace_id=1, kind="video", prompt="Cap 1")
        c2 = create_muse_task(paths.db_file, workspace_id=1, kind="video", prompt="Cap 2")
        c3 = create_muse_task(paths.db_file, workspace_id=1, kind="video", prompt="Cap 3 over limit")
        run_muse_dispatcher_tick(paths)
        assert get_muse_task(paths.db_file, int(c1["id"]))["status"] == "submitted"  # type: ignore[index]
        assert get_muse_task(paths.db_file, int(c2["id"]))["status"] == "submitted"  # type: ignore[index]
        over = get_muse_task(paths.db_file, int(c3["id"]))
        assert over is not None and over["status"] == "waiting_quota"


def test_video_import_probe_partial_flag_and_signed_webhook(tmp_path: Path) -> None:
    # Scenarios 7 & 8
    with FakeMuseGatewayServer(tmp_path) as gw:
        app = create_app(data_dir=tmp_path / "wh_app", start_worker=False)
        paths: AppPaths = app.state.paths
        cfg = load_settings(paths.config_file)
        cfg.muse_gateway.enabled = True
        cfg.muse_gateway.base_url = gw.base_url
        save_settings(paths.config_file, cfg)
        sec = SecretsStore(paths.secrets_file)
        sec.set("MUSE_GATEWAY_WEBHOOK_SECRET", "whsec_test_secret_123")

        t_part = create_muse_task(
            paths.db_file, workspace_id=1, kind="video", prompt="Clip PARTIAL_CLIP"
        )
        gw.state.polls_until_done = 5  # keep running until webhook arrives
        run_muse_dispatcher_tick(paths)
        sub_row = get_muse_task(paths.db_file, int(t_part["id"]))
        assert sub_row is not None and sub_row["gateway_task_id"]
        gw_id = str(sub_row["gateway_task_id"])

        with TestClient(app) as tc:
            # Invalid signature -> 401
            bad_r = tc.post(
                "/api/v1/integrations/muse/webhook",
                content=b'{"event":"task.succeeded"}',
                headers={"X-Muse-Signature": "sha256=deadbeef"},
            )
            assert bad_r.status_code == 401

            # Valid HMAC signature -> imports video into shots + assets!
            gw.state.tasks[gw_id]["status"] = "succeeded"
            gw.state.tasks[gw_id]["partial"] = True
            gw.state.tasks[gw_id]["url"] = "/api/media/sample.mp4"
            gw.state.tasks[gw_id]["media"] = [
                {"url": "/api/media/sample.mp4", "kind": "video", "duration_sec": 2.2}
            ]
            import hashlib
            import hmac
            import json

            raw = json.dumps({"event": "task.succeeded", "task": gw.state.tasks[gw_id]}).encode("utf-8")
            sig = "sha256=" + hmac.new(b"whsec_test_secret_123", raw, hashlib.sha256).hexdigest()

            ok1 = tc.post(
                "/api/v1/integrations/muse/webhook",
                content=raw,
                headers={"X-Muse-Signature": sig},
            )
            assert ok1.status_code == 200
            assert ok1.json()["handled"] is True

            # Duplicate webhook delivery is idempotent!
            ok2 = tc.post(
                "/api/v1/integrations/muse/webhook",
                content=raw,
                headers={"X-Muse-Signature": sig},
            )
            assert ok2.status_code == 200
            assert ok2.json()["handled"] is False

        imported = get_muse_task(paths.db_file, int(t_part["id"]))
        assert imported is not None
        assert imported["status"] == "succeeded"
        assert imported["partial"] is True
        assert imported["shot_id"] is not None
        shot_row = query_one(paths.db_file, "SELECT * FROM shots WHERE id = ?", (imported["shot_id"],))
        assert shot_row is not None and int(shot_row["has_product"]) == 0
        mp4_file = paths.media_dir / str(imported["local_path"])
        assert mp4_file.is_file()
        assert probe_video(mp4_file).duration_s > 1.0
