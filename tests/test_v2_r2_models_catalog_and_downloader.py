"""Tests for Stage R2: Verified AI Models Catalog, Range/Mirror Downloader & Real CPU Smoke Tests."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.app import create_app
from videocreator.db import get_conn, migrate
from videocreator.models_manager import get_local_model, install_local_model, list_local_models
from videocreator.paths import get_paths

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _make_minimal_identity_onnx(
    input_name: str = "input",
    output_name: str = "output",
    dims: tuple[int, ...] = (1, 4, 16, 16),
) -> bytes:
    def _varint(v: int) -> bytes:
        out = bytearray()
        while True:
            b = v & 0x7F
            v >>= 7
            if v:
                out.append(b | 0x80)
            else:
                out.append(b)
                break
        return bytes(out)

    def _f_varint(fnum: int, val: int) -> bytes:
        return _varint((fnum << 3) | 0) + _varint(val)

    def _f_bytes(fnum: int, data: bytes) -> bytes:
        return _varint((fnum << 3) | 2) + _varint(len(data)) + data

    def _f_str(fnum: int, s: str) -> bytes:
        return _f_bytes(fnum, s.encode("utf-8"))

    shape_bytes = b"".join(_f_bytes(1, _f_varint(1, d)) for d in dims)
    tensor_type = _f_varint(1, 1) + _f_bytes(2, shape_bytes)
    type_proto = _f_bytes(1, tensor_type)
    vi_in = _f_str(1, input_name) + _f_bytes(2, type_proto)
    vi_out = _f_str(1, output_name) + _f_bytes(2, type_proto)
    node = (
        _f_str(1, input_name)
        + _f_str(2, output_name)
        + _f_str(3, "id0")
        + _f_str(4, "Identity")
    )
    graph = (
        _f_bytes(1, node)
        + _f_str(2, "g")
        + _f_bytes(11, vi_in)
        + _f_bytes(12, vi_out)
    )
    opset = _f_str(1, "") + _f_varint(2, 13)
    return _f_varint(1, 7) + _f_bytes(7, graph) + _f_bytes(8, opset)


@pytest.mark.local
def test_r2_catalog_entries_have_verified_hashes_licenses_and_installed_pkgs(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    migrate(paths.db_file, paths.migrations_dir)
    models = list_local_models(paths)
    by_id = {m["model_id"]: m for m in models}

    expected_ids = {
        "faster_whisper_small",
        "faster_whisper_medium",
        "speaker_embedding_onnx",
        "uvr_mdx_kim_vocal2",
        "vieneu_tts_vi",
        "paddle_lama_inpaint",
        "nllb_200_distilled_600m_ct2",
        "rembg_u2net",
    }
    assert set(by_id.keys()) == expected_ids

    for mid, entry in by_id.items():
        assert entry["license"], f"{mid} missing license"
        assert entry["requires_python_pkgs"], f"{mid} missing requires_python_pkgs"
        assert entry["missing_python_pkgs"] == [], (
            f"{mid} has missing Python packages in .venv: {entry['missing_python_pkgs']}"
        )
        files = entry["files"]
        assert len(files) >= 1, f"{mid} has empty files_json"
        for fspec in files:
            assert str(fspec["url"]).startswith("https://"), f"{mid} non-HTTPS url: {fspec['url']}"
            assert _SHA256_RE.match(str(fspec["sha256"])), f"{mid} invalid sha256: {fspec['sha256']}"
            assert int(fspec["size_bytes"]) > 100, f"{mid} invalid size_bytes: {fspec['size_bytes']}"

    assert by_id["nllb_200_distilled_600m_ct2"]["license"] == "CC-BY-NC-4.0"


@pytest.mark.local
def test_r2_downloader_rejects_html_bad_onnx_and_supports_http_range_and_mirror(tmp_path: Path) -> None:
    onnx_blob = _make_minimal_identity_onnx("x", "y", (1, 64, 80))
    onnx_sha = hashlib.sha256(onnx_blob).hexdigest()
    corrupt_blob = b"NOT_AN_ONNX_BINARY_PAYLOAD" * 8
    corrupt_sha = hashlib.sha256(corrupt_blob).hexdigest()
    range_requests: list[str] = []

    class _MockModelHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:  # noqa: ARG002
            return

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/html/"):
                body = b"<!DOCTYPE html><html><body>Login required</body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

            if self.path.startswith("/corrupt/"):
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(corrupt_blob)))
                self.end_headers()
                self.wfile.write(corrupt_blob)
                return

            if self.path.startswith("/mirror/speaker_embedding_onnx/"):
                rng = self.headers.get("Range")
                if rng and rng.startswith("bytes="):
                    range_requests.append(rng)
                    start = int(rng.split("=", 1)[1].split("-", 1)[0])
                    chunk = onnx_blob[start:]
                    self.send_response(206)
                    self.send_header("Content-Type", "application/octet-stream")
                    self.send_header("Content-Range", f"bytes {start}-{len(onnx_blob)-1}/{len(onnx_blob)}")
                    self.send_header("Content-Length", str(len(chunk)))
                    self.end_headers()
                    self.wfile.write(chunk)
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(onnx_blob)))
                self.end_headers()
                self.wfile.write(onnx_blob)
                return

            self.send_response(404)
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), _MockModelHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        paths = get_paths(tmp_path / "data")
        app = create_app(paths.data_dir)
        with TestClient(app) as client:
            fname = "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx"

            # 1. Reject HTML responses cleanly
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    "UPDATE local_models SET files_json = ? WHERE model_id = 'speaker_embedding_onnx'",
                    (
                        json.dumps(
                            [
                                {
                                    "filename": fname,
                                    "url": f"http://127.0.0.1:{port}/html/{fname}",
                                    "sha256": onnx_sha,
                                    "size_bytes": len(onnx_blob),
                                }
                            ]
                        ),
                    ),
                )
            r_html = client.post("/api/v1/models/speaker_embedding_onnx/install", json={"sync": True})
            assert r_html.status_code == 400
            assert "HTML" in r_html.json()["detail"]
            m_after_html = get_local_model(paths, "speaker_embedding_onnx")
            assert m_after_html is not None and m_after_html["status"] == "failed"
            assert not (paths.models_dir / "speaker_embedding_onnx" / f"{fname}.part").exists()

            # 2. Download without smoke test -> 'downloaded', then /verify catches corrupt ONNX -> 'failed'
            with get_conn(paths.db_file) as conn:
                conn.execute(
                    "UPDATE local_models SET files_json = ? WHERE model_id = 'speaker_embedding_onnx'",
                    (
                        json.dumps(
                            [
                                {
                                    "filename": fname,
                                    "url": f"http://127.0.0.1:{port}/corrupt/{fname}",
                                    "sha256": corrupt_sha,
                                    "size_bytes": len(corrupt_blob),
                                }
                            ]
                        ),
                    ),
                )
            r_dl = client.post(
                "/api/v1/models/speaker_embedding_onnx/install",
                json={"sync": True, "verify_smoke": False},
            )
            assert r_dl.status_code == 200
            assert r_dl.json()["model"]["status"] == "downloaded"
            assert r_dl.json()["model"]["smoke_tested"] is False

            r_ver = client.post("/api/v1/models/speaker_embedding_onnx/verify")
            assert r_ver.status_code == 400
            m_failed = get_local_model(paths, "speaker_embedding_onnx")
            assert m_failed is not None and m_failed["status"] == "failed"

            # 3. Clean up, configure mirror_base_url, seed .part prefix, point primary URL to dead port -> Range 206 + mirror + ONNX smoke test -> 'ready'
            client.delete("/api/v1/models/speaker_embedding_onnx")
            r_cfg = client.put(
                "/api/v1/settings",
                json={"models": {"mirror_base_url": f"http://127.0.0.1:{port}/mirror"}},
            )
            assert r_cfg.status_code == 200

            with get_conn(paths.db_file) as conn:
                conn.execute(
                    "UPDATE local_models SET files_json = ? WHERE model_id = 'speaker_embedding_onnx'",
                    (
                        json.dumps(
                            [
                                {
                                    "filename": fname,
                                    "url": "http://127.0.0.1:9/unreachable/primary.onnx",
                                    "sha256": onnx_sha,
                                    "size_bytes": len(onnx_blob),
                                }
                            ]
                        ),
                    ),
                )
            part_dir = paths.models_dir / "speaker_embedding_onnx"
            part_dir.mkdir(parents=True, exist_ok=True)
            half = len(onnx_blob) // 2
            (part_dir / f"{fname}.part").write_bytes(onnx_blob[:half])

            r_ok = client.post("/api/v1/models/speaker_embedding_onnx/install", json={"sync": True})
            assert r_ok.status_code == 200, r_ok.text
            ready_model = r_ok.json()["model"]
            assert ready_model["status"] == "ready"
            assert ready_model["smoke_tested"] is True
            assert ready_model["sha256"] == onnx_sha
            assert range_requests == [f"bytes={half}-"]
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.models
def test_r2_live_download_and_cpu_smoke_test_verified_models(tmp_path: Path) -> None:
    """Downloads real models from Hugging Face (or verified cache), verifies SHA-256 & runs CPU ONNX inference."""
    paths = get_paths(tmp_path / "data")
    migrate(paths.db_file, paths.migrations_dir)

    # 1. Live download from Hugging Face + SHA-256 + ONNX CPU inference smoke test
    spk = install_local_model(paths, "speaker_embedding_onnx", verify_smoke=True)
    assert spk["status"] == "ready"
    assert spk["smoke_tested"] is True
    assert Path(spk["local_path"]).is_file()

    # 2. Live download UVR MDX-Net Kim_Vocal_2.onnx (64 MB) + SHA-256 + ONNX CPU inference smoke test
    mdx = install_local_model(paths, "uvr_mdx_kim_vocal2", verify_smoke=True)
    assert mdx["status"] == "ready"
    assert mdx["smoke_tested"] is True
    assert Path(mdx["local_path"]).is_file()
