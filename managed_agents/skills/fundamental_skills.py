"""财务 + 基础数据 Skill — 直接 import astock_data 模块."""

import logging

logger = logging.getLogger(__name__)

F10_CATEGORIES = [
    "最新提示", "公司概况", "财务分析", "股东研究",
    "股本结构", "资本运作", "业内点评", "行业分析", "公司大事",
]


class FundamentalSkills:
    """封装 astock_data.fundamental，供 Agent 调用."""

    def get_finance(self, code: str) -> dict:
        """获取个股财务快照（37 项指标）。

        Args:
            code: 股票代码
        """
        from astock_data.fundamental import get_finance

        data = get_finance(code)
        return {"code": code, "finance": data}

    def get_f10(self, code: str, category: str = "公司概况") -> dict:
        """获取个股 F10 资料（9 大类）。

        Args:
            code: 股票代码
            category: 资料类别，见 F10_CATEGORIES
        """
        from astock_data.fundamental import get_f10

        text = get_f10(code, category=category)
        return {"code": code, "category": category, "content": text}

    def get_stock_basics(self, code: str) -> dict:
        """获取个股基本信息（行业/市值/流通股本）。

        Args:
            code: 股票代码
        """
        from astock_data.fundamental import get_stock_basics

        data = get_stock_basics(code)
        return {"code": code, "basics": data}
