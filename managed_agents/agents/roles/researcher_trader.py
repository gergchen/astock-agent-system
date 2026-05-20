"""量化研究员 — 盘前扫描、盘中监控、交易信号生成."""

import json
import logging

from ..base import BaseAgent

logger = logging.getLogger(__name__)

RESEARCHER_PROMPT = """你是A股量化研究员，负责市场扫描和信号发现。你不执行交易，只向风控官和交易员提供分析结果。

## 核心职责
1. 盘前扫描 (09:00-09:25)：隔夜消息、外围市场、板块轮动
2. 盘中监控 (09:30-15:00)：热点板块、北向资金、异动个股
3. 信号生成：基于技术指标+资金流向+题材热度

## 信号格式
```json
{
  "type": "trade_signal",
  "symbol": "600519",
  "direction": "BUY",
  "price": 1850.00,
  "volume": 100,
  "reason": "放量突破前高+北向持续流入+板块异动",
  "strategy": "breakout_v1",
  "confidence": 0.75
}
```

## 与风控官协作
- 信号发到消息总线 from_researcher channel
- 等待风控官审批后，由交易员执行
- 不要直接发交易指令给交易员

## 注意事项
- 信号必须有明确的置信度和理由
- 同一标的30分钟内不重复发信号
- 开盘前30分钟和收盘前15分钟减少信号密度
"""


class ResearcherTrader(BaseAgent):
    """量化研究员 Agent."""

    def __init__(self):
        from astock_trade.skills.market_monitor import scan_now, scan_hotspots, scan_northbound, get_quotes
        from astock_trade.skills.signal_generator import generate_signals, generate_single_signal, publish_signal
        from astock_trade.skills.morning_scan import premarket_scan

        self._scan_now = scan_now
        self._scan_hotspots = scan_hotspots
        self._scan_northbound = scan_northbound
        self._get_quotes = get_quotes
        self._generate_signals = generate_signals
        self._generate_single_signal = generate_single_signal
        self._publish_signal = publish_signal
        self._premarket_scan = premarket_scan

        super().__init__(name="researcher-trader", role="量化研究员")

    def system_prompt(self) -> str:
        return RESEARCHER_PROMPT

    def _register_skills(self):
        self._skills.update({
            "scan_now": lambda: self._scan_now(),
            "scan_hotspots": lambda: self._scan_hotspots(),
            "scan_northbound": lambda: self._scan_northbound(),
            "get_quotes": lambda symbols: self._get_quotes(symbols),
            "generate_signals": lambda h, n: self._generate_signals(h, n),
            "generate_single_signal": lambda **kw: self._generate_single_signal(**kw),
            "publish_signal": lambda s: str(self._publish_signal(s)),
            "premarket_scan": lambda: self._premarket_scan(),
        })

    def scan_and_generate(self, symbols: list[str] | None = None) -> dict:
        """执行一次完整的扫描+信号生成.

        Returns:
            {"signals": [...], "scan": {...}}
        """
        try:
            scan = self._scan_now()
            hotspots = scan.get("hotspots", [])
            northbound_raw = self._scan_northbound()

            signals = self._generate_signals(hotspots, northbound_raw)
        except Exception as e:
            logger.error(f"扫描信号失败: {e}")
            return {"error": str(e), "signals": []}

        for sig in signals:
            try:
                self._publish_signal(sig)
            except Exception as e:
                logger.error(f"发布信号失败: {e}")

        return {
            "signals": signals,
            "scan": scan,
            "signal_count": len(signals),
        }
