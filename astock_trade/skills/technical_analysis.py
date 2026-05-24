"""技术分析 Skill — TA-Lib 指标、K线形态、筹码分布.

每个方法返回的字段在 docstring 中注明，Agent 在构造 prompt 时
可读取这些信息了解数据能力边界。
"""

import logging

from astock_data.market.mootdx_quote import get_kline
from astock_data.ta import (
    compute_indicators, get_latest_indicators,
    compute_patterns, get_latest_patterns,
    get_pattern_buy_signals, get_pattern_sell_signals,
    get_buy_signals, get_sell_signals, get_technical_signals,
    compute_chip_distribution,
)

logger = logging.getLogger(__name__)

# 日K线默认获取天数（约1年交易数据，足够计算250日等长周期指标）
_DEFAULT_KLINE_DAYS = 365


class TechnicalAnalysisSkills:
    """技术分析技能 — 基于 TA-Lib 的指标计算、形态识别、筹码分析."""

    @staticmethod
    def _get_kline_df(symbol: str, days: int = _DEFAULT_KLINE_DAYS) -> "pd.DataFrame | None":
        """获取日K线数据并转换列名以适配 ta 模块。"""
        df = get_kline(symbol, "day", days)
        if df is None or len(df) == 0:
            return None
        # mootdx 返回列：open, close, high, low, vol, amount, datetime
        # ta 模块内部处理别名映射
        return df

    def get_technical_indicators(self, symbol: str) -> dict:
        """获取个股的32种技术指标最新值。

        Args:
            symbol: 6位股票代码，如 "600519"。

        Returns:
            {指标名: 值} 字典，包含 MACD/KDJ/RSI/CCI/BOLL 等。
            值均为 float，异常值以 0.0 填充。
        """
        df = self._get_kline_df(symbol)
        if df is None:
            return {}
        return get_latest_indicators(df, calc_threshold=90)

    def get_kline_patterns(self, symbol: str) -> dict:
        """获取个股的61种K线形态识别结果。

        Args:
            symbol: 6位股票代码。

        Returns:
            {形态字段名: 值}，值含义：
            - 正数（100）= 买入信号
            - 0 = 无信号
            - 负数（-100）= 卖出信号
        """
        df = self._get_kline_df(symbol)
        if df is None:
            return {}
        patterns = get_latest_patterns(df, calc_threshold=12)
        # 将 int 转为带中文名的格式
        result = {}
        for key, val in patterns.items():
            result[key] = {"value": val, "direction": "买入" if val > 0 else ("卖出" if val < 0 else "无")}
        return result

    def get_pattern_signals(self, symbol: str) -> dict:
        """获取K线形态的买入/卖出信号列表。

        Returns:
            {"buy": [{field, name_cn, signal, value}], "sell": [...]}
        """
        df = self._get_kline_df(symbol)
        if df is None:
            return {"buy": [], "sell": []}
        return {
            "buy": get_pattern_buy_signals(df),
            "sell": get_pattern_sell_signals(df),
        }

    def get_technical_signals(self, symbol: str) -> dict:
        """基于指标阈值判断个股的买卖信号。

        Returns:
            {"buy": [指标名], "sell": [指标名]}
            示例: {"buy": ["KDJ_K", "RSI_6"], "sell": []}
        """
        indicators = self.get_technical_indicators(symbol)
        if not indicators:
            return {"buy": [], "sell": []}
        return get_technical_signals(indicators)

    def get_chip_distribution(self, symbol: str, days: int = _DEFAULT_KLINE_DAYS) -> dict:
        """计算个股的筹码分布 (CYQ)。

        Args:
            symbol: 6位股票代码。

        Returns:
            {
                "avg_cost": "150.23",       # 平均成本价
                "benefit_part": 0.65,       # 获利盘比例
                "percent_chips": {
                    "90": {"priceRange": ["140.00", "160.00"], "concentration": 0.067},
                    "70": {"priceRange": ["145.00", "155.00"], "concentration": 0.033}
                },
                "price_range": {"min": 140.0, "max": 160.0},
                "trading_days": 210
            }
        """
        df = self._get_kline_df(symbol, days)
        if df is None:
            return {}

        # 获取换手率数据 — mootdx 日K线没有 turnover，需要从 Tencent Finance 获取
        from astock_data.market.tencent_finance import get_valuation
        val_data = get_valuation([symbol])
        if val_data and symbol in val_data:
            turnover_pct = val_data[symbol].get("turnover_pct", 0)
            # 将最近换手率填入最后一行作为近似
            df["turnover"] = 0.0
            if isinstance(turnover_pct, (int, float)):
                df.iloc[-1, df.columns.get_loc("turnover")] = turnover_pct

        result = compute_chip_distribution(df)
        if result is None:
            return {}
        return {
            "avg_cost": result["avg_cost"],
            "benefit_part": result["benefit_part"],
            "percent_chips": result["percent_chips"],
            "price_range": {
                "min": min(result["y"]) if result["y"] else 0,
                "max": max(result["y"]) if result["y"] else 0,
            },
            "trading_days": result["t"],
        }

    def get_full_technical_analysis(self, symbol: str) -> dict:
        """一键获取个股的完整技术分析（指标 + 形态 + 信号 + 筹码）。

        Returns:
            {
                "symbol": "600519",
                "indicators": {...},        # 32种指标最新值
                "indicator_signals": {...},  # 买卖信号
                "patterns": {...},           # K线形态
                "pattern_signals": {...},    # 形态信号列表
                "chip_distribution": {...},  # 筹码分布
            }
        """
        df = self._get_kline_df(symbol)
        if df is None:
            return {"symbol": symbol, "error": "无法获取K线数据"}

        indicators = get_latest_indicators(df, calc_threshold=90)
        indicator_signals = get_technical_signals(indicators)
        patterns = get_latest_patterns(df, calc_threshold=12)
        pattern_signals = {
            "buy": get_pattern_buy_signals(df),
            "sell": get_pattern_sell_signals(df),
        }

        # 简化筹码（不需要完整分布数组，仅摘要）
        cyq = self.get_chip_distribution(symbol)

        return {
            "symbol": symbol,
            "indicators": indicators,
            "indicator_signals": indicator_signals,
            "patterns": patterns,
            "pattern_signals": pattern_signals,
            "chip_distribution": cyq,
        }
