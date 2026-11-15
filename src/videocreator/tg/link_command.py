"""The `/link` command: one pasted Facebook/Instagram video becomes a pinned trend item."""
from __future__ import annotations

import logging

from videocreator.config import load_settings
from videocreator.paths import AppPaths
from videocreator.tg.access import check_two_layer_allowlist, telegram_actor

logger = logging.getLogger("videocreator.tg.commands")


def handle_link_command(
    paths: AppPaths,
    *,
    chat_id: int | None,
    user_id: int | None,
    user_name: str,
    args: str,
) -> tuple[bool, str]:
    """`/link <url>`: adds one Facebook/Instagram video as a pinned trend item.

    Blocking (runs yt-dlp): the bot calls it with `asyncio.to_thread`. Same two-layer allowlist
    as other state-changing commands. `args` keeps its case: Instagram codes are case-sensitive.
    """
    from videocreator.trends.link_parse import PLATFORM_LABELS, extract_first_url
    from videocreator.trends.links import add_pasted_link

    settings = load_settings(paths.config_file)
    allowed, err_msg = check_two_layer_allowlist(chat_id, user_id, settings)
    if not allowed:
        return False, err_msg or "Không có quyền thực hiện lệnh này."
    url = extract_first_url(args)
    if not url:
        return False, "Gửi kèm link: /link https://www.facebook.com/reel/..."
    try:
        trend_id, item = add_pasted_link(paths, url, actor=telegram_actor(user_id, user_name))
    except ValueError as exc:
        return False, f"❌ {exc}"
    except Exception:  # never leave the user without a reply
        logger.exception("/link failed for %s", url)
        return False, "❌ Lỗi nội bộ khi đọc link. Đã ghi vào log; hãy thử lại sau."
    views = f"{int(item.metrics.get('views') or 0):,}".replace(",", ".")  # 9.900 (Vietnamese grouping)
    platform = PLATFORM_LABELS.get(item.source, item.source)
    return True, (
        f"✅ Đã thêm video {platform} #{trend_id} của {item.author or 'không rõ tác giả'} "
        f"({views} lượt xem). App đang tải và phân tích, xong sẽ ưu tiên đưa vào đề xuất."
    )
