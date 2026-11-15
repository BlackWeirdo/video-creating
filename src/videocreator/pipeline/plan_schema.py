"""Schemas the writer and checker AI roles must answer with, and per-platform caption limits."""
from __future__ import annotations

from pydantic import BaseModel, Field

DEFAULT_FORMULAS: tuple[str, ...] = (
    "hook-first",
    "craft-process",
    "detail-closeup",
    "story-emotion",
    "collection",
)


PLATFORM_CHAR_LIMITS: dict[str, int] = {
    "facebook": 2200,
    "instagram": 2200,
    "threads": 500,
    "tiktok": 2200,
}


PLATFORM_HASHTAG_LIMITS: dict[str, int] = {
    "facebook": 5,
    "instagram": 8,
    "threads": 1,
    "tiktok": 6,
}


class PlatformCaption(BaseModel):
    text: str = Field(description="Nội dung caption cho nền tảng này")
    hashtags: list[str] = Field(description="Danh sách hashtag (không vượt giới hạn nền tảng)")


class PlatformCaptions(BaseModel):
    facebook: PlatformCaption
    instagram: PlatformCaption
    threads: PlatformCaption
    tiktok: PlatformCaption


class PlannedShot(BaseModel):
    shot_id: int = Field(description="ID của shot có thật trong danh sách được cung cấp")
    start_s: float = Field(description="Mốc bắt đầu trong footage gốc (giây)")
    duration_s: float = Field(description="Thời lượng lấy của shot (giây, >= 0.7)")
    text: str = Field(description="Dòng phụ đề/lời thoại ngắn cho shot này")


class VideoPlanItem(BaseModel):
    formula: str = Field(description="Tên công thức dựng (VD: hook-first, craft-process, detail-closeup)")
    title: str = Field(description="Tiêu đề ngắn gọn của kịch bản")
    shots: list[PlannedShot] = Field(description="Danh sách các shot theo thứ tự xuất hiện")
    captions: PlatformCaptions = Field(description="4 bộ caption riêng cho Facebook, Instagram, Threads, TikTok")


class RemixPlansBatch(BaseModel):
    plans: list[VideoPlanItem]


class FactCheckResult(BaseModel):
    unverified_claims: list[str] = Field(
        description="Danh sách nguyên văn các câu/cụm từ trong lời thoại hoặc caption tự bịa thông số không có trong facts_json; rỗng nếu hoàn toàn hợp lệ"
    )
