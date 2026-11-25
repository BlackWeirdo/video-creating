"""In-process FastAPI + Uvicorn Fake Muse Gateway (`vc-hardened`) for deterministic E2E tests."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from videocreator.pipeline.ffmpeg import run_ffmpeg


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _generate_sample_media(media_dir: Path) -> dict[str, Path]:
    media_dir.mkdir(parents=True, exist_ok=True)
    mp4 = media_dir / "sample.mp4"
    png = media_dir / "sample.png"
    mp3 = media_dir / "sample.mp3"
    if not mp4.exists():
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "color=c=0x1e293b:s=360x640:r=24:d=2.2",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=48000:duration=2.2",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-preset",
                "ultrafast",
                "-c:a",
                "aac",
                str(mp4),
            ]
        )
    if not png.exists():
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "color=c=0x0f766e:s=540x960:d=0.1",
                "-frames:v",
                "1",
                "-c:v",
                "png",
                str(png),
            ]
        )
    if not mp3.exists():
        wav_tmp = media_dir / "tmp_speech.wav"
        run_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=520:sample_rate=48000:duration=1.4",
                "-c:a",
                "pcm_s16le",
                str(wav_tmp),
            ]
        )
        # Try libmp3lame, fallback to wav bytes if minimal ffmpeg lacks mp3 encoder (ffmpeg decodes both!)
        try:
            run_ffmpeg(["-i", str(wav_tmp), "-c:a", "libmp3lame", "-q:a", "4", str(mp3)])
        except Exception:
            mp3.write_bytes(wav_tmp.read_bytes())
        wav_tmp.unlink(missing_ok=True)
    return {"mp4": mp4, "png": png, "mp3": mp3}


@dataclass
class FakeMuseGatewayState:
    media_files: dict[str, Path]
    cmd_mode: str = "off"
    hardened: bool = True
    auto_approve_pairing: bool = True
    polls_until_done: int = 0
    fail_restart_remaining: int = 0
    force_quota_429: bool = False
    chat_reply_json: dict[str, Any] = field(
        default_factory=lambda: {"headline": "Muse Test", "score": 9}
    )
    pool_strategy: str = "round-robin"
    accounts: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "id": "acc-1",
                "name": "studio.alpha@example.com",
                "cookies": "hatch_sess=SUPER_SECRET_COOKIE_ALPHA_999",
                "proxy": "http://user1:secretpass@10.0.0.5:8080",
                "enabled": True,
                "status": "ready",
                "cooldownRemainingMs": 0,
                "cooldownReason": "",
                "lanes": 2,
                "lastStatus": "valid",
            },
            {
                "id": "acc-2",
                "name": "studio.beta@example.com",
                "cookies": "hatch_sess=SUPER_SECRET_COOKIE_BETA_888",
                "proxy": None,
                "enabled": True,
                "status": "ready",
                "cooldownRemainingMs": 0,
                "cooldownReason": "",
                "lanes": 2,
                "lastStatus": "valid",
            },
        ]
    )
    combos: list[dict[str, Any]] = field(default_factory=list)
    keys: list[dict[str, Any]] = field(default_factory=list)
    settings: dict[str, Any] = field(
        default_factory=lambda: {
            "lanesMode": "auto",
            "lanesPerAccount": 2,
            "autoHealEnabled": True,
            "keepAliveEnabled": True,
            "keepAliveMin": 30,
            "maskEmails": True,
            "telegramBotToken": "SECRET_INTERNAL_GW_TG_TOKEN",
            "tunnelDashboardAccess": False,
        }
    )
    pair_requests: dict[str, dict[str, Any]] = field(default_factory=dict)
    tasks: dict[str, dict[str, Any]] = field(default_factory=dict)
    idempotency_map: dict[str, str] = field(default_factory=dict)
    submitted_payloads: list[dict[str, Any]] = field(default_factory=list)
    backup_restores: list[dict[str, Any]] = field(default_factory=list)
    max_running_observed: int = 0
    task_seq: int = 0


def build_fake_muse_app(state: FakeMuseGatewayState) -> FastAPI:
    app = FastAPI()

    def _running_count() -> int:
        return sum(1 for t in state.tasks.values() if t["status"] in ("queued", "running"))

    def _advance_task_if_ready(t: dict[str, Any]) -> dict[str, Any]:
        if t["status"] not in ("queued", "running"):
            return t
        t["_polls"] = int(t.get("_polls", 0)) + 1
        if t["_polls"] <= state.polls_until_done:
            return t

        prompt = str(t.get("prompt") or "")
        if "FAIL_ALWAYS_RESTART" in prompt:
            t["status"] = "failed"
            t["error"] = "Gateway restarted while this task was running."
            return t
        if "FAIL_ONCE_RESTART" in prompt and state.fail_restart_remaining > 0:
            state.fail_restart_remaining -= 1
            t["status"] = "failed"
            t["error"] = "Gateway restarted while this task was running."
            return t
        if "FAIL_QUOTA" in prompt:
            t["status"] = "failed"
            t["error"] = "Muse returned no media: rate limit / quota reached"
            return t

        t["status"] = "succeeded"
        kind = t["kind"]
        if kind == "video":
            partial = "PARTIAL_CLIP" in prompt
            t["partial"] = partial
            t["duration_sec"] = 2.2
            t["url"] = "/api/media/sample.mp4"
            t["media"] = [{"url": "/api/media/sample.mp4", "kind": "video", "duration_sec": 2.2}]
        elif kind == "image":
            cnt = max(1, int(t.get("count") or 1))
            t["url"] = "/api/media/sample.png"
            t["media"] = [{"url": "/api/media/sample.png", "kind": "image"} for _ in range(cnt)]
        elif kind == "audio":
            t["url"] = "/api/media/sample.mp3"
            t["media"] = [{"url": "/api/media/sample.mp3", "kind": "audio", "duration_sec": 1.4}]
        else:
            t["text"] = json.dumps(state.chat_reply_json)
        return t

    @app.get("/api/health")
    async def api_health() -> JSONResponse:
        return JSONResponse({"ok": True, "service": "muse", "ts": int(time.time() * 1000)})

    @app.get("/api/config")
    async def api_config() -> JSONResponse:
        return JSONResponse(
            {
                "cmdMode": state.cmd_mode,
                "hardened": state.hardened,
                "fork": "vc-hardened" if state.hardened else "upstream",
            }
        )

    @app.get("/api/pair")
    async def api_pair_discover() -> JSONResponse:
        ready = sum(
            1 for a in state.accounts if a.get("enabled", True) and a.get("status") == "ready"
        )
        return JSONResponse(
            {
                "service": "muse-gateway",
                "version": "1.0.13-vc",
                "licensed": True,
                "accounts": {"total": len(state.accounts), "ready": ready},
            }
        )

    @app.post("/api/pair")
    async def api_pair_start(req: Request) -> JSONResponse:
        body = await req.json()
        pid = f"pair-{len(state.pair_requests) + 1}"
        sec = f"psec-{pid}"
        state.pair_requests[pid] = {
            "id": pid,
            "secret": sec,
            "app": body.get("app") or "Video Creator V2",
            "code": "4829",
            "approved": state.auto_approve_pairing,
        }
        return JSONResponse(
            {
                "id": pid,
                "code": "4829",
                "secret": sec,
                "approve_url": f"http://127.0.0.1:{req.url.port}/pair/{pid}",
                "expires_in": 300,
            }
        )

    @app.get("/api/pair/{pair_id}")
    async def api_pair_poll(pair_id: str, req: Request) -> JSONResponse:
        rec = state.pair_requests.get(pair_id)
        if not rec or req.headers.get("X-Pair-Secret") != rec["secret"]:
            return JSONResponse({"error": "Not found"}, status_code=404)
        if not rec["approved"]:
            return JSONResponse({"status": "pending", "code": rec["code"]})
        raw_key = f"mgw_live_secret_key_{pair_id}_998877"
        key_id = f"key-{len(state.keys) + 1}"
        state.keys.append(
            {
                "id": key_id,
                "name": rec["app"],
                "key": raw_key,
                "enabled": True,
                "access": {"restricted": False, "models": []},
            }
        )
        return JSONResponse({"status": "approved", "api_key": raw_key, "code": rec["code"]})

    @app.get("/api/pool")
    async def api_pool_get() -> JSONResponse:
        return JSONResponse({"strategy": state.pool_strategy, "accounts": state.accounts})

    @app.patch("/api/pool")
    async def api_pool_patch(req: Request) -> JSONResponse:
        body = await req.json()
        if body.get("strategy"):
            state.pool_strategy = str(body["strategy"])
        aid = body.get("accountId")
        if aid:
            for a in state.accounts:
                if a["id"] == aid:
                    if "enabled" in body:
                        a["enabled"] = bool(body["enabled"])
                    if body.get("resetCooldown"):
                        a["status"] = "ready"
                        a["cooldownRemainingMs"] = 0
        return JSONResponse({"strategy": state.pool_strategy, "accounts": state.accounts})

    @app.post("/api/pool")
    async def api_pool_post() -> JSONResponse:
        return JSONResponse(
            {"results": [{"ok": True}], "state": {"strategy": state.pool_strategy, "accounts": state.accounts}}
        )

    @app.get("/api/sessions")
    async def api_sessions_get() -> JSONResponse:
        return JSONResponse(state.accounts)

    @app.post("/api/sessions")
    async def api_sessions_post(req: Request) -> JSONResponse:
        body = await req.json()
        new_acc = {
            "id": f"acc-{len(state.accounts) + 1}",
            "name": body.get("name") or "New Account",
            "cookies": body.get("cookies") or "",
            "proxy": None,
            "enabled": True,
            "status": "ready",
            "cooldownRemainingMs": 0,
            "lanes": 2,
        }
        state.accounts.append(new_acc)
        return JSONResponse({"success": True, "session": new_acc})

    @app.patch("/api/sessions/{acc_id}")
    async def api_sessions_patch(acc_id: str, req: Request) -> JSONResponse:
        body = await req.json()
        for a in state.accounts:
            if a["id"] == acc_id:
                if "proxy" in body:
                    a["proxy"] = body["proxy"]
                if "name" in body:
                    a["name"] = body["name"]
                return JSONResponse({"success": True, "session": a})
        return JSONResponse({"error": "Not found"}, status_code=404)

    @app.delete("/api/sessions/{acc_id}")
    async def api_sessions_delete(acc_id: str) -> JSONResponse:
        state.accounts = [a for a in state.accounts if a["id"] != acc_id]
        return JSONResponse({"success": True})

    @app.post("/api/sessions/test")
    async def api_sessions_test(req: Request) -> JSONResponse:
        body = await req.json()
        return JSONResponse({"id": body.get("id"), "valid": True, "lastStatus": "valid"})

    @app.post("/api/launch-browser")
    async def api_launch_browser() -> JSONResponse:
        return JSONResponse({"success": True, "browser": "chrome", "totalCookiesInjected": 4})

    @app.post("/api/login-capture")
    async def api_login_start() -> JSONResponse:
        return JSONResponse({"success": True, "jobId": "lc-1"})

    @app.get("/api/login-capture")
    async def api_login_poll() -> JSONResponse:
        return JSONResponse({"status": "done", "sessionId": "acc-1", "deduped": True})

    @app.delete("/api/login-capture")
    async def api_login_cancel() -> JSONResponse:
        return JSONResponse({"success": True})

    @app.get("/api/combos")
    async def api_combos_get() -> JSONResponse:
        return JSONResponse({"combos": state.combos})

    @app.post("/api/combos", status_code=201)
    async def api_combos_post(req: Request) -> JSONResponse:
        body = await req.json()
        cb = {
            "id": f"cb-{len(state.combos) + 1}",
            "name": body["name"],
            "accountIds": body.get("accountIds") or [],
            "strategy": body.get("strategy") or "round-robin",
            "kind": body.get("kind") or "video",
        }
        state.combos.append(cb)
        return JSONResponse(cb, status_code=201)

    @app.patch("/api/combos")
    async def api_combos_patch(req: Request) -> JSONResponse:
        body = await req.json()
        for c in state.combos:
            if c["id"] == body.get("id"):
                c.update({k: v for k, v in body.items() if k != "id"})
        return JSONResponse({"combos": state.combos})

    @app.delete("/api/combos")
    async def api_combos_del(req: Request) -> JSONResponse:
        cid = req.query_params.get("id")
        state.combos = [c for c in state.combos if c["id"] != cid]
        return JSONResponse({"combos": state.combos})

    @app.get("/api/settings")
    async def api_settings_get() -> JSONResponse:
        return JSONResponse(state.settings)

    @app.patch("/api/settings")
    async def api_settings_patch(req: Request) -> JSONResponse:
        body = await req.json()
        state.settings.update(body)
        return JSONResponse(state.settings)

    @app.get("/api/keys")
    async def api_keys_get() -> JSONResponse:
        masked = [
            {**k, "key": f"{k['key'][:10]}…{k['key'][-4:]}"} for k in state.keys
        ]
        return JSONResponse({"keys": masked, "authRequired": bool(state.keys), "requireAuth": True})

    @app.patch("/api/keys")
    async def api_keys_patch(req: Request) -> JSONResponse:
        body = await req.json()
        kid = body.get("id")
        for k in state.keys:
            if k["id"] == kid:
                if "access" in body:
                    k["access"] = body["access"]
                if "enabled" in body:
                    k["enabled"] = bool(body["enabled"])
        return JSONResponse({"ok": True})

    @app.get("/api/usage")
    async def api_usage(req: Request) -> Response:
        rk = req.query_params.get("range") or "today"
        if req.query_params.get("format") == "csv":
            return PlainTextResponse("time,account,model,status\n2026-11-25,acc-1,muse-video,ok\n")
        return JSONResponse({"range": rk, "totals": {"requests": len(state.tasks), "ok": len(state.tasks), "failed": 0}})

    @app.get("/api/overview")
    async def api_overview() -> JSONResponse:
        return JSONResponse({"uptimeSec": 120, "activeTasks": _running_count()})

    @app.delete("/api/tasks")
    async def api_tasks_cleanup() -> JSONResponse:
        return JSONResponse({"removed": 2})

    @app.get("/api/update")
    async def api_update_check() -> JSONResponse:
        return JSONResponse({"current": "1.0.13", "latest": "1.0.13", "upToDate": True})

    @app.post("/api/update")
    async def api_update_post() -> JSONResponse:
        return JSONResponse({"error": "auto-update disabled in vc-hardened"}, status_code=403)

    @app.get("/api/backup")
    async def api_backup_get() -> JSONResponse:
        return JSONResponse(
            {
                "version": 2,
                "app": "muse-router",
                "files": {"sessions.json": state.accounts, "pool.json": {"strategy": state.pool_strategy}},
            }
        )

    @app.post("/api/backup")
    async def api_backup_post(req: Request) -> JSONResponse:
        body = await req.json()
        state.backup_restores.append(body)
        return JSONResponse({"success": True, "restored": list((body.get("files") or {}).keys())})

    @app.get("/api/media/{name}")
    async def api_media(name: str) -> Response:
        if name.endswith(".png"):
            return Response(state.media_files["png"].read_bytes(), media_type="image/png")
        if name.endswith(".mp3"):
            return Response(state.media_files["mp3"].read_bytes(), media_type="audio/mpeg")
        return Response(state.media_files["mp4"].read_bytes(), media_type="video/mp4")

    @app.get("/v1/models")
    async def v1_models() -> JSONResponse:
        base = [
            {"id": "muse-video", "kind": "video"},
            {"id": "muse-image", "kind": "image"},
            {"id": "muse-voice", "kind": "audio"},
            {"id": "muse-chat", "kind": "chat"},
        ]
        extra = [{"id": c["name"], "kind": c.get("kind", "video")} for c in state.combos]
        return JSONResponse({"data": [*base, *extra]})

    @app.post("/v1/tasks", status_code=202)
    async def v1_tasks_create(req: Request) -> JSONResponse:
        if state.force_quota_429:
            return JSONResponse({"error": "All Muse accounts cooling down"}, status_code=429)
        body = await req.json()
        state.submitted_payloads.append(body)
        idem = str(body.get("idempotency_key") or "")
        if idem and idem in state.idempotency_map:
            return JSONResponse(state.tasks[state.idempotency_map[idem]], status_code=202)

        model = str(body.get("model") or "muse-video")
        kind = (
            "image"
            if "image" in model or body.get("count")
            else ("audio" if "voice" in model or body.get("voice") else "video")
        )
        state.task_seq += 1
        tid = f"gw-task-{state.task_seq}"
        t_obj = {
            "id": tid,
            "status": "running",
            "model": model,
            "kind": kind,
            "prompt": body.get("prompt") or "",
            "count": body.get("count"),
            "partial": False,
            "thread_url": body.get("thread") or f"https://muse.ai/t/thread-{state.task_seq}",
            "account_id": body.get("account") or "acc-1",
            "webhook_url": body.get("webhook_url"),
            "webhook_secret": body.get("webhook_secret"),
            "_polls": 0,
        }
        state.tasks[tid] = t_obj
        if idem:
            state.idempotency_map[idem] = tid
        state.max_running_observed = max(state.max_running_observed, _running_count())
        return JSONResponse(t_obj, status_code=202)

    @app.get("/v1/tasks")
    async def v1_tasks_list() -> JSONResponse:
        out = [_advance_task_if_ready(t) for t in state.tasks.values()]
        return JSONResponse({"data": out})

    @app.get("/v1/tasks/{tid}")
    async def v1_tasks_get(tid: str) -> JSONResponse:
        t = state.tasks.get(tid)
        if not t:
            return JSONResponse({"error": "Task not found"}, status_code=404)
        return JSONResponse(_advance_task_if_ready(t))

    @app.delete("/v1/tasks/{tid}")
    async def v1_tasks_cancel(tid: str) -> JSONResponse:
        t = state.tasks.get(tid)
        if t:
            t["status"] = "cancelled"
        return JSONResponse({"id": tid, "status": "cancelled"})

    @app.post("/v1/images/generations")
    async def v1_images_gen(req: Request) -> JSONResponse:
        body = await req.json()
        state.submitted_payloads.append(body)
        n = max(1, min(4, int(body.get("n") or 1)))
        b64 = base64.b64encode(state.media_files["png"].read_bytes()).decode("ascii")
        return JSONResponse({"data": [{"b64_json": b64} for _ in range(n)]})

    @app.post("/v1/audio/speech")
    async def v1_audio_speech(req: Request) -> Response:
        body = await req.json()
        state.submitted_payloads.append(body)
        return Response(state.media_files["mp3"].read_bytes(), media_type="audio/mpeg")

    @app.post("/v1/chat/completions")
    async def v1_chat(req: Request) -> JSONResponse:
        body = await req.json()
        state.submitted_payloads.append(body)
        return JSONResponse(
            {
                "id": "chatcmpl-muse-1",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(state.chat_reply_json, ensure_ascii=False),
                        },
                    }
                ],
            }
        )

    return app


class FakeMuseGatewayServer:
    """Context manager running `build_fake_muse_app` on a free loopback port."""

    def __init__(self, tmp_dir: Path) -> None:
        self.port = _pick_free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        media = _generate_sample_media(tmp_dir / "fake_gw_media")
        self.state = FakeMuseGatewayState(media_files=media)
        self._app = build_fake_muse_app(self.state)
        cfg = uvicorn.Config(self._app, host="127.0.0.1", port=self.port, log_level="error")
        self._server = uvicorn.Server(cfg)
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def __enter__(self) -> FakeMuseGatewayServer:
        self._thread.start()
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            try:
                r = httpx.get(f"{self.base_url}/api/health", timeout=1.0, trust_env=False)
                if r.status_code == 200:
                    return self
            except httpx.RequestError:
                time.sleep(0.05)
        raise RuntimeError("FakeMuseGatewayServer failed to start")

    def __exit__(self, *_: object) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5.0)

    def deliver_signed_webhook(
        self, app_webhook_url: str, gateway_task_id: str, secret: str, *, event: str = "task.succeeded"
    ) -> httpx.Response:
        t = self.state.tasks[gateway_task_id]
        if event == "task.succeeded":
            t["status"] = "succeeded"
            t["url"] = "/api/media/sample.mp4"
            t["media"] = [{"url": "/api/media/sample.mp4", "kind": "video", "duration_sec": 2.2}]
        raw = json.dumps({"event": event, "task": t}).encode("utf-8")
        sig = "sha256=" + hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
        return httpx.post(
            app_webhook_url,
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Muse-Event": event,
                "X-Muse-Task-Id": gateway_task_id,
                "X-Muse-Signature": sig,
            },
            timeout=10.0,
            trust_env=False,
        )
