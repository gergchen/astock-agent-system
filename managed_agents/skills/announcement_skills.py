"""公告 Skill — 直接 import astock_data 模块."""

import logging

logger = logging.getLogger(__name__)


class AnnouncementSkills:
    """封装 astock_data.announcement，供 Agent 调用."""

    def get_announcements(self, code: str) -> dict:
        """获取个股公告列表（巨潮资讯）。

        Args:
            code: 股票代码
        """
        from astock_data.announcement import get_announcements

        items = get_announcements(code)
        return {"code": code, "count": len(items), "announcements": items[:20]}

    def get_latest_announcements(self, code: str) -> dict:
        """获取个股最新公告内容（mootdx）。

        Args:
            code: 股票代码
        """
        from astock_data.announcement import get_latest_announcements

        text = get_latest_announcements(code)
        return {"code": code, "content": text}
