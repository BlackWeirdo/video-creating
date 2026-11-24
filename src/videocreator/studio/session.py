"""Studio session state management, version history, and single-active-session guard (Phase 17, FR-STD-08, FR-STD-13)."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_all, query_one, record_audit
from videocreator.jobs import enqueue_job
from videocreator.jsonutil import loads_or
from videocreator.paths import AppPaths
from videocreator.workspaces import DEFAULT_WORKSPACE_ID, require_workspace

STUDIO_JOB_KIND = "studio"
BUSY_MESSAGE = "Một phiên Studio khác đang chạy (chỉ cho phép 1 phiên tại 1 thời điểm)."


class StudioBusyError(RuntimeError):
    """Raised when attempting to start a Studio session while another is actively running (`FR-STD-13`)."""


def has_active_studio_session(db_file: Path, *, exclude_id: int | None = None) -> bool:
    sql = "SELECT id FROM studio_sessions WHERE status IN ('analysing', 'planning', 'rendering')"
    params: list[Any] = []
    if exclude_id is not None:
        sql += " AND id != ?"
        params.append(int(exclude_id))
    row = query_one(db_file, sql, params)
    return row is not None


def session_options(sess: dict[str, Any]) -> dict[str, Any]:
    """Options of a session: `voice_lang`, `music_asset_id`, `sfx_asset_id`, `shot_ids`, `auto_run`, `template_id`."""
    try:
        options = json.loads(str(sess.get("options_json") or "{}"))
    except ValueError:
        return {}
    return options if isinstance(options, dict) else {}


def enqueue_studio_job(db_file: Path, session_id: int) -> int:
    return enqueue_job(db_file, STUDIO_JOB_KIND, ref_id=session_id)


def confirm_studio_plan(paths: AppPaths, session_id: int, *, actor: str = "ui") -> None:
    """The user accepted the script shown at the confirmation stop; queue the render (`FR-STD-05`)."""
    if has_active_studio_session(paths.db_file, exclude_id=session_id):
        raise StudioBusyError(BUSY_MESSAGE)
    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            "UPDATE studio_sessions SET status = 'rendering', error = NULL WHERE id = ? AND status = 'awaiting_confirm'",
            (session_id,),
        )
        if cur.rowcount != 1:
            raise ValueError(f"Phiên Studio #{session_id} không ở bước chờ xác nhận kịch bản")
        record_audit(
            conn, actor=actor, action="studio_session.plan_confirmed", object_type="studio_session", object_id=session_id
        )
    enqueue_studio_job(paths.db_file, session_id)


def request_studio_revision(paths: AppPaths, session_id: int, prompt: str, *, actor: str = "ui") -> None:
    """Queues a revision by prompt: of the script while it waits for confirmation, or of a finished video (`FR-STD-08`)."""
    clean = prompt.strip()
    if not clean:
        raise ValueError("Studio prompt is required")
    if has_active_studio_session(paths.db_file, exclude_id=session_id):
        raise StudioBusyError(BUSY_MESSAGE)
    linked = query_one(
        paths.db_file,
        """
        SELECT v.status AS video_status
        FROM studio_sessions s
        LEFT JOIN videos v ON s.video_id = v.id
        WHERE s.id = ?
        """,
        (session_id,),
    )
    if linked and str(linked.get("video_status") or "") in ("approved", "scheduled", "posted"):
        raise ValueError("Video của phiên Studio này đã được duyệt/lên lịch đăng; hãy tạo phiên Studio mới thay vì ghi đè.")
    with get_conn(paths.db_file) as conn:
        cur = conn.execute(
            """
            UPDATE studio_sessions SET status = 'planning', pending_prompt = ?, error = NULL
            WHERE id = ? AND status IN ('awaiting_confirm', 'done', 'failed')
            """,
            (clean, session_id),
        )
        if cur.rowcount != 1:
            raise ValueError(f"Phiên Studio #{session_id} đang chạy hoặc không tồn tại")
        record_audit(
            conn, actor=actor, action="studio_session.revision_requested",
            object_type="studio_session", object_id=session_id, detail=clean[:140],
        )
    enqueue_studio_job(paths.db_file, session_id)


def recover_stuck_studio_sessions(db_file: Path) -> int:
    """On startup: a session marked as running with no job left to run it is failed, so it stops blocking Studio."""
    with get_conn(db_file) as conn:
        cur = conn.execute(
            """
            UPDATE studio_sessions
            SET status = 'failed', error = 'Phiên bị ngắt giữa chừng (app tắt); bấm Sửa để chạy lại'
            WHERE status IN ('analysing', 'planning', 'rendering')
              AND id NOT IN (
                  SELECT ref_id FROM jobs
                  WHERE kind = ? AND ref_id IS NOT NULL AND status IN ('queued', 'running', 'waiting_quota')
              )
            """,
            (STUDIO_JOB_KIND,),
        )
        return int(cur.rowcount or 0)


def create_studio_session(
    paths: AppPaths,
    *,
    prompt: str,
    ref_item_id: int | None = None,
    video_id: int | None = None,
    options: dict[str, Any] | None = None,
    status: str = "planning",
    workspace_id: int = DEFAULT_WORKSPACE_ID,
    actor: str = "ui",
) -> int:
    """Creates a new `studio_sessions` row after enforcing the single-active-session rule (`FR-STD-13`).

    The caller queues the work with `enqueue_studio_job`.
    """
    if has_active_studio_session(paths.db_file):
        raise StudioBusyError(BUSY_MESSAGE)
    ws = require_workspace(paths.db_file, int(workspace_id))

    clean_prompt = prompt.strip()
    if not clean_prompt:
        raise ValueError("Studio prompt is required")

    with get_conn(paths.db_file) as conn:
        if video_id is None:
            v_cur = conn.execute(
                """
                INSERT INTO videos (engine, status, plan_json, captions_json, workspace_id)
                VALUES ('studio', 'planned', ?, '{}', ?)
                """,
                (
                    json.dumps(
                        {"title": f"Studio: {clean_prompt[:40]}", "formula": "studio-custom", "shots": []},
                        ensure_ascii=False,
                    ),
                    int(ws["id"]),
                ),
            )
            video_id = int(v_cur.lastrowid or 0)

        s_cur = conn.execute(
            """
            INSERT INTO studio_sessions (video_id, prompt, ref_item_id, status, cost_usd, versions_json, options_json, workspace_id)
            VALUES (?, ?, ?, ?, 0.0, '[]', ?, ?)
            """,
            (
                video_id,
                clean_prompt,
                ref_item_id,
                status,
                json.dumps(options or {}, ensure_ascii=False),
                int(ws["id"]),
            ),
        )
        session_id = int(s_cur.lastrowid or 0)
        record_audit(
            conn,
            actor=actor,
            action="studio_session.created",
            object_type="studio_session",
            object_id=session_id,
            detail=f"ws={ws['id']}, {clean_prompt[:120]}",
        )

    session_dir = paths.media_dir / "studio" / str(session_id)
    (session_dir / "public").mkdir(parents=True, exist_ok=True)
    return session_id


def list_studio_sessions(
    db_file: Path, *, workspace_id: int | None = None
) -> list[dict[str, Any]]:
    if workspace_id is not None:
        rows = query_all(
            db_file,
            "SELECT * FROM studio_sessions WHERE workspace_id = ? ORDER BY id DESC LIMIT 30",
            (int(workspace_id),),
        )
    else:
        rows = query_all(db_file, "SELECT * FROM studio_sessions ORDER BY id DESC LIMIT 30")
    out: list[dict[str, Any]] = []
    for r in rows:
        vers = loads_or(r.get("versions_json"), [])
        out.append({**r, "versions": vers})
    return out
