"""Real CPU inference smoke-test verification for installed local AI models."""
from __future__ import annotations

import gc
from pathlib import Path
from typing import Any

from videocreator.ai_models.catalog import get_local_model, set_model_state
from videocreator.db import get_conn, record_audit
from videocreator.paths import AppPaths


def _smoke_test_onnx_generic(model_id: str, target_path: Path) -> None:
    import numpy as np
    import onnxruntime as ort

    onnx_path = target_path
    if onnx_path.is_dir():
        found = sorted(onnx_path.glob("*.onnx"))
        if not found:
            raise FileNotFoundError(f"No .onnx model file found in {onnx_path}")
        onnx_path = found[0]

    sess_opts = ort.SessionOptions()
    sess_opts.intra_op_num_threads = 2
    sess_opts.inter_op_num_threads = 1
    sess = ort.InferenceSession(
        str(onnx_path),
        sess_options=sess_opts,
        providers=["CPUExecutionProvider"],
    )
    try:
        feed: dict[str, Any] = {}
        for inp in sess.get_inputs():
            concrete: list[int] = []
            rank = len(inp.shape)
            for axis_idx, dim in enumerate(inp.shape):
                if isinstance(dim, int) and dim > 0:
                    concrete.append(dim)
                elif axis_idx == 0:
                    concrete.append(1)
                elif model_id == "speaker_embedding_onnx":
                    concrete.append(80 if axis_idx == rank - 1 else 64)
                elif model_id == "paddle_lama_inpaint":
                    concrete.append(512)
                elif model_id == "rembg_u2net":
                    concrete.append(320)
                else:
                    concrete.append(64)
            inp_type = str(inp.type or "")
            if "float16" in inp_type:
                dtype: Any = np.float16
            elif "int64" in inp_type:
                dtype = np.int64
            elif "int32" in inp_type:
                dtype = np.int32
            else:
                dtype = np.float32
            feed[inp.name] = np.zeros(tuple(concrete), dtype=dtype)
        outputs = sess.run(None, feed)
        if not outputs or outputs[0] is None:
            raise RuntimeError(f"ONNX smoke test produced no output for '{model_id}'")
    finally:
        del sess


def verify_model_smoke_test(paths: AppPaths, model_id: str) -> dict[str, Any]:
    """Runs a real CPU inference smoke test on an installed local model before marking it `ready`."""
    info = get_local_model(paths, model_id)
    if info is None:
        raise ValueError(f"Unknown local model '{model_id}'")
    local_target = str(info.get("local_path") or "").strip()
    if not local_target or not Path(local_target).exists():
        set_model_state(
            paths,
            model_id,
            status="failed",
            smoke_tested=False,
            error="Model files not found on disk",
        )
        raise FileNotFoundError(f"Model '{model_id}' is not present on disk: {local_target}")

    missing_pkgs = list(info.get("missing_python_pkgs") or [])
    if missing_pkgs:
        msg = f"Missing required Python packages: {', '.join(missing_pkgs)}"
        set_model_state(
            paths,
            model_id,
            status="downloaded",
            progress=0.95,
            smoke_tested=False,
            error=msg,
        )
        raise RuntimeError(msg)

    target_path = Path(local_target)
    try:
        if model_id in ("faster_whisper_small", "faster_whisper_medium"):
            import numpy as np
            from faster_whisper import WhisperModel

            w_dir = target_path if target_path.is_dir() else target_path.parent
            w_model = WhisperModel(str(w_dir), device="cpu", compute_type="int8", cpu_threads=2)
            try:
                silent = np.zeros(16000, dtype=np.float32)
                segs, _ = w_model.transcribe(silent, language="en", vad_filter=False)
                list(segs)
            finally:
                del w_model
        elif model_id == "vieneu_tts_vi":
            from vieneu.v3nano import V3NanoVieNeuTTS

            v_dir = target_path if target_path.is_dir() else target_path.parent
            tts = V3NanoVieNeuTTS(onnx_dir=str(v_dir))
            try:
                wav = tts.infer("Xin chào", apply_watermark=False)
                if wav is None or len(wav) < 400:
                    raise RuntimeError("VieNeu-TTS smoke test returned empty audio")
            finally:
                tts.close()
        elif model_id == "nllb_200_distilled_600m_ct2":
            import ctranslate2
            import sentencepiece as spm

            nllb_dir = target_path if target_path.is_dir() else target_path.parent
            sp_model = nllb_dir / "sentencepiece.bpe.model"
            sp = spm.SentencePieceProcessor(str(sp_model))
            translator = ctranslate2.Translator(
                str(nllb_dir),
                device="cpu",
                compute_type="int8",
                inter_threads=1,
                intra_threads=2,
            )
            try:
                tokens = ["eng_Latn", *sp.encode("Hello", out_type=str), "</s>"]
                out = translator.translate_batch(
                    [tokens],
                    target_prefix=[["vie_Latn"]],
                    beam_size=1,
                    max_decoding_length=24,
                )
                if not out or not out[0].hypotheses:
                    raise RuntimeError("NLLB-200 smoke test returned no hypothesis")
            finally:
                del translator
        else:
            _smoke_test_onnx_generic(model_id, target_path)
        gc.collect()
    except Exception as exc:
        set_model_state(
            paths,
            model_id,
            status="failed",
            smoke_tested=False,
            error=f"Smoke test failed: {exc}",
        )
        raise ValueError(f"Model smoke test failed for '{model_id}': {exc}") from exc

    set_model_state(
        paths,
        model_id,
        status="ready",
        progress=1.0,
        smoke_tested=True,
        error=None,
    )
    with get_conn(paths.db_file) as conn:
        record_audit(
            conn,
            actor="models_manager",
            action="verify_model",
            object_type="local_model",
            detail=f"{model_id} verified ready",
        )
    updated = get_local_model(paths, model_id)
    assert updated is not None
    return updated
