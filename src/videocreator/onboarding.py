"""First-run Welcome Wizard state & Backup Summary helpers (V2-OPS-01..02)."""
from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from typing import Any

from videocreator.ai.key_pool import add_pooled_key, list_pooled_keys
from videocreator.config import load_settings, save_settings
from videocreator.db import (
    get_conn,
    get_setting,
    query_one,
    record_audit,
    set_setting,
)
from videocreator.paths import AppPaths, find_ffmpeg_binary, find_node_runtime
from videocreator.secrets_store import SecretsStore
from videocreator.workspaces import (
    create_workspace,
    get_active_workspace_id,
    get_workspace,
    list_workspaces,
    set_active_workspace_id,
    update_workspace,
)

WIZARD_COMPLETED_KEY = "v2_wizard_completed"


def _binary_available(cmd_or_path: str) -> bool:
    if not cmd_or_path:
        return False
    p = Path(cmd_or_path)
    if p.is_file():
        return True
    return shutil.which(cmd_or_path) is not None


def _count_rows(db_file: Path, sql: str, params: tuple[Any, ...] = ()) -> int:
    row = query_one(db_file, sql, params)
    return int(row["c"]) if row else 0


def get_onboarding_status(
    paths: AppPaths,
    secrets_store: SecretsStore | None = None,
) -> dict[str, Any]:
    """Inspects runtime readiness, active workspace, configured keys, and wizard completion."""
    sec = secrets_store or SecretsStore(paths.secrets_file)
    cfg = load_settings(paths.config_file)
    active_ws_id = get_active_workspace_id(paths.db_file)
    active_ws = get_workspace(paths.db_file, active_ws_id)
    workspaces = list_workspaces(paths.db_file, include_archived=False)
    pooled_keys = list_pooled_keys(paths, secrets_store=sec)

    ffmpeg_bin = find_ffmpeg_binary("ffmpeg")
    ffprobe_bin = find_ffmpeg_binary("ffprobe")
    node_bin = find_node_runtime()
    ytdlp_ready = bool(
        shutil.which("yt-dlp") or importlib.util.find_spec("yt_dlp") is not None
    )

    wizard_completed = get_setting(paths.db_file, WIZARD_COMPLETED_KEY, "0") == "1"
    configured_secret_keys = sec.list_keys()

    return {
        "wizard_completed": wizard_completed,
        "runtime": {
            "ffmpeg_ready": _binary_available(ffmpeg_bin),
            "ffprobe_ready": _binary_available(ffprobe_bin),
            "node_ready": bool(node_bin and _binary_available(node_bin)),
            "ytdlp_ready": ytdlp_ready,
            "ffmpeg_path": ffmpeg_bin,
            "node_path": node_bin or "",
        },
        "workspace_count": len(workspaces),
        "active_workspace_id": active_ws_id,
        "active_workspace": active_ws,
        "configured_secrets": configured_secret_keys,
        "key_pool_count": len(pooled_keys),
        "connected_channels_count": _count_rows(
            paths.db_file, "SELECT COUNT(*) AS c FROM accounts WHERE enabled = 1"
        ),
        "defaults": {
            "role": cfg.role,
            "daily_usd": cfg.budget.daily_usd,
            "api_fallback": cfg.ai.policy.api_fallback,
            "timezone": cfg.schedule.timezone,
            "vi_provider": cfg.voice.vi_provider,
            "vi_voice": cfg.voice.vi_voice,
        },
    }


def complete_onboarding(
    paths: AppPaths,
    payload: dict[str, Any],
    secrets_store: SecretsStore | None = None,
) -> dict[str, Any]:
    """Saves initial Workspace, AI policy/keys, Voice defaults, and marks Welcome Wizard done."""
    sec = secrets_store or SecretsStore(paths.secrets_file)

    ws_cfg = payload.get("workspace")
    if isinstance(ws_cfg, dict) and ws_cfg:
        mode = str(ws_cfg.get("mode") or "update").strip().lower()
        name = str(ws_cfg.get("name") or "").strip()
        niche = str(ws_cfg.get("niche") or "general").strip() or "general"
        policy = str(ws_cfg.get("content_policy") or "strict_footage").strip()
        approval = str(ws_cfg.get("approval_mode") or "single").strip()
        ratio = str(ws_cfg.get("default_aspect_ratio") or "9:16").strip()
        style = str(ws_cfg.get("style_preset") or "tiktok_karaoke").strip()

        if mode == "create" and name:
            new_ws_id = create_workspace(
                paths.db_file,
                name=name,
                niche=niche,
                content_policy=policy,
                approval_mode=approval,
                default_aspect_ratio=ratio,
                style_preset=style,
                actor="wizard",
            )
            set_active_workspace_id(paths.db_file, new_ws_id, actor="wizard")
        else:
            ws_id = int(ws_cfg.get("id") or get_active_workspace_id(paths.db_file))
            update_workspace(
                paths.db_file,
                ws_id,
                name=name or None,
                niche=niche,
                content_policy=policy,
                approval_mode=approval,
                default_aspect_ratio=ratio,
                style_preset=style,
                actor="wizard",
            )
            set_active_workspace_id(paths.db_file, ws_id, actor="wizard")

    cfg = load_settings(paths.config_file)
    if payload.get("daily_usd") is not None:
        cfg.budget.daily_usd = max(0.0, float(payload["daily_usd"]))
    if payload.get("api_fallback"):
        fb = str(payload["api_fallback"]).strip().lower()
        if fb in ("auto", "ask", "never"):
            cfg.ai.policy.api_fallback = fb  # type: ignore[assignment]
    if payload.get("timezone"):
        cfg.schedule.timezone = str(payload["timezone"]).strip()
    if payload.get("vi_provider"):
        cfg.voice.vi_provider = str(payload["vi_provider"]).strip()
    if payload.get("vi_voice"):
        cfg.voice.vi_voice = str(payload["vi_voice"]).strip()
    save_settings(paths.config_file, cfg)

    raw_secrets = payload.get("secrets")
    if isinstance(raw_secrets, dict):
        for k, v in raw_secrets.items():
            key_name = str(k).strip()
            val = str(v).strip()
            if key_name and val:
                sec.set(key_name, val)

    pooled = payload.get("pooled_keys")
    if isinstance(pooled, list):
        for item in pooled:
            if not isinstance(item, dict):
                continue
            raw_val = str(item.get("raw_secret") or "").strip()
            prov = str(item.get("provider") or "").strip()
            if raw_val and prov:
                add_pooled_key(
                    paths,
                    provider=prov,
                    raw_secret=raw_val,
                    label=str(item.get("label") or "").strip(),
                    priority=int(item.get("priority") or 0),
                    secrets_store=sec,
                )

    set_setting(paths.db_file, WIZARD_COMPLETED_KEY, "1")
    with get_conn(paths.db_file) as conn:
        record_audit(
            conn,
            actor="wizard",
            action="onboarding.completed",
            object_type="system",
            detail=f"ws={get_active_workspace_id(paths.db_file)}",
        )
    return get_onboarding_status(paths, secrets_store=sec)


def reset_onboarding(
    paths: AppPaths,
    secrets_store: SecretsStore | None = None,
) -> dict[str, Any]:
    """Marks the Welcome Wizard incomplete so the user can re-run setup."""
    set_setting(paths.db_file, WIZARD_COMPLETED_KEY, "0")
    with get_conn(paths.db_file) as conn:
        record_audit(
            conn,
            actor="wizard",
            action="onboarding.reset",
            object_type="system",
        )
    return get_onboarding_status(paths, secrets_store=secrets_store)


def get_backup_summary(
    paths: AppPaths,
    secrets_store: SecretsStore | None = None,
) -> dict[str, Any]:
    """Returns database, workspace, secret, and local `.vcx` backup snapshot statistics."""
    sec = secrets_store or SecretsStore(paths.secrets_file)
    paths.backups_dir.mkdir(parents=True, exist_ok=True)
    snapshots = [
        {
            "filename": f.name,
            "size_bytes": int(f.stat().st_size),
        }
        for f in sorted(paths.backups_dir.glob("*.vcx"), key=lambda p: p.stat().st_mtime, reverse=True)[:15]
    ]
    return {
        "db_size_bytes": int(paths.db_file.stat().st_size) if paths.db_file.is_file() else 0,
        "workspaces": _count_rows(paths.db_file, "SELECT COUNT(*) AS c FROM workspaces WHERE archived = 0"),
        "products": _count_rows(paths.db_file, "SELECT COUNT(*) AS c FROM products WHERE hidden = 0"),
        "workflows": _count_rows(paths.db_file, "SELECT COUNT(*) AS c FROM workflows"),
        "channels": _count_rows(paths.db_file, "SELECT COUNT(*) AS c FROM accounts WHERE enabled = 1"),
        "pooled_keys": _count_rows(paths.db_file, "SELECT COUNT(*) AS c FROM api_key_pool"),
        "secrets_count": len(sec.list_keys()),
        "snapshots": snapshots,
    }
