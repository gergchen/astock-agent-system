"""新闻 + 全球资讯 Skill — 直接 import astock_data 模块."""

import logging

logger = logging.getLogger(__name__)


class NewsSkills:
    """封装 astock_data.news，供 Agent 调用."""

    def get_stock_news(self, code: str) -> dict:
        """获取个股相关新闻。

        Args:
            code: 股票代码
        """
        from astock_data.news import get_stock_news

        items = get_stock_news(code)
        return {"code": code, "count": len(items), "news": items[:20]}

    def get_flash_news(self, limit: int = 20) -> dict:
        """获取财联社最新快讯。

        Args:
            limit: 返回条数
        """
        from astock_data.news import get_flash_news

        items = get_flash_news()
        items = items[:limit] if items else []
        return {"count": len(items), "news": items}

    def get_global_news(self) -> dict:
        """获取全球宏观资讯."""
        from astock_data.news import get_global_news

        items = get_global_news()
        return {"count": len(items), "news": items[:20]}

    def search_geopolitical_news(self, query: str, max_results: int = 20) -> dict:
        """搜索地缘政治新闻。

        Args:
            query: 搜索关键词
            max_results: 最大条数
        """
        from astock_data.news import search_geopolitical_news

        items = search_geopolitical_news(query, max_results=max_results)
        return {"query": query, "count": len(items), "news": items}

    def get_top_headlines(self, category: str = "world", max_results: int = 20) -> dict:
        """获取全球头条新闻。

        Args:
            category: 新闻类别
            max_results: 最大条数
        """
        from astock_data.news import get_top_headlines

        items = get_top_headlines(category=category, max_results=max_results)
        return {"category": category, "count": len(items), "headlines": items}
