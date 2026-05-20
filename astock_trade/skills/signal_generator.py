"""Signal generator — produce trading signals from market data.

Consumes hotspot, northbound, K-line data and generates structured
trade signals for the risk officer to evaluate.
"""

import json
from datetime import datetime
from pathlib import Path

from ..config import get_config


def generate_signals(
    hotspots: list[dict],
    northbound: list[dict],
    watchlist: list[str] | None = None,
) -> list[dict]:
    """Generate trading signals from market data.

    Returns a list of signal dicts, each with:
    - symbol, direction, price (estimated), reason, confidence
    """
    signals = []

    # Top sectors with high stock count indicate strong momentum
    strong_sectors = {h["sector"]: h["count"] for h in hotspots if h["count"] >= 3}

    # Northbound trend: compare last 5 min vs 30 min ago
    nb_trend = _northbound_trend(northbound)

    for h in hotspots[:15]:
        sector = h["sector"]
        count = h["count"]
        confidence = min(0.9, 0.4 + count * 0.05)

        signal = {
            "type": "sector_momentum",
            "sector": sector,
            "direction": "BUY" if confidence > 0.5 else "HOLD",
            "reason": f"{sector}板块强势，{count}只涨停/大涨股票",
            "confidence": round(confidence, 2),
            "northbound_trend": nb_trend,
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        signals.append(signal)

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
