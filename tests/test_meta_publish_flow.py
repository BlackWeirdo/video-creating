"""Facebook Reels and Instagram publish flows against a real local HTTP server.

The server is a real `http.server` on 127.0.0.1 that answers like the Graph API does per Meta's
Reels Publishing guide (status phases, `{"success": true}`), including the failure that matters:
the publish reply is lost after Meta already published. The posters run unchanged; only their
base URLs point at this server. Real SQLite. Replace with recorded live responses after S2/S3.
"""
from __future__ import annotations

import json
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from videocreator.db import get_conn, migrate, query_one
from videocreator.paths import get_paths
from videocreator.posting import facebook, instagram, meta_published
from videocreator.posting.base import TransientPostError
from videocreator.secrets_store import SecretsStore

CLIP = Path(__file__).resolve().parent / "samples" / "clip1_6s.mp4"


class MetaState:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.uploaded = False
        self.published = False
        self.drop_first_finish = True  # Meta publishes, but the reply never arrives
        self.status_lags = False  # after a lost finish, status does not show it yet
        self.ig_status = "FINISHED"


def _start_server(state: MetaState) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def _json(self, payload: dict) -> None:
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            fields = parse_qs(url.query).get("fields", [""])[0]
            if url.path == "/graph/991" and fields == "status":
                state.calls.append("status")
                published = state.published and not state.status_lags
                return self._json({"id": "991", "status": {
                    "video_status": "ready" if published else ("upload_complete" if state.uploaded else "uploading"),
                    "uploading_phase": {"status": "complete" if state.uploaded else "not_started"},
                    "publishing_phase": {"status": "complete" if published else "not_started",
                                         "publish_status": "published" if published else "draft"},
                }})
            if url.path == "/graph/991" and fields == "permalink_url":
                return self._json({"permalink_url": "/reel/991"})
            if url.path == "/graph/c1":
                state.calls.append("ig_status")
                return self._json({"status_code": state.ig_status})
            if url.path == "/graph/ig_1/media":
                state.calls.append("ig_list")
                return self._json({"data": [
                    {"id": "m9", "caption": "Khác", "timestamp": "2026-11-15T10:05:00+0000"},
                    {"id": "m8", "caption": "Nhẫn bạc", "timestamp": "2026-11-15T10:02:00+0000",
                     "permalink": "https://www.instagram.com/reel/m8/"},
                ]})
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length)
            url = urlparse(self.path)
            if url.path == "/rupload/991":
                state.calls.append(f"upload:{len(raw)}")
                state.uploaded = True
                return self._json({"success": True})
            form = parse_qs(raw.decode())
            phase = form.get("upload_phase", [""])[0]
            if url.path == "/graph/page_1/video_reels" and phase == "start":
                state.calls.append("start")
                return self._json({"video_id": "991", "upload_url": "unused"})
            if url.path == "/graph/page_1/video_reels" and phase == "finish":
                state.calls.append("finish")
                state.published = True
                if state.drop_first_finish:
                    state.drop_first_finish = False
                    self.close_connection = True
                    return  # published, but the connection closes without any reply
                return self._json({"success": True})
            if url.path == "/graph/ig_1/media_publish":
                state.calls.append("ig_publish")
                return self._json({"id": "duplicate!"})
            self.send_error(404)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def meta(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    state = MetaState()
    server = _start_server(state)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    for module in (facebook, instagram, meta_published):
        monkeypatch.setattr(module, "GRAPH_BASE_URL", f"{base}/graph")
    monkeypatch.setattr(facebook, "RUPLOAD_BASE", f"{base}/rupload")
    yield state
    server.shutdown()


def _setup(tmp_path: Path, platform: str, external_id: str, container: str | None) -> tuple:  # type: ignore[type-arg]
    paths = get_paths(tmp_path)
    migrate(paths.db_file)
    secrets = SecretsStore(paths.secrets_file)
    secrets.set("TOK", "page-token")
    video = paths.media_dir / "output" / "video_1.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(CLIP, video)
    with get_conn(paths.db_file) as conn:
        conn.execute("INSERT INTO videos (id, status, plan_json) VALUES (1, 'scheduled', '{}')")
        conn.execute(
            "INSERT INTO accounts (id, platform, external_id, name, lang, secret_key, enabled) VALUES (1, ?, ?, 'Acc', 'vi', 'TOK', 1)",
            (platform, external_id),
        )
        conn.execute(
            "INSERT INTO posts (id, video_id, account_id, status, scheduled_at, remote_container_id) "
            "VALUES (1, 1, 1, 'publishing', '2026-11-15T10:00:00Z', ?)",
            (container,),
        )
    return paths, secrets, video


def _rows(paths):  # type: ignore[no-untyped-def]
    return (query_one(paths.db_file, "SELECT * FROM accounts WHERE id = 1"),
            query_one(paths.db_file, "SELECT * FROM posts WHERE id = 1"))


@pytest.mark.local
def test_reel_lost_finish_reply_is_never_published_twice(tmp_path: Path, meta: MetaState) -> None:
    paths, secrets, video = _setup(tmp_path, "facebook", "page_1", None)
    poster = facebook.FacebookPagePoster(paths, secrets)

    account, post = _rows(paths)
    with pytest.raises(TransientPostError, match="network error"):
        poster.publish(account, "", video, "Nhẫn bạc", post)
    assert meta.calls == ["start", f"upload:{video.stat().st_size}", "finish"]
    assert _rows(paths)[1]["remote_container_id"] == "991#finish_sent"  # saved before the reply was lost

    # Retry: status is read first; Meta shows it published, so no second start/upload/finish
    account, post = _rows(paths)
    result = poster.publish(account, "", video, "Nhẫn bạc", post)
    assert result.status == "posted" and result.external_post_id == "991"
    assert result.permalink == "https://www.facebook.com/reel/991"
    assert meta.calls.count("finish") == 1 and meta.calls.count("start") == 1


@pytest.mark.local
def test_reel_retry_waits_while_meta_status_lags_behind_a_sent_finish(tmp_path: Path, meta: MetaState) -> None:
    paths, secrets, video = _setup(tmp_path, "facebook", "page_1", None)
    poster = facebook.FacebookPagePoster(paths, secrets)
    meta.status_lags = True
    account, post = _rows(paths)
    with pytest.raises(TransientPostError):
        poster.publish(account, "", video, "Nhẫn bạc", post)

    # Early retries (attempts 0 and 1) wait instead of sending finish again
    for attempts in (0, 1):
        with get_conn(paths.db_file) as conn:
            conn.execute("UPDATE posts SET attempts = ? WHERE id = 1", (attempts,))
        account, post = _rows(paths)
        with pytest.raises(TransientPostError, match="finish already sent"):
            poster.publish(account, "", video, "Nhẫn bạc", post)
    assert meta.calls.count("finish") == 1


@pytest.mark.local
def test_instagram_published_container_is_found_not_republished(tmp_path: Path, meta: MetaState) -> None:
    paths, secrets, video = _setup(tmp_path, "instagram", "ig_1", "c1")
    meta.ig_status = "PUBLISHED"
    poster = instagram.InstagramReelsPoster(paths, secrets, poll_interval_s=0.0)
    account, post = _rows(paths)
    result = poster.publish(account, "https://r2.example.com/v.mp4", video, "Nhẫn bạc", post)
    assert (result.status, result.external_post_id) == ("posted", "m8")
    assert result.permalink == "https://www.instagram.com/reel/m8/"
    assert "ig_publish" not in meta.calls
