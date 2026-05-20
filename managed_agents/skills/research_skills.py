"""研报 + 估值 Skill — 直接 import astock_data 模块."""

import logging

logger = logging.getLogger(__name__)


class ResearchSkills:
    """封装 astock_data.research + workflow，供 Agent 调用."""

    def get_reports(self, code: str, max_pages: int = 3) -> dict:
        """获取个股研报列表。

        Args:
            code: 股票代码
            max_pages: 最大翻页数
        """
        from astock_data.research import get_reports

        reports = get_reports(code, max_pages=max_pages)
        return {"code": code, "count": len(reports), "reports": reports[:15]}

    def get_consensus_eps(self, code: str) -> dict:
        """获取分析师一致预期 EPS。

        Args:
            code: 股票代码
        """
        from astock_data.research import get_consensus_eps

        data = get_consensus_eps(code)
        return {"code": code, "eps_consensus": data}

    def semantic_search(self, query: str, channel: str = "report", size: int = 30) -> dict:
        """问财语义搜索（研报/公告/新闻）。

        Args:
            query: 搜索语句
            channel: report|announcement|news
            size: 返回条数
        """
        from astock_data.research import semantic_search

        results = semantic_search(query, channel=channel, size=size)
        return {"query": query, "channel": channel, "count": len(results), "results": results}

    def full_valuation(self, code: str) -> dict:
        """个股完整估值（PE/PB/PEG/一致预期/估值水位）。

        Args:
            code: 股票代码
        """
        from astock_data.workflow import full_valuation

        data = full_valuation(code)
        return {"code": code, "valuation": data}

    def thematic_research(self, queries: list[str], channel: str = "report") -> dict:
        """题材产业链研究（跨股票搜索）。

        Args:
            queries: 搜索主题列表
            channel: report|announcement|news
        """
        from astock_data.workflow import thematic_research

        data = thematic_research(queries, channel=channel)
        return {"queries": queries, "result": data}
