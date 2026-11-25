"""AI B-roll generation: one paid clip from a text prompt, kept as a no-product shot (Phase 14)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from videocreator.ai.budget import check_budget, record_usage
from videocreator.ai.gateway import GatewayVideoGenProvider
from videocreator.ai.veo import VeoVideoGenProvider
from videocreator.ai.videogen_base import VideoGenProvider, estimate_videogen_cost
from videocreator.config import load_settings
from videocreator.manual.tickets import create_manual_ticket
from videocreator.paths import AppPaths
from videocreator.pipeline.broll import keep_broll_clip
from videocreator.secrets_store import SecretsStore

logger = logging.getLogger("videocreator.pipeline.broll")

BROLL_PRESET_PROMPTS: list[dict[str, str]] = [
    {
        "id": "workbench",
        "label": "Bàn thợ bạc thủ công (ánh đèn vàng ấm)",
        "prompt": "Cận cảnh bàn gỗ của nghệ nhân kim hoàn, dụng cụ chạm khắc cổ điển, bụi bạc lấp lánh dưới ánh đèn vàng ấm, chuyển động máy chậm, 9:16 dọc, không có trang sức hoàn thiện",
    },
    {
        "id": "smoke_light",
        "label": "Khói mỏng & tia sáng nghệ thuật",
        "prompt": "Làn khói mỏng bay chậm qua tia sáng chiếu xiên trên nền đá tối màu sang trọng, bokeh dịu, điện ảnh, 9:16 dọc",
    },
    {
        "id": "nature_stone",
        "label": "Đá tự nhiên & rêu ẩm (bối cảnh trưng bày)",
        "prompt": "Bề mặt đá bazan đen tự nhiên và rêu xanh ẩm dưới nắng sớm dịu nhẹ, giọt sương tinh khiết, chuyển động dolly chậm, 9:16 dọc",
    },
]


def get_videogen_provider(
    paths: AppPaths,
    source_key: str,
) -> VideoGenProvider:
    settings = load_settings(paths.config_file)
    secrets = SecretsStore(paths.secrets_file)
    clean = source_key.replace("gateway_api:", "").replace("_api", "").strip().lower()
    if clean in ("muse", "muse-video"):
        from videocreator.ai.muse_videogen import MuseVideoGenProvider

        return MuseVideoGenProvider(paths, settings, secrets, paths.work_dir)
    if clean == "veo":
        return VeoVideoGenProvider(settings, secrets, paths.work_dir)
    return GatewayVideoGenProvider(clean, settings, secrets, paths.work_dir)


def generate_broll(
    paths: AppPaths,
    *,
    prompt: str,
    source: str = "manual",
    seconds: int = 6,
    image_path: Path | None = None,
    provider: VideoGenProvider | None = None,
    auto_keep: bool = True,
    workspace_id: int = 1,
) -> dict[str, Any]:
    """Generates a B-roll clip via the selected `source` (`manual`, `muse`, `kling`, `seedance`, `veo`, etc.).

    Checks `budget.generative_daily_usd` BEFORE calling any paid API (`BR-COST-02`, `FR-BRL-03`).
    """
    clean_source = source.replace("gateway_api:", "").replace("_api", "").strip().lower()
    if clean_source == "manual":
        tid = create_manual_ticket(
            paths,
            prompt=prompt,
            seconds=seconds,
            ref_path=str(image_path) if image_path else None,
        )
        return {
            "mode": "manual",
            "ticket_id": tid,
            "estimated_cost_usd": 0.0,
        }

    settings = load_settings(paths.config_file)
    if clean_source in ("muse", "muse-video") and provider is None:
        from videocreator.muse_gateway.store import create_muse_task

        refs: list[dict[str, Any]] = []
        if image_path is not None and image_path.is_file():
            from videocreator.muse_gateway.refs import stage_uploaded_muse_ref

            staged = stage_uploaded_muse_ref(
                paths,
                filename=image_path.name,
                data=image_path.read_bytes(),
                workspace_id=workspace_id,
            )
            refs.append({"type": "upload", "upload_id": staged["upload_id"]})
        task = create_muse_task(
            paths.db_file,
            workspace_id=workspace_id,
            kind="video",
            model=settings.muse_gateway.default_video_model or "muse-video",
            purpose="broll",
            prompt=prompt,
            params={"duration": max(1, min(60, int(seconds))), "ratio": "9:16"},
            refs=refs,
            priority=5,
        )
        return {
            "mode": "muse_queued",
            "muse_task_id": int(task["id"]),
            "task": task,
            "estimated_cost_usd": 0.0,
        }
    est_cost = estimate_videogen_cost(settings, clean_source, seconds)

    # Enforce generative daily budget ceiling BEFORE calling API
    check_budget(
        paths.db_file,
        settings,
        kind="videogen",
        estimated_cost_usd=est_cost,
    )

    gen = provider or get_videogen_provider(paths, clean_source)
    raw_clip = gen.generate_clip(prompt, seconds=seconds, image=image_path)

    record_usage(
        paths.db_file,
        provider=gen.name,
        model=clean_source,
        kind="videogen",
        route="api",
        units_in=1,
        units_out=seconds,
        cost_usd=est_cost,
    )

    if auto_keep:
        asset_id, shot_id = keep_broll_clip(
            paths,
            raw_clip,
            prompt=prompt,
            source_model=clean_source,
            tag_kind="ai_broll",
        )
        return {
            "mode": "api",
            "source": clean_source,
            "asset_id": asset_id,
            "shot_id": shot_id,
            "estimated_cost_usd": est_cost,
        }

    return {
        "mode": "api_preview",
        "source": clean_source,
        "preview_path": str(raw_clip),
        "estimated_cost_usd": est_cost,
    }
