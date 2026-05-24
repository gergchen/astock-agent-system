"""行情/信号 Skill — 直接调用 astock_data 模块，零子进程开销.

每个方法返回的字段和限制都在 docstring 中注明，
Agent 在构造 prompt 时可读取这些信息了解数据能力边界。
"""

import logging

from astock_data.signal.ths_hotspot import get_hot_sectors, get_hot_stocks
from astock_data.signal.northbound import get_northbound_realtime
from astock_data.news.cls_news import get_flash_news as _get_flash_news
from astock_data.market.mootdx_quote import get_quotes as _get_quotes
from astock_data.market.tencent_finance import get_valuation as _get_valuation

logger = logging.getLogger(__name__)

# ST股票识别
_ST_PREFIXES = ("*ST", "ST")


def _is_st(name: str) -> bool:
    return bool(name and name.startswith(_ST_PREFIXES))


class MarketSkills:
    """封装 astock_data 数据源，供 Agent 调用.

    字段说明中的 ⚠️ 标记表示该字段在该数据源中不可用，
    Agent 不应在 prompt 中假设这些字段存在。
    """

    def get_hotspots(self) -> dict:
        """获取同花顺今日涨停/大涨股票列表。

        数据源: zx.10jqka.com.cn 打板列表
        更新频率: 盘中实时更新
        返回字段:
            total(int): 总股票数
            top_stocks(list): 前10只股票, 每只包含:
                - name(str): 股票名称 ⚠️ 含ST/*ST前缀
                - code(str): 6位股票代码
                - reason(str): 题材归因(编辑标签, 如"算力+机器人+AI")
                - market(str): 市场代码 (17=沪, 33=深)

        注意:
        - 该列表只收录已涨停或大涨股票，没有未涨停的数据
        - 没有涨幅%、换手率、成交额等字段
        - 题材归因是编辑标签不是官方行业分类
        - 返回数据不包含涨幅数据，无法判断是否封板
        """
        df = get_hot_stocks()
        if df.empty:
            return {"total": 0, "top_stocks": []}

        stocks = df.head(10).to_dict(orient="records")
        return {
            "total": len(df),
            "top_stocks": [
                {
                    "name": s.get("名称", ""),
                    "code": s.get("代码", ""),
                    "reason": s.get("题材归因", ""),
                    "market": s.get("市场", ""),
                }
                for s in stocks
            ],
        }

    def get_sector_hotspots(self) -> dict:
        """获取今日热点板块汇总（按题材归因聚合）。

        将同花顺热点列表中每只股票的题材归因标签按+拆分后计数聚合。
        例如"机器人+减速器"会计入机器人和减速器各1次。

        返回字段:
            sectors(list): 板块列表, 每项包含:
                - name(str): 概念名称 (如"机器人", "算力", "AI应用")
                - count(int): 含有该标签的涨停股票数量

        注意:
        - count 只代表该概念被编辑标注的次数，不代表可操作性
        - 包含ST板块，需注意过滤
        - 不含非涨停股票的数据
        """
        items = get_hot_sectors()
        return {
            "sectors": [
                {"name": i["sector"], "count": i["count"]}
                for i in items[:20]
            ]
        }

    def get_northbound(self) -> dict:
        """获取北向资金实时流向。

        数据源: data.hexin.cn 沪深港通
        更新频率: 交易日09:10-15:00每分钟

        返回字段:
            latest_time(str): 最新数据时间 (如"14:35")
            latest_hgt(float): 沪股通当日净买入(亿)
            latest_sgt(float): 深股通当日净买入(亿)
            total(float): 沪深合计净买入(亿)
            key_points(list): 整点时刻的快照, 每项:
                - time(str): 时间点
                - hgt(float): 沪股通累计净买入
                - sgt(float): 深股通累计净买入
            sources(list): 多个数据源的交叉验证结果

        注意:
        - 正值=净流入，负值=净流出
        - 单分钟波动大，看累计值趋势更可靠
        - 09:10-09:25为集合竞价时段数据
        - 午休(11:30-13:00)数据不变
        - hexin.cn预填全天262个时间点，未到的时间点是前日缓存
          必须按当前时间截取，不可直接用末条数据
        """
        from datetime import datetime

        df = get_northbound_realtime()
        if df.empty:
            return {"error": "暂无数据"}

        items = df.to_dict(orient="records")
        base_h = items[0]["hgt_yi"] or 0
        base_s = items[0]["sgt_yi"] or 0

        # 按当前时间截取，避免用前日缓存
        now_str = datetime.now().strftime("%H:%M")
        current_items = [i for i in items if i["time"] <= now_str]
        if not current_items:
            return {"error": f"暂无当前时段数据(当前{now_str})"}

        latest = current_items[-1]
        h = (latest["hgt_yi"] or 0) - base_h
        s = (latest["sgt_yi"] or 0) - base_s

        key_times = ["09:30", "10:00", "10:30", "11:00", "11:30",
                     "13:00", "13:30", "14:00", "14:30", "15:00"]
        key_points = []
        for item in items:
            if item["time"] in key_times and item["time"] <= now_str:
                key_points.append({
                    "time": item["time"],
                    "hgt": round((item["hgt_yi"] or 0) - base_h, 2),
                    "sgt": round((item["sgt_yi"] or 0) - base_s, 2),
                })

        # 交叉验证: 东方财富日线数据
        cross_sources = [
            {"source": "hexin.cn", "time": latest["time"],
             "hgt": round(h, 2), "sgt": round(s, 2), "total": round(h + s, 2)}
        ]
        try:
            import akshare as ak
            import requests
            em_url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
            em_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0",
                "Referer": "https://data.eastmoney.com/",
            }
            for name, code in [("沪股通", "001"), ("深股通", "003")]:
                p = {
                    "sortColumns": "TRADE_DATE", "sortTypes": "-1",
                    "pageSize": "1", "pageNumber": "1",
                    "reportName": "RPT_MUTUAL_DEAL_HISTORY",
                    "columns": "TRADE_DATE,FUND_INFLOW",
                    "source": "WEB", "client": "WEB",
                    "filter": f'(MUTUAL_TYPE="00{code}")',
                }
                r = requests.get(em_url, params=p, headers=em_headers, timeout=5)
                d = r.json()
                if d.get("result") and d["result"].get("data") and d["result"]["data"][0].get("FUND_INFLOW") is not None:
                    inflow = float(d["result"]["data"][0]["FUND_INFLOW"])
                    cross_sources.append({
                        "source": f"东方财富({name})",
                        "time": d["result"]["data"][0]["TRADE_DATE"],
                        "value": inflow,
                    })
        except Exception:
            pass

        return {
            "latest_time": latest["time"],
            "latest_hgt": round(h, 2),
            "latest_sgt": round(s, 2),
            "total": round(h + s, 2),
            "key_points": key_points,
            "sources": cross_sources,
        }

    def get_flash_news(self, limit: int = 10) -> dict:
        """获取财联社实时快讯。

        数据源: akshare → 财联社
        更新频率: 分钟级

        返回字段:
            count(int): 新闻条数
            news(list): 每条包含:
                - time(str): 发布时间
                - title(str): 标题 (可能为空)
                - content(str): 正文前200字 (可能为空)

        注意:
        - 是快讯不是深度报道，部分条目只有标题无正文
        - 部分新闻与A股无关（国际新闻等）
        - 可能包含重复或近似重复的内容
        """
        items = _get_flash_news()
        items = items[:limit] if items else []
        return {
            "count": len(items),
            "news": [
                {
                    "time": i.get("datetime", ""),
                    "title": i.get("title", ""),
                    "content": i.get("content", "")[:200],
                }
                for i in items
            ],
        }

    def get_index_quotes(self, codes: list[str] | None = None) -> dict:
        """获取主要指数实时行情。

        数据源: 腾讯财经 qt.gtimg.cn

        支持指数:
            000001 上证指数
            399001 深证成指
            399006 创业板指
            000688 科创50
            000300 沪深300

        返回字段: {代码: {name, price, change_pct, change_amt, last_close, high, low}}

        注意:
        - 午休时段数据不变
        - 指数涨幅与个股涨幅含义相同，正=涨负=跌
        """
        if codes is None:
            codes = ["000001", "399001", "399006", "000688", "000300"]

        raw = _get_valuation(codes)
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
