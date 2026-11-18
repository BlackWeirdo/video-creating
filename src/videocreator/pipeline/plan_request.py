"""`plan` job: the saved plan request of a footage and its handler (Phase 04)."""
from __future__ import annotations

import json
import threading
from typing import Any, Literal

from videocreator.paths import AppPaths
from videocreator.pipeline.planner import create_remix_plans

_PLAN_REQ_LOCK = threading.Lock()


def save_plan_request_params(
    paths: AppPaths,
    footage_id: int,
    *,
    count: int = 3,
    voice_lang: Literal["none", "vi", "en"] = "vi",
    caption_lang: Literal["vi", "en"] = "vi",
    target_duration_s: float = 15.0,
    formula: dict[str, Any] | str | None = None,
    suggestion_id: int | None = None,
    auto_render: bool = False,
    preset_body: str | None = None,
) -> None:
    req_file = paths.work_dir / f"plan_req_{footage_id}.json"
    req_file.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "count": max(1, min(6, int(count))),
        "voice_lang": voice_lang,
        "caption_lang": caption_lang,
        "target_duration_s": max(5.0, min(60.0, float(target_duration_s))),
        "formula": formula,
        "suggestion_id": suggestion_id,
        "auto_render": auto_render,
        "preset_body": preset_body,
    }
    with _PLAN_REQ_LOCK:
        queue: list[dict[str, Any]] = []
        if req_file.exists():
            try:
                loaded = json.loads(req_file.read_text(encoding="utf-8"))
                if isinstance(loaded, list):
                    queue = [x for x in loaded if isinstance(x, dict)]
                elif isinstance(loaded, dict):
                    queue = [loaded]
            except Exception:
                queue = []
        queue.append(entry)
        req_file.write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")


def run_plan_footage(paths: AppPaths, footage_id: int) -> str:
    """Job handler for `plan`: pops the oldest saved request params and calls `create_remix_plans`."""
    req_file = paths.work_dir / f"plan_req_{footage_id}.json"
    params: dict[str, Any] = {
        "count": 3,
        "voice_lang": "vi",
        "caption_lang": "vi",
        "target_duration_s": 15.0,
        "formula": None,
        "suggestion_id": None,
        "auto_render": False,
        "preset_body": None,
    }
    with _PLAN_REQ_LOCK:
        if req_file.exists():
            try:
                loaded = json.loads(req_file.read_text(encoding="utf-8"))
                if isinstance(loaded, list) and loaded:
                    first = loaded.pop(0)
                    if isinstance(first, dict):
                        params.update(first)
                    if loaded:
                        req_file.write_text(json.dumps(loaded, ensure_ascii=False), encoding="utf-8")
                    else:
                        req_file.unlink(missing_ok=True)
                elif isinstance(loaded, dict):
                    params.update(loaded)
                    req_file.unlink(missing_ok=True)
                else:
                    req_file.unlink(missing_ok=True)
            except Exception:
                req_file.unlink(missing_ok=True)

    target_ftg: int | None = footage_id if footage_id > 0 else None
    vids = create_remix_plans(
        paths,
        target_ftg,
        count=int(params["count"]),
        voice_lang=params["voice_lang"],
        caption_lang=params["caption_lang"],
        target_duration_s=float(params["target_duration_s"]),
        formula=params.get("formula"),
        suggestion_id=params.get("suggestion_id"),
        auto_render=bool(params.get("auto_render", False)),
        preset_body=params.get("preset_body"),
    )
    return f"Created {len(vids)} video plans: {vids}"
