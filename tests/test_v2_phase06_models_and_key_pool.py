"""Tests for Phase 06: On-demand Local AI Models Manager & Multi-Key Rotation Pool."""
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.ai.key_pool import (
    acquire_api_key,
    add_pooled_key,
    mark_pooled_key_cooldown,
    update_pooled_key,
)
from videocreator.app import create_app
from videocreator.db import migrate
from videocreator.models_manager import separate_vocals_and_bgm, transcribe_media_segments
from videocreator.paths import get_paths
from videocreator.pipeline.ffmpeg import ALLOWED_FILTERS, run_ffmpeg, validate_filtergraph_allowed
from videocreator.pipeline.probe import probe_duration
from videocreator.secrets_store import SecretsStore

pytestmark = pytest.mark.local


def _make_av_clip(dest: Path, *, channels: int = 2, duration_s: float = 2.4) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    layout = "stereo" if channels >= 2 else "mono"
    run_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=#1e293b:s=360x640:r=30:d={duration_s}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={duration_s}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ac",
            str(channels),
            "-channel_layout",
            layout,
            str(dest),
        ]
    )
    return dest


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


def test_local_models_catalog_offline_install_and_delete_api(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    assert paths.models_dir.is_dir()

    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        res = client.get("/api/v1/models")
        assert res.status_code == 200
        models = res.json()["models"]
        ids = {m["model_id"] for m in models}
        assert {
            "faster_whisper_small",
            "faster_whisper_medium",
            "speaker_embedding_onnx",
            "uvr_mdx_kim_vocal2",
            "vieneu_tts_vi",
            "paddle_lama_inpaint",
            "nllb_200_distilled_600m_ct2",
            "rembg_u2net",
        }.issubset(ids)
        assert "wav2lip_gan" not in ids
        assert all(m["status"] == "not_installed" for m in models)

        # Bad SHA-256 should fail cleanly without marking ready
        onnx_payload = _make_minimal_identity_onnx()
        weights = tmp_path / "Kim_Vocal_2.onnx"
        weights.write_bytes(onnx_payload)
        bad = client.post(
            "/api/v1/models/uvr_mdx_kim_vocal2/install",
            json={"local_source_path": str(weights), "expected_sha256": "0" * 64},
        )
        assert bad.status_code == 400

        digest = hashlib.sha256(onnx_payload).hexdigest()
        ok = client.post(
            "/api/v1/models/uvr_mdx_kim_vocal2/install",
            json={"local_source_path": str(weights), "expected_sha256": digest},
        )
        assert ok.status_code == 200
        installed = ok.json()["model"]
        assert installed["status"] == "ready"
        assert installed["smoke_tested"] is True
        assert installed["installed_on_disk"] is True
        assert installed["sha256"] == digest
        assert Path(installed["local_path"]).is_file()

        removed = client.delete("/api/v1/models/uvr_mdx_kim_vocal2")
        assert removed.status_code == 200
        assert removed.json()["model"]["status"] == "not_installed"
        assert not Path(installed["local_path"]).exists()


def test_audio_separation_stereo_mono_and_transcribe_segments(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    migrate(paths.db_file, paths.migrations_dir)
    stereo_mp4 = _make_av_clip(tmp_path / "stereo.mp4", channels=2, duration_s=2.5)
    mono_mp4 = _make_av_clip(tmp_path / "mono.mp4", channels=1, duration_s=2.2)

    # Confirm strict BR-PRD-01 whitelist remains untouched
    assert "eq" not in ALLOWED_FILTERS
    with pytest.raises(ValueError):
        validate_filtergraph_allowed("eq=contrast=1.2")

    v_st, b_st = separate_vocals_and_bgm(paths, stereo_mp4, tmp_path / "st_out")
    assert v_st.is_file() and b_st.is_file()
    assert probe_duration(v_st) > 1.5
    assert probe_duration(b_st) > 1.5

    v_mo, b_mo = separate_vocals_and_bgm(paths, mono_mp4, tmp_path / "mo_out")
    assert v_mo.is_file() and b_mo.is_file()
    assert probe_duration(v_mo) > 1.5
    assert probe_duration(b_mo) > 1.5
    assert b_mo.stat().st_size > 1024

    # SRT sidecar preference + silencedetect fallback
    srt_file = stereo_mp4.with_suffix(".srt")
    srt_file.write_text(
        "1\n00:00:00,100 --> 00:00:01,200\nHello Silver Ring\n\n"
        "2\n00:00:01,300 --> 00:00:02,400\n925 Sterling Quality\n",
        encoding="utf-8",
    )
    segs_srt = transcribe_media_segments(paths, stereo_mp4)
    assert len(segs_srt) == 2
    assert segs_srt[0]["source_text"] == "Hello Silver Ring"

    segs_auto = transcribe_media_segments(paths, mono_mp4)
    assert len(segs_auto) >= 1
    assert segs_auto[0]["end_s"] > segs_auto[0]["start_s"]


def test_api_key_pool_round_robin_cooldown_and_masking(tmp_path: Path) -> None:
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)
    with TestClient(app) as client:
        # Legacy fallback when pool is empty
        secrets = SecretsStore(paths.secrets_file)
        secrets.set("GEMINI_API_KEY", "legacy-gemini-fallback-1234")
        val_legacy, kid_legacy = acquire_api_key(
            paths, "gemini", legacy_secret_name="GEMINI_API_KEY", secrets_store=secrets
        )
        assert val_legacy == "legacy-gemini-fallback-1234"
        assert kid_legacy is None

        # Add 2 pooled keys and verify round-robin
        k1 = client.post(
            "/api/v1/key-pool",
            json={
                "provider": "gemini",
                "label": "Account A",
                "raw_secret": "AIzaSyAAAA1111222233334444",
                "priority": 10,
            },
        )
        k2 = client.post(
            "/api/v1/key-pool",
            json={
                "provider": "gemini",
                "label": "Account B",
                "raw_secret": "AIzaSyBBBB5555666677778888",
                "priority": 10,
            },
        )
        assert k1.status_code == 201 and k2.status_code == 201
        id1 = int(k1.json()["key"]["id"])
        id2 = int(k2.json()["key"]["id"])

        # Raw key must never be exposed via REST JSON
        listed = client.get("/api/v1/key-pool?provider=gemini").json()["keys"]
        raw_dump = repr(listed)
        assert "AIzaSyAAAA1111222233334444" not in raw_dump
        assert "AIzaSyBBBB5555666677778888" not in raw_dump
        assert listed[0]["masked_preview"].startswith("AIza")

        v1, got1 = acquire_api_key(paths, "gemini", secrets_store=secrets)
        v2, got2 = acquire_api_key(paths, "gemini", secrets_store=secrets)
        v3, got3 = acquire_api_key(paths, "gemini", secrets_store=secrets)
        assert (got1, got2, got3) == (id1, id2, id1)
        assert v1 == "AIzaSyAAAA1111222233334444"
        assert v2 == "AIzaSyBBBB5555666677778888"
        assert v3 == "AIzaSyAAAA1111222233334444"

        # Quota cooldown removes key1 from rotation immediately
        mark_pooled_key_cooldown(paths.db_file, id1, "429 RESOURCE_EXHAUSTED")
        for _ in range(3):
            _, got = acquire_api_key(paths, "gemini", secrets_store=secrets)
            assert got == id2

        # Clearing cooldown via PATCH restores key1
        patched = client.patch(f"/api/v1/key-pool/{id1}", json={"clear_cooldown": True})
        assert patched.status_code == 200
        assert patched.json()["key"]["is_cooling_down"] is False

        # Deleting removes secret cleanly
        d1 = client.delete(f"/api/v1/key-pool/{id1}")
        assert d1.status_code == 200
        assert secrets.get(f"POOL_GEMINI_{id1}") is None
