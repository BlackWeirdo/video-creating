"""Multi-provider AI Router for Studio (`claude_cli` -> `claude_api` -> `gemini_api`) (Phase 17+).

Allows Studio (Remotion) to run either via the local `claude -p` subscription CLI or via structured
API providers (`claude_api`, `gemini_api`, `muse_api`) while honoring `ai.policy.api_fallback`,
`budget.studio_daily_usd`, and `studio.max_session_usd`.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from videocreator.ai.base import (
    AIProvider,
    BudgetExceeded,
    ProviderAuthError,
    ProviderQuotaExhausted,
)
from videocreator.ai.budget import check_budget, get_daily_api_spend
from videocreator.ai.cli_base import find_claude_binary
from videocreator.ai.providers import build_single_provider
from videocreator.ai.quota import (
    clear_provider_rest,
    earliest_recovery_seconds,
    is_provider_resting,
    mark_provider_error,
    mark_provider_resting,
)
from videocreator.config import Settings, load_settings
from videocreator.jobs import QuotaWaitRequested
from videocreator.paths import AppPaths
from videocreator.secrets_store import SecretsStore
from videocreator.studio.claude_agent import (
    CodeGenerator,
    StudioNotAvailableError,
    make_claude_generator,
)
from videocreator.studio.remotion import can_use_remotion
from videocreator.studio.session import has_active_studio_session

logger = logging.getLogger("videocreator.studio.api_agent")

_PROVIDER_SECRET_KEYS: dict[str, str] = {
    "claude_api": "ANTHROPIC_API_KEY",
    "gemini_api": "GEMINI_API_KEY",
    "muse_api": "MUSE_API_KEY",
}

_CODE_FENCE_RE = re.compile(r"^\s*```(?:tsx|typescript|ts|jsx|js)?\s*\n(.*?)\n\s*```\s*$", re.DOTALL)


class StudioSceneItemSchema(BaseModel):
    shot_id: int
    start_s: float
    duration_s: float
    text: str = ""


class StudioCaptionItemSchema(BaseModel):
    text: str
    hashtags: list[str] = Field(default_factory=list)


class StudioCaptionsSchema(BaseModel):
    facebook: StudioCaptionItemSchema
    instagram: StudioCaptionItemSchema
    threads: StudioCaptionItemSchema
    tiktok: StudioCaptionItemSchema


class StudioPlanGenSchema(BaseModel):
    title: str
    formula: str = "trend-studio"
    scenes: list[StudioSceneItemSchema]
    captions: StudioCaptionsSchema | None = None


class StudioSceneGenSchema(BaseModel):
    scene_tsx: str = Field(description="Toàn bộ mã nguồn đầy đủ của file src/Scene.tsx (không bọc markdown ```)")


class StudioReviseGenSchema(BaseModel):
    update_plan: bool = Field(default=False, description="true nếu cần sửa kịch bản plan.json")
    plan: StudioPlanGenSchema | None = None
    update_scene: bool = Field(default=False, description="true nếu cần sửa trình bày src/Scene.tsx")
    scene_tsx: str = Field(default="", description="Mã nguồn đầy đủ mới của src/Scene.tsx khi update_scene=true")


def _strip_code_fences(code: str) -> str:
    cleaned = code.strip()
    m = _CODE_FENCE_RE.match(cleaned)
    return (m.group(1).strip() if m else cleaned) + "\n"


def _read_optional(path: Path, max_chars: int = 24000) -> str:
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")[:max_chars]


def _write_plan_from_schema(session_dir: Path, plan_obj: StudioPlanGenSchema) -> None:
    payload: dict[str, Any] = {
        "title": plan_obj.title.strip() or "Video trang sức bạc",
        "formula": plan_obj.formula.strip() or "trend-studio",
        "scenes": [s.model_dump() for s in plan_obj.scenes],
    }
    if plan_obj.captions is not None:
        payload["captions"] = plan_obj.captions.model_dump()
    (session_dir / "plan.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _run_api_stage(provider: AIProvider, session_dir: Path, prompt: str) -> None:
    """Executes Stage 1 (`plan.json`), Stage 2 (`src/Scene.tsx`), or Revision via structured JSON."""
    brief_txt = _read_optional(session_dir / "brief.json")
    plan_json_txt = _read_optional(session_dir / "plan.json")
    lib_tsx_txt = _read_optional(session_dir / "src" / "lib.tsx")
    plan_ts_txt = _read_optional(session_dir / "src" / "plan.ts")
    scene_tsx_txt = _read_optional(session_dir / "src" / "Scene.tsx")

    if "viết kịch bản vào `plan.json`" in prompt:
        ctx = f"{prompt}\n\n=== Nội dung brief.json ===\n{brief_txt}\n"
        if plan_json_txt:
            ctx += f"\n=== plan.json hiện tại ===\n{plan_json_txt}\n"
        res = provider.generate_json(ctx, StudioPlanGenSchema)
        _write_plan_from_schema(session_dir, res)
        return

    if "Video đã được dựng. Người dùng muốn sửa" in prompt:
        ctx = (
            f"{prompt}\n\n=== Nội dung brief.json ===\n{brief_txt}\n"
            f"\n=== plan.json hiện tại ===\n{plan_json_txt}\n"
            f"\n=== src/lib.tsx ===\n{lib_tsx_txt}\n"
            f"\n=== src/Scene.tsx hiện tại ===\n{scene_tsx_txt}\n"
        )
        rev = provider.generate_json(ctx, StudioReviseGenSchema)
        if rev.update_plan and rev.plan is not None:
            _write_plan_from_schema(session_dir, rev.plan)
        if rev.update_scene and rev.scene_tsx.strip():
            (session_dir / "src").mkdir(parents=True, exist_ok=True)
            (session_dir / "src" / "Scene.tsx").write_text(_strip_code_fences(rev.scene_tsx), encoding="utf-8")
        return

    ctx = (
        f"{prompt}\n\n=== Nội dung brief.json ===\n{brief_txt}\n"
        f"\n=== src/lib.tsx ===\n{lib_tsx_txt}\n"
        f"\n=== src/plan.ts ===\n{plan_ts_txt or plan_json_txt}\n"
    )
    if scene_tsx_txt:
        ctx += f"\n=== src/Scene.tsx bản trước (cần sửa lỗi) ===\n{scene_tsx_txt}\n"
    scene_res = provider.generate_json(ctx, StudioSceneGenSchema)
    (session_dir / "src").mkdir(parents=True, exist_ok=True)
    (session_dir / "src" / "Scene.tsx").write_text(_strip_code_fences(scene_res.scene_tsx), encoding="utf-8")


def can_start_studio_editor(
    paths: AppPaths,
    settings: Settings | None = None,
    *,
    secrets_store: SecretsStore | None = None,
) -> tuple[bool, str]:
    """Checks whether a new Studio AI editing session can run right now without blocking."""
    cfg = settings or load_settings(paths.config_file)
    rem_ok, rem_reason = can_use_remotion()
    if not rem_ok:
        return False, rem_reason
    if has_active_studio_session(paths.db_file):
        return False, "Một phiên Studio khác đang chạy"
    try:
        check_budget(paths.db_file, cfg, kind="studio")
    except BudgetExceeded as exc:
        return False, str(exc)

    secrets = secrets_store or SecretsStore(paths.secrets_file)
    policy = cfg.ai.policy.api_fallback
    resting_sub = False

    for pname in cfg.ai.routes.studio:
        resting, _ = is_provider_resting(paths.db_file, pname)
        if pname == "claude_cli":
            if resting:
                resting_sub = True
                continue
            if find_claude_binary() is not None:
                return True, "claude_cli"
            continue

        if resting or policy == "never" or (policy == "ask" and resting_sub):
            continue
        sec_key = _PROVIDER_SECRET_KEYS.get(pname)
        if sec_key and secrets.has(sec_key):
            return True, pname

    return False, "Không có provider Studio nào khả dụng (thiếu Claude CLI hoặc API key / hết hạn mức)"


def make_studio_generator(
    paths: AppPaths,
    settings: Settings,
    *,
    secrets_store: SecretsStore | None = None,
    provider_overrides: dict[str, AIProvider] | None = None,
) -> CodeGenerator:
    """Builds a `CodeGenerator` routed across `settings.ai.routes.studio` (`claude_cli` -> API fallback)."""
    overrides = provider_overrides or {}
    accumulated_cost = 0.0

    def generate(session_dir: Path, prompt: str, attempt: int, resume_ref: str | None) -> tuple[str, float]:
        nonlocal accumulated_cost
        route_names = list(settings.ai.routes.studio)
        if not route_names:
            raise StudioNotAvailableError("Chưa cấu hình route nào cho `ai.routes.studio`.")

        policy = settings.ai.policy.api_fallback
        resting_sub: list[str] = []
        last_error: Exception | None = None

        for pname in route_names:
            resting, _ = is_provider_resting(paths.db_file, pname)
            if resting:
                if pname == "claude_cli":
                    resting_sub.append(pname)
                continue

            if pname == "claude_cli" and pname not in overrides:
                if find_claude_binary() is None:
                    continue
                try:
                    cli_gen = make_claude_generator(paths.db_file, settings)
                    cli_resume = resume_ref if (resume_ref and not resume_ref.startswith("api:")) else None
                    ref, cost = cli_gen(session_dir, prompt, attempt, cli_resume)
                    clear_provider_rest(paths.db_file, "claude_cli")
                    return ref, cost
                except ProviderQuotaExhausted as exc:
                    mark_provider_resting(paths.db_file, "claude_cli", duration_s=exc.retry_after_s, error_msg=str(exc))
                    resting_sub.append("claude_cli")
                    last_error = exc
                    continue
                except Exception as exc:
                    mark_provider_error(paths.db_file, "claude_cli", str(exc))
                    last_error = exc
                    continue

            provider = overrides.get(pname) or build_single_provider(
                pname, paths, settings, secrets_store, role="studio"
            )
            if provider.route_kind == "api":
                if policy == "never":
                    continue
                if policy == "ask" and resting_sub:
                    wait_s = earliest_recovery_seconds(paths.db_file, resting_sub)
                    raise QuotaWaitRequested(
                        reason=f"Provider đăng ký ({', '.join(resting_sub)}) hết hạn mức và api_fallback='ask'.",
                        retry_after_s=wait_s,
                    )
                if accumulated_cost >= float(settings.studio.max_session_usd):
                    raise BudgetExceeded(
                        f"Phiên Studio đã chạm trần max_session_usd (${settings.studio.max_session_usd:.2f})."
                    )

            try:
                spent_before = get_daily_api_spend(paths.db_file, bucket="studio")
                _run_api_stage(provider, session_dir, prompt)
                spent_after = get_daily_api_spend(paths.db_file, bucket="studio")
                delta = max(0.0, round(spent_after - spent_before, 6))
                accumulated_cost += delta
                clear_provider_rest(paths.db_file, pname)
                return f"api:{pname}", delta
            except BudgetExceeded:
                raise
            except ProviderQuotaExhausted as exc:
                mark_provider_resting(paths.db_file, pname, duration_s=exc.retry_after_s, error_msg=str(exc))
                if provider.route_kind == "subscription":
                    resting_sub.append(pname)
                last_error = exc
                continue
            except ProviderAuthError as exc:
                mark_provider_error(paths.db_file, pname, str(exc))
                last_error = exc
                continue
            except Exception as exc:
                mark_provider_error(paths.db_file, pname, str(exc))
                last_error = exc
                logger.warning("Studio provider '%s' failed: %s", pname, exc)
                continue

        if resting_sub:
            wait_s = earliest_recovery_seconds(paths.db_file, resting_sub)
            raise QuotaWaitRequested(
                reason=f"Các provider đăng ký Studio ({', '.join(resting_sub)}) đang nghỉ chờ hạn mức.",
                retry_after_s=wait_s,
            )
        if last_error is not None:
            raise last_error
        raise StudioNotAvailableError(
            "Không có provider Studio nào chạy được (cần đăng nhập Claude Code hoặc cấu hình API key)."
        )

    return generate
