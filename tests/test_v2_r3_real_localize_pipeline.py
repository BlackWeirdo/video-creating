"""Tests for Stage R3: Real Localize / Reup Pipeline (MDX-Net, RapidOCR, Whisper, Diarization, AI/NLLB, Edge/VieNeu Cloning & LaMa)."""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from videocreator.ai.base import RouteKind


def _ensure_r3_real_samples() -> dict[str, Path]:
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "prepare_r3_test_samples.py"
    spec = importlib.util.spec_from_file_location("prepare_r3_test_samples", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ensure_r3_real_samples()
from videocreator.app import create_app
from videocreator.db import get_conn, migrate, query_all, query_one
from videocreator.models_manager import get_local_model, install_local_model
from videocreator.paths import AppPaths, get_paths
from videocreator.pipeline.localize import (
    create_localize_project,
    run_localize_extract,
    run_localize_render,
)
from videocreator.pipeline.ocr_hardsub import (
    align_ocr_and_whisper_segments,
    extract_hardsub_ocr_cues,
    inpaint_segment_with_lama,
)
from videocreator.pipeline.translate_vi import (
    TranslatedBatchSchema,
    TranslatedItemSchema,
    translate_localize_segments,
)

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_VI_DIACRITIC_RE = re.compile(r"[ăâđêôơưĂÂĐÊÔƠƯáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]")


def _seed_installed_models_from_user_cache(target_paths: AppPaths, model_ids: list[str]) -> None:
    """Reuses already smoke-verified models from `get_paths().models_dir` (or installs live if missing)."""
    default_paths = get_paths()
    migrate(default_paths.db_file, default_paths.migrations_dir)
    migrate(target_paths.db_file, target_paths.migrations_dir)
    for mid in model_ids:
        cached = get_local_model(default_paths, mid)
        if cached and cached.get("status") == "ready" and cached.get("smoke_tested") and cached.get("installed_on_disk"):
            with get_conn(target_paths.db_file) as conn:
                conn.execute(
                    """
                    UPDATE local_models
                    SET status = 'ready',
                        smoke_tested = 1,
                        progress = 1.0,
                        local_path = ?,
                        sha256 = ?,
                        error = NULL
                    WHERE model_id = ?
                    """,
                    (str(cached["local_path"]), str(cached["sha256"]), mid),
                )
            continue
        install_local_model(default_paths, mid, verify_smoke=True)
        fresh = get_local_model(default_paths, mid)
        assert fresh is not None and fresh["status"] == "ready"
        with get_conn(target_paths.db_file) as conn:
            conn.execute(
                "UPDATE local_models SET status = 'ready', smoke_tested = 1, progress = 1.0, local_path = ?, sha256 = ? WHERE model_id = ?",
                (str(fresh["local_path"]), str(fresh["sha256"]), mid),
            )


@pytest.mark.local
def test_r3_ocr_whisper_alignment_translator_role_and_cloning_safeguards(tmp_path: Path) -> None:
    """Verifies OCR+Whisper merge priority, AI `translator` role number preservation, and Decision 7c cloning guards."""
    paths = get_paths(tmp_path / "data")
    app = create_app(paths.data_dir)

    # 1. OCR + Whisper alignment prioritizes reliable OCR text & snaps timestamps to Whisper
    whisper_segs = [
        {"index": 0, "start_s": 0.22, "end_s": 2.95, "source_text": "这款925纯银戒今天优惠50"},
        {"index": 1, "start_s": 3.20, "end_s": 5.80, "source_text": "Extra spoken remark without hardsub"},
    ]
    ocr_cues = [
        {
            "start_s": 0.40,
            "end_s": 2.80,
            "text": "这款925纯银戒指今天优惠50%",
            "confidence": 0.96,
            "box": {"x": 0.08, "y": 0.76, "w": 0.84, "h": 0.12},
        }
    ]
    merged, origin = align_ocr_and_whisper_segments(whisper_segs, ocr_cues)
    assert origin == "ocr+whisper"
    assert len(merged) == 2
    assert merged[0]["source_text"] == "这款925纯银戒指今天优惠50%"
    assert merged[0]["text_origin"] == "ocr"
    assert merged[0]["start_s"] == 0.22
    assert merged[1]["text_origin"] == "whisper"

    # 2. AI `translator` role routes cleanly and enforces verbatim numeric preservation (925, 50%)
    class _FakeTranslatorProvider:
        name = "claude_cli"
        route_kind: RouteKind = "subscription"

        def describe_video(self, video, prompt, schema, *, thumbnails=None):  # noqa: ANN001, ARG002
            raise NotImplementedError

        def generate_json(self, prompt: str, schema: type[TranslatedBatchSchema]) -> TranslatedBatchSchema:
            assert "natural_tiktok" in prompt
            assert "925" in prompt and "50%" in prompt
            return schema(
                segments=[
                    # Intentionally omit '50%' in item 0 to test post-validation numeric preservation!
                    TranslatedItemSchema(index=0, translated_text="Mẫu nhẫn bạc 925 hôm nay giảm cực sâu"),
                    TranslatedItemSchema(index=1, translated_text="Chia sẻ thêm mẹo phối đồ cực xinh"),
                ]
            )

    trans_segs, engine = translate_localize_segments(
        paths,
        merged,
        source_lang="zh",
        target_lang="vi",
        translation_style="natural_tiktok",
        provider_overrides={"claude_cli": _FakeTranslatorProvider()},
    )
    assert engine == "ai_translator"
    assert "925" in trans_segs[0]["translated_text"]
    assert "50%" in trans_segs[0]["translated_text"]

    # 3. Decision 7c: Original voice cloning blocked in strict_footage and requires explicit consent + audit log
    with TestClient(app) as client:
        # Strict footage (#1) blocks voice cloning even on intl_export with consent=True
        r_strict = client.post(
            "/api/v1/localize/projects",
            json={
                "workspace_id": 1,
                "title": "Blocked Strict Clone",
                "mode": "intl_export",
                "source_media_path": "dummy.mp4",
                "clone_source_voice": True,
                "clone_consent_confirmed": True,
            },
        )
        assert r_strict.status_code == 403

        ws_ai = client.post(
            "/api/v1/workspaces",
            json={"name": "Reup AI Lab", "content_policy": "full_ai"},
        ).json()["workspace"]
        ws_id = int(ws_ai["id"])

        # Missing consent_confirmed is rejected with 403
        r_no_consent = client.post(
            "/api/v1/localize/projects",
            json={
                "workspace_id": ws_id,
                "title": "Missing Consent",
                "mode": "reup_vi",
                "clone_source_voice": True,
                "clone_consent_confirmed": False,
            },
        )
        assert r_no_consent.status_code == 403

        # Default project has clone_source_voice == False
        r_ok = client.post(
            "/api/v1/localize/projects",
            json={"workspace_id": ws_id, "title": "Safe Default", "mode": "reup_vi"},
        )
        assert r_ok.status_code == 201
        proj_id = int(r_ok.json()["project"]["id"])
        assert r_ok.json()["project"]["clone_source_voice"] is False

        # Enabling with explicit consent succeeds and writes audit_log
        r_enable = client.patch(
            f"/api/v1/localize/projects/{proj_id}",
            json={"clone_source_voice": True, "clone_consent_confirmed": True},
        )
        assert r_enable.status_code == 200
        assert r_enable.json()["project"]["clone_source_voice"] is True
        audits = query_all(
            paths.db_file,
            "SELECT action FROM audit_log WHERE object_type = 'localize_project' AND object_id = ?",
            (proj_id,),
        )
        assert any(a["action"] == "enable_source_voice_clone" for a in audits)


@pytest.mark.models
def test_r3_real_chinese_hardsub_reup_lama_and_english_e2e(tmp_path: Path) -> None:
    """End-to-end R3 acceptance on real Mandarin hardsub + English clips with real CPU models."""
    samples = _ensure_r3_real_samples()
    paths = get_paths(tmp_path / "data")
    _seed_installed_models_from_user_cache(
        paths,
        [
            "uvr_mdx_kim_vocal2",
            "faster_whisper_small",
            "speaker_embedding_onnx",
            "nllb_200_distilled_600m_ct2",
            "paddle_lama_inpaint",
            "vieneu_tts_vi",
        ],
    )
    # Exercise real offline CPU NLLB-200 translation deterministically without waiting on external CLI subprocesses
    from videocreator.config import load_settings, save_settings

    cfg = load_settings(paths.config_file)
    cfg.ai.routes.translator = []
    save_settings(paths.config_file, cfg)

    with get_conn(paths.db_file) as conn:
        ws_id = int(
            conn.execute(
                "INSERT INTO workspaces (slug, name, content_policy) VALUES ('reup-e2e', 'Reup E2E', 'full_ai')"
            ).lastrowid
        )

    # Copy Chinese hardsub sample into workspace media
    zh_dst = paths.media_dir / "localize" / "zh_hardsub_reup.mp4"
    zh_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(samples["zh_hardsub"], zh_dst)

    # Verify LaMa ONNX Inpaint directly erases >=80% of Chinese hardsub characters before new subs are burned
    initial_cues = extract_hardsub_ocr_cues(zh_dst, sample_every_s=0.5)
    initial_cjk_chars = sum(len(_CJK_RE.findall(c["text"])) for c in initial_cues)
    assert initial_cjk_chars >= 6, f"Expected Chinese OCR characters in source clip, got: {initial_cues}"

    inpainted_mp4 = tmp_path / "zh_lama_cleaned.mp4"
    ok_lama = inpaint_segment_with_lama(
        paths,
        zh_dst,
        inpainted_mp4,
        boxes=[c["box"] for c in initial_cues],
        work_dir=tmp_path,
    )
    assert ok_lama is True
    after_cues = extract_hardsub_ocr_cues(inpainted_mp4, sample_every_s=0.5)
    after_cjk_chars = sum(len(_CJK_RE.findall(c["text"])) for c in after_cues)
    assert after_cjk_chars <= initial_cjk_chars * 0.20, (
        f"LaMa inpaint did not sufficiently remove Chinese hardsubs: before={initial_cjk_chars}, after={after_cjk_chars}"
    )

    # Full Localize Extract + Render on Chinese hardsub clip (MDX-Net + OCR + Whisper + NLLB + Blur + Edge TTS + QC)
    proj = create_localize_project(
        paths,
        workspace_id=ws_id,
        title="Douyin Silver Ring Reup",
        mode="reup_vi",
        source_media_path="localize/zh_hardsub_reup.mp4",
        source_lang="zh",
        target_lang="vi",
        hardsub_mode="blur_bar",
        translation_style="natural_tiktok",
    )
    extracted = run_localize_extract(paths, int(proj["id"]))
    segs = extracted["segments"]
    assert len(segs) >= 2
    combined_src = " ".join(s["source_text"] for s in segs)
    combined_vi = " ".join(s["translated_text"] for s in segs)
    assert _CJK_RE.search(combined_src), f"Expected Chinese source text, got: {combined_src}"
    assert _VI_DIACRITIC_RE.search(combined_vi), f"Expected Vietnamese translation, got: {combined_vi}"
    assert "925" in combined_vi and "50%" in combined_vi and "2026" in combined_vi
    assert "audio_sep_midside_fallback" not in extracted["simulation_flags"]
    assert "asr_silencedetect_placeholder" not in extracted["simulation_flags"]

    rendered_proj = run_localize_render(paths, int(proj["id"]), tts_provider="edge")
    assert rendered_proj["status"] == "completed"
    assert "tts_tone_placeholder" not in rendered_proj["simulation_flags"]

    vid_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (rendered_proj["output_video_id"],))
    assert vid_row is not None
    qc = json.loads(str(vid_row["qc_json"]))
    assert qc["passed"] is True, f"QC failed: {qc}"

    # Transcribe rendered Vietnamese video with Faster-Whisper to prove output audio is genuinely spoken Vietnamese!
    from faster_whisper import WhisperModel

    w_info = get_local_model(paths, "faster_whisper_small")
    assert w_info is not None
    w_model = WhisperModel(str(w_info["local_path"]), device="cpu", compute_type="int8", cpu_threads=4)
    try:
        out_mp4 = paths.media_dir / str(vid_row["output_path"])
        vi_segs, info = w_model.transcribe(str(out_mp4), language=None, vad_filter=True)
        heard_vi = " ".join(s.text for s in vi_segs).strip()
        assert info.language == "vi" or _VI_DIACRITIC_RE.search(heard_vi), (
            f"Expected rendered audio to be spoken Vietnamese, detected lang={info.language} text={heard_vi!r}"
        )
    finally:
        del w_model

    # Also verify pure English clip (no hardsubs) -> Whisper ASR -> VI translation preserving 2026 & 85%
    en_dst = paths.media_dir / "localize" / "en_clean_speech.mp4"
    shutil.copy2(samples["en_clean"], en_dst)
    proj_en = create_localize_project(
        paths,
        workspace_id=ws_id,
        title="English Promo to VI",
        mode="reup_vi",
        source_media_path="localize/en_clean_speech.mp4",
        source_lang="en",
        target_lang="vi",
        hardsub_mode="none",
    )
    ext_en = run_localize_extract(paths, int(proj_en["id"]))
    en_vi_text = " ".join(s["translated_text"] for s in ext_en["segments"])
    assert _VI_DIACRITIC_RE.search(en_vi_text), f"Expected Vietnamese text, got: {en_vi_text}"
    assert "2026" in en_vi_text and "85%" in en_vi_text


@pytest.mark.models
def test_r3_real_two_speakers_diarization_and_vieneu_voice_cloning(tmp_path: Path) -> None:
    """Verifies ONNX multi-speaker diarization (>=2 speaker_ids) and VieNeu-TTS v3 Nano zero-shot voice cloning."""
    samples = _ensure_r3_real_samples()
    paths = get_paths(tmp_path / "data")
    _seed_installed_models_from_user_cache(
        paths,
        [
            "uvr_mdx_kim_vocal2",
            "faster_whisper_small",
            "speaker_embedding_onnx",
            "nllb_200_distilled_600m_ct2",
            "vieneu_tts_vi",
        ],
    )
    from videocreator.config import load_settings, save_settings

    cfg = load_settings(paths.config_file)
    cfg.ai.routes.translator = []
    save_settings(paths.config_file, cfg)

    with get_conn(paths.db_file) as conn:
        ws_id = int(
            conn.execute(
                "INSERT INTO workspaces (slug, name, content_policy) VALUES ('clone-lab', 'Clone Lab', 'hybrid_remix')"
            ).lastrowid
        )
        f_id = int(
            conn.execute(
                "INSERT INTO footage (workspace_id, path, sha256, orientation, width, height, duration_s) VALUES (?, 'localize/two_spk.mp4', 'sha_2spk', 'portrait', 360, 640, 8.0)",
                (ws_id,),
            ).lastrowid
        )
        conn.execute(
            "INSERT INTO shots (footage_id, start_s, end_s, description, has_product, quality) VALUES (?, 0.0, 2.5, 'Demo B-roll', 1, 5)",
            (f_id,),
        )

    dst_2s = paths.media_dir / "localize" / "two_spk.mp4"
    dst_2s.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(samples["two_speakers"], dst_2s)

    proj = create_localize_project(
        paths,
        workspace_id=ws_id,
        title="2-Speaker Interview Clone",
        mode="hybrid_remix",
        source_media_path="localize/two_spk.mp4",
        source_lang="en",
        target_lang="vi",
        hardsub_mode="none",
        clone_source_voice=True,
        clone_consent_confirmed=True,
    )
    extracted = run_localize_extract(paths, int(proj["id"]))
    speaker_ids = {s["speaker_id"] for s in extracted["segments"]}
    assert len(speaker_ids) >= 2, f"Expected >=2 speakers detected on female/male dialogue, got: {extracted['segments']}"

    # Verify extracted speaker clips live strictly inside project folder (never global catalog)
    speakers_cfg = extracted["speaker_config"]["speakers"]
    for spk_id, meta in speakers_cfg.items():
        assert meta["ref_audio_rel"].startswith(f"localize/proj_{proj['id']}/speakers/"), meta
        assert (paths.media_dir / meta["ref_audio_rel"]).is_file()

    # Render using VieNeu-TTS zero-shot voice cloning on extracted speaker references!
    rendered = run_localize_render(paths, int(proj["id"]), tts_provider="auto")
    assert rendered["status"] == "completed"
    assert "tts_tone_placeholder" not in rendered["simulation_flags"]

    vid_row = query_one(paths.db_file, "SELECT * FROM videos WHERE id = ?", (rendered["output_video_id"],))
    assert vid_row is not None
    plan = json.loads(str(vid_row["plan_json"]))
    assert plan["cloned_source_voice"] is True
    assert "vieneu" in plan["voice_provider"]
    assert json.loads(str(vid_row["qc_json"]))["passed"] is True

    audits = query_all(
        paths.db_file,
        "SELECT action FROM audit_log WHERE object_type = 'localize_project' AND object_id = ?",
        (int(proj["id"]),),
    )
    assert any(a["action"] == "render_source_voice_clone" for a in audits)
