"""Reusable Studio templates: a saved scene re-rendered with new shots and text, no agent (Phase 17, FR-STD-09)."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.paths import AppPaths
from videocreator.studio.session import create_studio_session, enqueue_studio_job

MAX_TEMPLATE_SCENE_S = 3.5


def save_studio_template(
    paths: AppPaths,
    session_id: int,
    *,
    name: str,
    props_schema: dict[str, Any] | None = None,
    actor: str = "ui",
) -> int:
    """Saves the scene code of a rendered Studio session as a reusable template (`FR-STD-09`)."""
    sess = query_one(
        paths.db_file, "SELECT * FROM studio_sessions WHERE id = ?", (session_id,)
    )
    if sess is None:
        raise LookupError(f"Studio session #{session_id} not found")

    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Template name is required")

    scene_file = paths.media_dir / "studio" / str(session_id) / "src" / "Scene.tsx"
    if not scene_file.exists():
        raise ValueError(f"Phiên Studio #{session_id} chưa có mã cảnh để lưu làm mẫu")
    rel_tpl_dir = f"studio_templates/tpl_{session_id}"
    abs_tpl_dir = paths.media_dir / rel_tpl_dir
    # Only the scene code: script, footage, renders and node_modules stay in the session.
    (abs_tpl_dir / "src").mkdir(parents=True, exist_ok=True)
    shutil.copy2(scene_file, abs_tpl_dir / "src" / "Scene.tsx")

    schema_obj = props_schema or {
        "base_prompt": sess.get("prompt", ""),
        "video_id": sess.get("video_id"),
    }

    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            INSERT INTO studio_templates (name, project_path, props_schema_json)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                project_path = excluded.project_path,
                props_schema_json = excluded.props_schema_json
            """,
            (clean_name, rel_tpl_dir, json.dumps(schema_obj, ensure_ascii=False)),
        )
        row = conn.execute(
            "SELECT id FROM studio_templates WHERE name = ?", (clean_name,)
        ).fetchone()
        tpl_id = int(row["id"]) if row else int(cur.lastrowid or 0)
        record_audit(
            conn,
            actor=actor,
            action="studio_template.saved",
            object_type="studio_template",
            object_id=tpl_id,
            detail=f"session_id={session_id}, name={clean_name}",
        )
        return tpl_id


def list_studio_templates(db_file: Path) -> list[dict[str, Any]]:
    return query_all(db_file, "SELECT * FROM studio_templates ORDER BY id DESC")


def start_render_from_template(
    paths: AppPaths,
    template_id: int,
    *,
    shot_ids: list[int],
    subtitles: list[str] | None = None,
    title: str | None = None,
    options: dict[str, Any] | None = None,
) -> int:
    """Queues a new video that reuses the template's scene code with the chosen shots and text (`FR-STD-09`).

    No agent is involved: the app writes the script, then the usual scan, Remotion render and export
    run in the `studio` job. Returns the new Studio session id.
    """
    tpl = query_one(
        paths.db_file, "SELECT * FROM studio_templates WHERE id = ?", (template_id,)
    )
    if tpl is None:
        raise LookupError(f"Studio template #{template_id} not found")
    scene_file = paths.media_dir / str(tpl["project_path"]) / "src" / "Scene.tsx"
    if not scene_file.exists():
        raise ValueError(f"Mẫu '{tpl['name']}' không còn mã cảnh trên đĩa")
    if not shot_ids:
        raise ValueError("At least one shot_id is required to render from template")

    scenes: list[dict[str, Any]] = []
    for idx, sid in enumerate(shot_ids):
        s_row = query_one(paths.db_file, "SELECT * FROM shots WHERE id = ?", (sid,))
        if s_row is None:
            raise LookupError(f"Shot #{sid} not found")
        dur = min(MAX_TEMPLATE_SCENE_S, float(s_row["end_s"]) - float(s_row["start_s"]))
        text = subtitles[idx].strip() if (subtitles and idx < len(subtitles)) else ""
        scenes.append({"shot_id": int(sid), "start_s": float(s_row["start_s"]), "duration_s": round(dur, 2), "text": text})

    name = str(tpl["name"])
    session_id = create_studio_session(
        paths,
        prompt=f"Dựng từ mẫu: {name}",
        options={**(options or {}), "template_id": int(template_id), "shot_ids": [int(s) for s in shot_ids], "auto_run": True},
        status="rendering",
    )
    session_dir = paths.media_dir / "studio" / str(session_id)
    (session_dir / "src").mkdir(parents=True, exist_ok=True)
    shutil.copy2(scene_file, session_dir / "src" / "Scene.tsx")
    (session_dir / "plan.json").write_text(
        json.dumps({"title": title or f"Từ mẫu {name}", "scenes": scenes}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    enqueue_studio_job(paths.db_file, session_id)
    return session_id
