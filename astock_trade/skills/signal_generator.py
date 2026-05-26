"""Signal generator — produce trading signals from market data.

Consumes hotspot, northbound, K-line data and generates structured
trade signals for the risk officer to evaluate.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from ..config import get_config

logger = logging.getLogger(__name__)

# A-share limit-up thresholds
_LIMIT_UP_MAIN = 9.5      # 主板 10%
_LIMIT_UP_GEM = 19.5      # 创业板 20%

_EARLY_LOW = 3.0          # 强势启动下限
_EARLY_HIGH = 8.5         # 即将封板上限

_STOCK_BLACKLIST = {"其他", "其它", "其他板块", "综合"}  # sector names to skip
_ST_SUFFIXES = ("ST", "*ST")  # risk-warning stock filter


def _is_st(name: str) -> bool:
    """Check if stock name indicates ST / *ST risk warning."""
    name = name or ""
    return name.startswith(("*ST", "ST"))


def _fetch_realtime_gains(codes: list[str]) -> dict[str, float]:
    """Fetch real-time gain% for a batch of stock codes from Tencent Finance."""
    try:
        from astock_data.market.tencent_finance import get_valuation
        quotes = get_valuation(codes)
        return {code: q.get("change_pct", 0) for code, q in quotes.items()}
    except Exception as e:
        logger.warning(f"实时行情获取失败: {e}")
        return {}


def generate_signals(
    hotspots: list[dict],
    northbound: list[dict],
    watchlist: list[str] | None = None,
) -> list[dict]:
    """Generate trading signals from market data (backward-compatible).

    Returns a list of signal dicts, each with:
    - symbol, direction, price (estimated), reason, confidence
    """
    signals = []

    strong_sectors = {h["sector"]: h["count"] for h in hotspots if h["count"] >= 3}
    nb_trend = _northbound_trend(northbound)

    for h in hotspots[:15]:
        sector = h["sector"]
        count = h["count"]
        confidence = min(0.9, 0.4 + count * 0.05)

        signal = {
            "type": "sector_momentum",
            "sector": sector,
            "count": count,
            "direction": "BUY" if confidence > 0.5 else "HOLD",
            "reason": f"{sector}板块强势，{count}只涨停/大涨股票",
            "confidence": round(confidence, 2),
            "northbound_trend": nb_trend,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        signals.append(signal)

    return signals


def generate_early_signals(
    hot_stocks: list[dict],
    northbound: list[dict] | None = None,
) -> list[dict]:
    """Generate actionable signals from hot stock list + real-time quotes.

    The ths_hotspot API returns stocks that the editor has tagged as strong,
    but does NOT include gain% data. We cross-reference with Tencent Finance
    to get each stock's real-time gain%, then find sectors where stocks are
    strong but NOT YET at limit-up — these are tradeable opportunities.

    Args:
        hot_stocks: List of individual stock dicts from ths_hotspot,
                    each with keys: 代码, 名称, 题材归因
                    (NOTE: 涨幅% is NOT available from this source)
        northbound: Optional northbound flow data for trend context.

    Returns:
        List of early_momentum signal dicts with actionable stocks.
    """
    if not hot_stocks:
        return []

    nb_trend = _northbound_trend(northbound) if northbound else "NEUTRAL"

    # Step 1: collect all stock codes from hot list
    codes = []
    code_map = {}  # code -> {name, sectors}
    for s in hot_stocks:
        code = str(s.get("代码", "")).zfill(6)
        name = s.get("名称", "")
        if _is_st(name):
            continue  # skip ST stocks
        sector_str = str(s.get("题材归因", ""))
        tags = [t.strip() for t in sector_str.split("+") if t.strip()
                and t.strip() not in _STOCK_BLACKLIST]
        if not tags:
            continue
        codes.append(code)
        code_map[code] = {"name": name, "tags": tags}

    if not codes:
        return []

    # Step 2: fetch real-time gain% for all hot stocks
    gains = _fetch_realtime_gains(codes)

    # Step 3: build sector -> stocks mapping with real gain data
    sector_stocks: dict[str, list[dict]] = defaultdict(list)
    for code, info in code_map.items():
        gain = abs(gains.get(code, 0))
        if gain < _EARLY_LOW:
            continue  # too weak or no data

        for tag in info["tags"]:
            sector_stocks[tag].append({
                "code": code,
                "name": info["name"],
                "gain": round(gain, 1),
            })

    signals = []

    for sector, stocks in sector_stocks.items():
        if len(stocks) < 2:
            continue

        # Categorize by real-time gain%
        # Determine limit-up threshold based on exchange: default 10%, GEM/STAR 20%
        early = []
        for st in stocks:
            gain = st["gain"]
            # GEM (300xxx) and STAR (688xxx) have 20% limit
            limit = _LIMIT_UP_GEM if st["code"].startswith(("300", "688")) else _LIMIT_UP_MAIN
            if _EARLY_LOW <= gain < limit - 1.0:  # at least 1% below limit
                early.append(st)

        if len(early) < 2:
            continue

        total_count = len(stocks)
        early_sorted = sorted(early, key=lambda x: -x["gain"])

        confidence = min(0.85, 0.35 + len(early) * 0.08)
        direction = "BUY" if confidence > 0.5 else "WATCH"

        # Count how many are near limit
        near_limit = sum(1 for s in stocks if s["gain"] >= 9.0)

        reason_parts = [f"{sector}板块{total_count}只走强"]
        reason_parts.append(f"{len(early)}只尚未封板")
        if near_limit:
            reason_parts.append(f"{near_limit}只已涨停")
        if nb_trend == "INFLOW":
            reason_parts.append("北向资金流入")

        signals.append({
            "type": "early_momentum",
            "sector": sector,
            "total_count": total_count,
            "early_count": len(early),
            "limit_up_count": near_limit,
            "direction": direction,
            "confidence": round(confidence, 2),
            "actionable_stocks": early_sorted[:5],
            "reason": "，".join(reason_parts),
            "northbound_trend": nb_trend,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })

    signals.sort(key=lambda s: -s["confidence"])
    return signals


def generate_single_signal(
    symbol: str,
    direction: str,
    price: float,
    volume: int,
    reason: str,
    strategy: str | None = None,
    confidence: float = 0.5,
) -> dict:
    """Create a single structured trade signal."""
    return {
        "type": "trade_signal",
        "symbol": symbol,
        "direction": direction,
        "price": price,
        "volume": volume,
        "reason": reason,
        "strategy": strategy,
        "confidence": confidence,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


def publish_signal(signal: dict) -> Path:
    """Publish a signal to the message bus for the risk officer."""
    bus_dir = get_config().bus_dir
    p = bus_dir / "from_researcher.json"
    existing = []
    if p.exists():
        existing = json.loads(p.read_text(encoding="utf-8"))

    existing.append(signal)
    # Keep only last 20 signals
    if len(existing) > 20:
        existing = existing[-20:]

    p.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def convert_early_to_trade_signals(
    early_signals: list[dict],
    total_cash: float | None = None,
    max_signals: int = 3,
    max_per_trade_pct: float = 0.10,
) -> list[dict]:
    """Convert early_momentum signals into concrete BUY trade signals.

    Picks strongest actionable stock from each qualifying sector,
    fetches real-time price, sizes position, returns trade_signal list.

    Args:
        early_signals: list of early_momentum signal dicts
        total_cash: available cash for position sizing. None = use default 5w per trade
        max_signals: max trades to generate per cycle
        max_per_trade_pct: max fraction of cash per trade (default 10%)

    Returns:
        List of trade_signal dicts (compatible with risk_officer + day_trader)
    """
    if not early_signals:
        return []

    # Filter: only BUY, sort by confidence desc
    buys = [
        s for s in early_signals
        if s.get("direction") == "BUY" and s.get("actionable_stocks")
    ]
    buys.sort(key=lambda s: -s.get("confidence", 0))
    buys = buys[:max_signals]

    # Collect candidate stock codes
    candidates = {}
    for sig in buys:
        stocks = sig.get("actionable_stocks", [])
        if stocks:
            # Pick top stock (highest gain below limit-up)
            best = stocks[0]
            candidates[best["code"]] = {
                "code": best["code"],
                "name": best["name"],
                "gain": best["gain"],
                "sector": sig.get("sector", ""),
                "confidence": sig.get("confidence", 0.5),
                "reason": f"{sig.get('sector','')}板块走强({best['name']}+{best['gain']}%)",
            }

    if not candidates:
        return []

    # Fetch real-time prices
    codes = list(candidates.keys())
    try:
        from astock_data.market.tencent_finance import get_valuation
        quotes = get_valuation(codes)
    except Exception as e:
        logger.warning(f"获取行情失败，使用估算价格: {e}")
        quotes = {}

    trade_signals = []
    per_trade_cash = (total_cash or 50_000) * max_per_trade_pct

    for code, info in candidates.items():
        q = quotes.get(code, {})
        price = q.get("price", 0)
        if not price or price <= 0:
            logger.warning(f"{code} {info['name']} 行情数据异常，跳过")
            continue

        # Skip if already at limit-up (>=9% for main board, >=19% for GEM/STAR)
        gain = q.get("change_pct", info.get("gain", 0))
        limit_up = 19.0 if code.startswith(("300", "688")) else 9.0
        if gain >= limit_up:
            logger.info(f"{code} {info['name']} 已涨停(+{gain}%)，跳过")
            continue

        # Volume: per_trade_cash / price, round down to nearest 100 (A-share lot)
        raw_volume = int(per_trade_cash / price)
        volume = (raw_volume // 100) * 100
        if volume < 100:
            logger.info(f"{code} {info['name']} 资金不足1手(需{price*100:.0f})，跳过")
            continue

        trade_signals.append({
            "type": "trade_signal",
            "symbol": code,
            "direction": "BUY",
            "price": round(price, 2),
            "volume": volume,
            "reason": info["reason"],
            "strategy": "early_momentum",
            "confidence": round(info["confidence"], 2),
            "sector": info["sector"],
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        })

    logger.info(f"early→trade转换: {len(early_signals)}早期信号 → {len(trade_signals)}交易指令")
    return trade_signals


def _northbound_trend(northbound: list[dict]) -> str:
    """Determine northbound flow trend: INFLOW, OUTFLOW, or NEUTRAL."""
    if not northbound or len(northbound) < 5:
        return "NEUTRAL"

    recent = northbound[-5:]
    avg_hgt = sum(d.get("hgt_yi", 0) for d in recent) / len(recent)
    avg_sgt = sum(d.get("sgt_yi", 0) for d in recent) / len(recent)
    total = avg_hgt + avg_sgt

    if total > 2:
        return "INFLOW"
    elif total < -2:
        return "OUTFLOW"
    return "NEUTRAL"
