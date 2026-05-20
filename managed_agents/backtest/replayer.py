"""HistoricalReplayer — 历史数据重放层.

用历史 K 线数据（腾讯财经 HTTP API）替代实时行情，让 Agent 链在指定历史日期上运行。
"""

import json
import logging
import urllib.request
from datetime import datetime, timedelta

import pandas as pd

logger = logging.getLogger(__name__)

# 腾讯财经 K 线 API 模板
_TX_KL_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},day,,,{count},qfq"

# 市场前缀映射
def _tx_market(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith("8"):
        return "bj"
    return "sz"


class HistoricalReplayer:
    """包装 MarketSkills，将实时数据替换为指定日期的历史数据."""

    def __init__(self, target_date: str):
        """
        Args:
            target_date: 目标交易日，格式 YYYY-MM-DD
        """
        self.target_date = target_date
        self._dt = datetime.strptime(target_date, "%Y-%m-%d")
        self._kline_cache: dict[str, pd.DataFrame] = {}
        self._quote_cache: dict[str, dict] = {}

    # ── 历史行情 ──

    def get_quote(self, codes: list[str]) -> dict:
        """获取指定日期个股行情（用日K线模拟）。"""
        quotes = []
        for code in codes:
            q = self._get_single_quote(code)
            if q:
                quotes.append(q)
        return {"quotes": quotes}

    def _get_single_quote(self, code: str) -> dict | None:
        if code in self._quote_cache:
            return self._quote_cache[code]

        kline = self._get_kline(code, count=10)
        if kline.empty:
            return None

        target_date_str = self.target_date
        matching = kline[kline.index == target_date_str]
        if matching.empty:
            return None

        idx = kline.index.get_loc(target_date_str)
        r = kline.iloc[idx]
        prev = kline.iloc[idx - 1] if idx > 0 else r

        q = {
            "code": code,
            "date": target_date_str,
            "open": float(r["open"]),
            "high": float(r["high"]),
            "low": float(r["low"]),
            "close": float(r["close"]),
            "volume": float(r["volume"]),
            "pct_chg": round((float(r["close"]) / float(prev["close"]) - 1) * 100, 2)
            if float(prev.get("close", 0)) > 0 else 0,
        }
        self._quote_cache[code] = q
        return q

    def get_kline(self, code: str, count: int = 20) -> dict:
        """获取历史K线序列。"""
        kline = self._get_kline(code, count=count)
        if kline.empty:
            return {"code": code, "kline": []}

        records = []
        for idx, row in kline.iterrows():
            records.append({
                "date": str(idx)[:10],
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
            })
        return {"code": code, "kline": records}

    def _get_kline(self, code: str, count: int = 20) -> pd.DataFrame:
        """从腾讯财经获取历史日K线（HTTP API）。"""
        cache_key = f"{code}_{count}"
        if cache_key in self._kline_cache:
            return self._kline_cache[cache_key]

        try:
            url = _TX_KL_URL.format(market=_tx_market(code), code=str(code).zfill(6), count=count + 10)
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read().decode("utf-8"))

            key = f"{_tx_market(code)}{str(code).zfill(6)}"
            records = data.get("data", {}).get(key, {}).get("day", [])
            if not records:
                records = data.get("data", {}).get(key, {}).get("qfqday", [])

            if not records:
                return pd.DataFrame()

            # Tencent K-line format: [date, open, close, high, low, volume]
            rows = []
            for r in records:
                rows.append({
                    "date": r[0],
                    "open": float(r[1]),
                    "close": float(r[2]),
                    "high": float(r[3]),
                    "low": float(r[4]),
                    "volume": float(r[5]) if len(r) > 5 else 0,
                })

            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()

            # 过滤到目标日期及之前
            df = df[df.index <= self.target_date]
            df = df.tail(count)
        except Exception as e:
            logger.debug(f"K线获取失败 {code}: {e}")
            df = pd.DataFrame()

        self._kline_cache[cache_key] = df
        return df

    # ── 热点模拟 ──

    def get_sector_hotspots(self) -> dict:
        return {
            "sectors": [],
            "_note": "历史热点数据需从缓存加载",
        }

    # ── 北向资金模拟 ──

    def get_northbound(self) -> dict:
        return {
            "total": 0,
            "_note": "历史北向数据需从专门数据源获取",
        }

    # ── 快讯模拟 ──

    def get_flash_news(self, limit: int = 10) -> dict:
        return {
            "count": 0,
            "news": [],
            "_note": "历史快讯数据需从缓存获取",
        }

    # ── 前向收益计算 ──

    def _get_kline_full(self, code: str, count: int = 60) -> pd.DataFrame:
        """获取包含目标日期之后数据的完整K线（用于计算前向收益）。"""
        try:
            url = _TX_KL_URL.format(market=_tx_market(code), code=str(code).zfill(6), count=count + 10)
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Mozilla/5.0")
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read().decode("utf-8"))

            key = f"{_tx_market(code)}{str(code).zfill(6)}"
            records = data.get("data", {}).get(key, {}).get("day", [])
            if not records:
                records = data.get("data", {}).get(key, {}).get("qfqday", [])

            if not records:
                return pd.DataFrame()

            rows = []
            for r in records:
                rows.append({
                    "date": r[0],
                    "open": float(r[1]),
                    "close": float(r[2]),
                    "high": float(r[3]),
                    "low": float(r[4]),
                    "volume": float(r[5]) if len(r) > 5 else 0,
                })

            df = pd.DataFrame(rows)
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date").sort_index()
            return df
        except Exception as e:
            logger.debug(f"完整K线获取失败 {code}: {e}")
            return pd.DataFrame()

    def get_forward_returns(self, code: str, days_list: list[int] = None) -> dict:
        """计算目标日期之后的收益（用于验证决策质量）。"""
        if days_list is None:
            days_list = [1, 3, 5, 10, 20]

        kline = self._get_kline_full(code, count=60)
        if kline.empty:
            return {}

        if self.target_date not in kline.index:
            return {}

        idx = kline.index.get_loc(self.target_date)
        entry_price = float(kline.iloc[idx]["close"])

        result = {"code": code, "entry_date": self.target_date, "entry_price": entry_price}
        for days in days_list:
            if idx + days < len(kline):
                fwd_price = float(kline.iloc[idx + days]["close"])
                ret = round((fwd_price / entry_price - 1) * 100, 2)
                result[f"ret_{days}d"] = ret
                result[f"price_{days}d"] = fwd_price
            else:
                result[f"ret_{days}d"] = None
                result[f"price_{days}d"] = None

        return result

    def get_batch_forward_returns(self, codes: list[str], days: int = 5) -> dict[str, dict]:
        """批量计算前向收益。"""
        results = {}
        for code in codes:
            r = self.get_forward_returns(code, [days])
            if r:
                results[code] = r
        return results
