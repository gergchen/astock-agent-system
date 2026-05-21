"""行情/信号 Skill — 直接调用 astock_data 模块，零子进程开销."""

import logging

from astock_data.signal.ths_hotspot import get_hot_sectors, get_hot_stocks
from astock_data.signal.northbound import get_northbound_realtime
from astock_data.news.cls_news import get_flash_news as _get_flash_news
from astock_data.market.mootdx_quote import get_quotes as _get_quotes

logger = logging.getLogger(__name__)


class MarketSkills:
    """封装 astock_data 数据源，供 Agent 调用."""

    def get_hotspots(self) -> dict:
        df = get_hot_stocks()
        if df.empty:
            return {"total": 0, "top_stocks": []}
        stocks = df.head(10).to_dict(orient="records")
        return {
            "total": len(df),
            "top_stocks": [
                {"name": s.get("名称", ""), "code": s.get("代码", ""),
                 "reason": s.get("题材归因", ""), "market": s.get("市场", "")}
                for s in stocks
            ],
        }

    def get_sector_hotspots(self) -> dict:
        items = get_hot_sectors()
        return {
            "sectors": [
                {"name": i["sector"], "count": i["count"]}
                for i in items[:20]
            ]
        }

    def get_northbound(self) -> dict:
        df = get_northbound_realtime()
        if df.empty:
            return {"error": "暂无数据"}
        items = df.to_dict(orient="records")
        base_h = items[0]["hgt_yi"] or 0
        base_s = items[0]["sgt_yi"] or 0
        latest = items[-1]
        h = (latest["hgt_yi"] or 0) - base_h
        s = (latest["sgt_yi"] or 0) - base_s

        key_times = ["09:30", "10:00", "10:30", "11:00", "11:30",
                     "13:00", "13:30", "14:00", "14:30", "15:00"]
        key_points = []
        for item in items:
            if item["time"] in key_times:
                key_points.append({
                    "time": item["time"],
                    "hgt": round((item["hgt_yi"] or 0) - base_h, 2),
                    "sgt": round((item["sgt_yi"] or 0) - base_s, 2),
                })

        return {
            "latest_time": latest["time"],
            "latest_hgt": round(h, 2),
            "latest_sgt": round(s, 2),
            "total": round(h + s, 2),
            "key_points": key_points,
        }

    def get_flash_news(self, limit: int = 10) -> dict:
        items = _get_flash_news()
        items = items[:limit] if items else []
        return {
            "count": len(items),
            "news": [
                {"time": i.get("datetime", ""), "title": i.get("title", ""),
                 "content": i.get("content", "")[:200]}
                for i in items
            ],
        }

    def get_quote(self, codes: list[str]) -> dict:
        df = _get_quotes(codes)
        if df.empty:
            return {"quotes": []}
        return {"quotes": df.to_dict(orient="records")}

    def get_index_quotes(self, codes: list[str] | None = None) -> dict:
        """获取主要指数实时行情.

        Args:
            codes: 指数代码列表，默认监控五大核心指数.

        Returns:
            代码 -> {name, price, change_pct, change_amt, ...}
        """
        from astock_data.market.tencent_finance import get_valuation
        if codes is None:
            codes = ["000001", "399001", "399006", "000688", "000300"]
        raw = get_valuation(codes)
        return {
            code: {
                "name": q["name"],
                "price": q["price"],
                "change_pct": q["change_pct"],
                "change_amt": q["change_amt"],
                "last_close": q["last_close"],
                "high": q["high"],
                "low": q["low"],
            }
            for code, q in raw.items()
            if q["price"] > 0
        }
