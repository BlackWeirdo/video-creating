"""Reference resolver converting internal assets/characters/products/uploads to `data:` URLs for Muse."""
from __future__ import annotations

import base64
import secrets
from pathlib import Path
from typing import Any

from videocreator.db import get_conn, query_one, record_audit
from videocreator.muse_gateway.errors import MuseInputError
from videocreator.paths import AppPaths
from videocreator.pipeline.ffmpeg import run_ffmpeg
from videocreator.safe_paths import resolve_within, validated_extension
from videocreator.workspaces import require_workspace

MAX_MUSE_IMAGE_REF_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_MUSE_MEDIA_REF_BYTES = 40 * 1024 * 1024  # 40 MB

ALLOWED_REF_EXTENSIONS: dict[str, str] = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
}


def stage_uploaded_muse_ref(
    paths: AppPaths,
    *,
    filename: str | None,
    data: bytes,
    workspace_id: int,
) -> dict[str, Any]:
    """Saves an uploaded image/video/audio reference into `work/muse_refs/` with size & extension guards."""
    require_workspace(paths.db_file, workspace_id)
    ext = validated_extension(filename, ALLOWED_REF_EXTENSIONS.keys(), default_ext=".png")
    mime = ALLOWED_REF_EXTENSIONS[ext]
    cap = MAX_MUSE_IMAGE_REF_BYTES if mime.startswith("image/") else MAX_MUSE_MEDIA_REF_BYTES
    if not data:
        raise MuseInputError("Tệp tham chiếu rỗng")
    if len(data) > cap:
        raise MuseInputError(f"Tệp tham chiếu vượt quá giới hạn {cap // (1024 * 1024)} MB")

    ref_dir = paths.work_dir / "muse_refs"
    ref_dir.mkdir(parents=True, exist_ok=True)
    upload_id = f"mref_{workspace_id}_{secrets.token_hex(8)}{ext}"
    dest = resolve_within(ref_dir, upload_id)
    dest.write_bytes(data)
    return {
        "upload_id": upload_id,
        "mime_type": mime,
        "bytes": len(data),
    }


def _file_to_data_url(file_path: Path) -> str:
    if not file_path.is_file():
        raise MuseInputError(f"Tệp tham chiếu không tồn tại: {file_path.name}")
    ext = file_path.suffix.lower()
    mime = ALLOWED_REF_EXTENSIONS.get(ext, "image/png")
    cap = MAX_MUSE_IMAGE_REF_BYTES if mime.startswith("image/") else MAX_MUSE_MEDIA_REF_BYTES
    raw = file_path.read_bytes()
    if len(raw) > cap:
        raise MuseInputError(f"Tệp tham chiếu '{file_path.name}' vượt quá {cap // (1024 * 1024)} MB")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def validate_muse_refs_policy(
    paths: AppPaths,
    *,
    workspace_id: int,
    refs: list[dict[str, Any]],
    actor: str = "api",
) -> None:
    """Validates `content_policy`, real-face consent, and trend-clip remix consent BEFORE queueing."""
    if len(refs) > 16:
        raise MuseInputError("Muse tối đa 16 tệp tham chiếu trên một yêu cầu")
    ws = require_workspace(paths.db_file, workspace_id)
    policy = str(ws.get("content_policy") or "strict_footage")

    for ref in refs:
        rtype = str(ref.get("type") or "").strip().lower()
        if rtype == "product" and policy == "strict_footage":
            raise PermissionError(
                "Workspace 'strict_footage' cấm dùng ảnh sản phẩm làm tham chiếu sinh AI (BR-PRD-01)."
            )
        if rtype == "trend_clip":
            if policy != "full_ai":
                raise PermissionError(
                    "Remix chuyển động từ clip xu hướng chỉ cho phép trên Workspace 'full_ai'."
                )
            if not ref.get("rights_confirmed"):
                raise PermissionError(
                    "Cần xác nhận quyền sử dụng (rights_confirmed=true) khi gửi clip xu hướng làm tham chiếu."
                )
            with get_conn(paths.db_file) as conn:
                record_audit(
                    conn,
                    actor=actor,
                    action="muse.trend_clip_ref_consent",
                    object_type="trend_item",
                    object_id=int(ref.get("id") or 0),
                    detail=f"workspace={workspace_id}",
                )
        if ref.get("real_face"):
            if not ref.get("face_consent_confirmed"):
                raise PermissionError(
                    "Ảnh/video có khuôn mặt người thật bắt buộc xác nhận đồng ý (face_consent_confirmed=true)."
                )
            with get_conn(paths.db_file) as conn:
                record_audit(
                    conn,
                    actor=actor,
                    action="muse.real_face_consent",
                    object_type="muse_ref",
                    detail=f"workspace={workspace_id} type={rtype}",
                )


def resolve_task_refs_to_data_urls(
    paths: AppPaths,
    *,
    workspace_id: int,
    refs: list[dict[str, Any]],
) -> list[str]:
    """Resolves stored lightweight `refs` descriptors into `data:` URLs right when submitting to Gateway."""
    validate_muse_refs_policy(paths, workspace_id=workspace_id, refs=refs, actor="dispatcher")
    out: list[str] = []
    for ref in refs:
        rtype = str(ref.get("type") or "").strip().lower()
        if rtype == "character":
            cid = int(ref.get("id") or 0)
            row = query_one(paths.db_file, "SELECT cutout_image_path, ref_image_path FROM characters WHERE id = ?", (cid,))
            rel = str((row or {}).get("cutout_image_path") or (row or {}).get("ref_image_path") or "")
            if not rel:
                raise MuseInputError(f"Nhân vật #{cid} chưa có ảnh tham chiếu")
            out.append(_file_to_data_url(resolve_within(paths.media_dir, rel)))
        elif rtype == "ai_image":
            iid = int(ref.get("id") or 0)
            row = query_one(paths.db_file, "SELECT image_path FROM ai_images WHERE id = ?", (iid,))
            rel = str((row or {}).get("image_path") or "")
            if not rel:
                raise MuseInputError(f"Ảnh AI #{iid} không tồn tại")
            out.append(_file_to_data_url(resolve_within(paths.media_dir, rel)))
        elif rtype == "product":
            pid = int(ref.get("id") or 0)
            row = query_one(paths.db_file, "SELECT photo_path FROM products WHERE id = ?", (pid,))
            rel = str((row or {}).get("photo_path") or "")
            if not rel:
                raise MuseInputError(f"Sản phẩm #{pid} chưa có ảnh")
            out.append(_file_to_data_url(resolve_within(paths.media_dir, rel)))
        elif rtype == "upload":
            uid = str(ref.get("upload_id") or "").strip()
            out.append(_file_to_data_url(resolve_within(paths.work_dir / "muse_refs", uid)))
        elif rtype == "media_rel":
            rel = str(ref.get("path") or "").strip()
            out.append(_file_to_data_url(resolve_within(paths.media_dir, rel)))
        elif rtype == "work_rel":
            rel = str(ref.get("path") or "").strip()
            out.append(_file_to_data_url(resolve_within(paths.work_dir, rel)))
        elif rtype == "footage_frame":
            fid = int(ref.get("id") or 0)
            ts = max(0.0, float(ref.get("timestamp_s") or 0.5))
            frow = query_one(paths.db_file, "SELECT path FROM footage WHERE id = ?", (fid,))
            if not frow or not frow.get("path"):
                raise MuseInputError(f"Footage #{fid} không tồn tại")
            src_vid = resolve_within(paths.media_dir, str(frow["path"]))
            frame_png = paths.work_dir / "muse_refs" / f"footage_{fid}_{int(ts * 100)}.png"
            frame_png.parent.mkdir(parents=True, exist_ok=True)
            run_ffmpeg(["-ss", f"{ts:.2f}", "-i", str(src_vid), "-frames:v", "1", "-c:v", "png", str(frame_png)])
            out.append(_file_to_data_url(frame_png))
        elif rtype == "trend_clip":
            tid = int(ref.get("id") or 0)
            trow = query_one(paths.db_file, "SELECT ref_video_path FROM trend_items WHERE id = ?", (tid,))
            rel = str((trow or {}).get("ref_video_path") or "")
            if not rel:
                raise MuseInputError(f"Trend #{tid} chưa tải video tham chiếu")
            src_vid = resolve_within(paths.media_dir, rel)
            dur = min(15.0, max(2.0, float(ref.get("max_seconds") or 12.0)))
            trimmed = paths.work_dir / "muse_refs" / f"trend_{tid}_{int(dur)}s.mp4"
            trimmed.parent.mkdir(parents=True, exist_ok=True)
            run_ffmpeg(["-i", str(src_vid), "-t", f"{dur:.1f}", "-c:v", "libx264", "-preset", "veryfast", "-an", str(trimmed)])
            out.append(_file_to_data_url(trimmed))
        else:
            raise MuseInputError(f"Loại tham chiếu Muse không hợp lệ: '{rtype}'")
    return out


__all__ = [
    "ALLOWED_REF_EXTENSIONS",
    "MAX_MUSE_IMAGE_REF_BYTES",
    "MAX_MUSE_MEDIA_REF_BYTES",
    "resolve_task_refs_to_data_urls",
    "stage_uploaded_muse_ref",
    "validate_muse_refs_policy",
]
