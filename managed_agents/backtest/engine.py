"""DecisionChainBacktester — Agent 决策链回测引擎.

在历史数据上重放完整决策链路，评估每个环节的判断质量。
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from .replayer import HistoricalReplayer
from .report import AttributionReport, ChainStepResult, SignalAttribution

logger = logging.getLogger(__name__)

DEFAULT_POOL = ["600519", "000858", "002230", "300750", "688017",
                "600036", "601318", "000333", "002415", "300124"]


@dataclass
class BacktestConfig:
    """回测配置."""
    target_date: str                          # 目标交易日 YYYY-MM-DD
    stock_pool: list[str] = field(default_factory=lambda: DEFAULT_POOL)
    kline_count: int = 30                      # 加载K线数量
    momentum_threshold: float = 3.0            # 动量阈值（涨幅>N%视为强势）
    forward_days: list[int] = field(default_factory=lambda: [1, 3, 5, 10, 20])
    run_risk_check: bool = True                 # 是否运行风控


class DecisionChainBacktester:
    """回测核心: 重放 → 记录 → 归因."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.replayer = HistoricalReplayer(config.target_date)
        self.report = AttributionReport(target_date=config.target_date)

    def run(self) -> AttributionReport:
        """执行完整回测。"""
        t0 = time.time()
        pool = self.config.stock_pool

        # ── Step 1: 数据加载 ──
        logger.info(f"[回测] 加载 {len(pool)} 只标的 K 线, 日期={self.config.target_date}")
        quotes, klines = self._load_data(pool)

        # ── Step 2: 热点发现 (模拟哨兵 scan) ──
        hotspots = self._derive_hotspots(quotes)
        self.report.set_step("sentinel_scan", ChainStepResult(
            step="sentinel", success=True,
            output=f"TOP3: {', '.join(h['name'] for h in hotspots[:3])}",
            data={"hotspots": hotspots},
        ))

        # ── Step 3: 信号生成 (模拟研究员) ──
        signals = self._generate_signals(quotes, klines, hotspots)
        self.report.set_step("researcher_signals", ChainStepResult(
            step="researcher", success=True,
            output=f"生成 {len(signals)} 个信号",
            data={"signals": signals},
        ))

        # ── Step 4: 风控过滤 (模拟风控官) ──
        if self.config.run_risk_check:
            approved, rejected = self._risk_filter(signals)
            self.report.set_step("risk_officer", ChainStepResult(
                step="risk_officer", success=True,
                output=f"通过 {len(approved)}, 拒绝 {len(rejected)}",
                data={"approved": approved, "rejected": rejected},
            ))
        else:
            approved = signals
            rejected = []

        # ── Step 5: 前向收益验证 ──
        for sig in approved:
            code = sig.get("symbol", "")
            if not code:
                continue
            fwd = self.replayer.get_forward_returns(code, self.config.forward_days)
            self.report.add_attribution(SignalAttribution(
                symbol=code,
                signal=sig,
                forward_returns=fwd,
                verdict=self._verdict(fwd),
            ))

        # ── 汇总 ──
        self.report.elapsed_ms = int((time.time() - t0) * 1000)
        self.report.summarize()
        return self.report

    # ── 内部方法 ──

    def _load_data(self, pool: list[str]) -> tuple[dict[str, dict], dict[str, dict]]:
        quotes = {}
        klines = {}
        for code in pool:
            q = self.replayer._get_single_quote(code)
            if q:
                quotes[code] = q
            k = self.replayer.get_kline(code, count=self.config.kline_count)
            if k.get("kline"):
                klines[code] = k
        return quotes, klines

    def _derive_hotspots(self, quotes: dict[str, dict]) -> list[dict]:
        """从当日涨幅推导热点板块."""
        threshold = self.config.momentum_threshold
        strong = [(code, q["pct_chg"]) for code, q in quotes.items()
                  if q["pct_chg"] > threshold]
        strong.sort(key=lambda x: -x[1])

        sectors = {}
        for code, chg in strong:
            # 用股票代码前缀做简单分组（实际应接入板块分类）
            sector = self._guess_sector(code)
            sectors.setdefault(sector, {"count": 0, "avg_chg": 0, "stocks": []})
            sectors[sector]["count"] += 1
            sectors[sector]["avg_chg"] += chg
            sectors[sector]["stocks"].append(code)

        for s in sectors:
            sectors[s]["avg_chg"] = round(sectors[s]["avg_chg"] / sectors[s]["count"], 2)

        ranked = sorted(sectors.items(), key=lambda x: -x[1]["count"])
        return [{"name": name, "count": data["count"], "avg_chg": data["avg_chg"]}
                for name, data in ranked[:10]]

    @staticmethod
    def _guess_sector(code: str) -> str:
        prefix = code[:3]
        mapping = {
            "600": "白酒消费", "601": "金融地产", "603": "制造业",
            "688": "科创板", "000": "深市主板", "001": "深市主板",
            "002": "中小板", "300": "创业板",
        }
        return mapping.get(prefix, "其他")

    def _generate_signals(self, quotes: dict[str, dict],
                          klines: dict[str, dict],
                          hotspots: list[dict]) -> list[dict]:
        """生成交易信号（模拟研究员逻辑）."""
        signals = []
        threshold = self.config.momentum_threshold

        for code, q in quotes.items():
            pct = q["pct_chg"]
            if pct <= threshold:
                continue

            kl = klines.get(code, {}).get("kline", [])
            ma5 = self._calc_ma(kl, 5)
            ma10 = self._calc_ma(kl, 10)
            close = q["close"]

            # 放量突破
            avg_vol = self._calc_avg_volume(kl)
            is_vol_break = avg_vol > 0 and q["volume"] > avg_vol * 1.5
            is_ma_break = close > ma5 > ma10 if ma5 and ma10 else False

            confidence = 0.5
            reason_parts = [f"涨幅 {pct}%"]
            if is_vol_break:
                confidence += 0.15
                reason_parts.append("放量")
            if is_ma_break:
                confidence += 0.1
                reason_parts.append("均线多头")
            if pct > 7:
                confidence += 0.1
                reason_parts.append("强势突破")
            confidence = min(0.9, round(confidence, 2))

            signals.append({
                "symbol": code,
                "direction": "BUY" if confidence > 0.5 else "HOLD",
                "price": close,
                "pct_chg": pct,
                "reason": " + ".join(reason_parts),
                "confidence": confidence,
                "vol_break": is_vol_break,
                "ma_break": is_ma_break,
            })

        # 按置信度排序
        signals.sort(key=lambda s: -s["confidence"])
        return signals

    def _risk_filter(self, signals: list[dict]) -> tuple[list[dict], list[dict]]:
        """风控过滤."""
        approved = []
        rejected = []
        allocated = set()

        for sig in signals:
            code = sig["symbol"]
            confidence = sig.get("confidence", 0)

            # ST 检查
            if code.startswith("000") and code in {"000001", "000002"}:
                rejected.append({**sig, "reject_reason": "ST名单"})
                continue

            # 同板块已分配
            sector = self._guess_sector(code)
            if sector in allocated:
                rejected.append({**sig, "reject_reason": f"{sector}已配置"})
                continue

            # 置信度下限
            if confidence < 0.55:
                rejected.append({**sig, "reject_reason": f"置信度不足({confidence})"})
                continue

            approved.append(sig)
            allocated.add(sector)

        return approved, rejected

    @staticmethod
    def _calc_ma(kline: list[dict], period: int) -> float | None:
        if len(kline) < period:
            return None
        closes = [k["close"] for k in kline[-period:]]
        return round(sum(closes) / period, 2)

    @staticmethod
    def _calc_avg_volume(kline: list[dict]) -> float:
        if len(kline) < 6:
            return 0
        vols = [k["volume"] for k in kline[-6:-1]]
        return sum(vols) / len(vols)

    @staticmethod
    def _verdict(fwd: dict) -> str:
        ret5 = fwd.get("ret_5d")
        if ret5 is None:
            return "UNKNOWN"
        if ret5 > 5:
            return "STRONG_WIN"
        if ret5 > 0:
            return "WIN"
        if ret5 > -5:
            return "LOSS"
        return "STRONG_LOSS"
