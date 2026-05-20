"""Risk assessor — pre-trade risk validation.

Checks trading signals against risk rules before approving execution.
"""

import json
from datetime import date, datetime
from pathlib import Path

from ..config import get_config


# ── Risk Rules ──────────────────────────────────────────────────

def check_position_limit(symbol: str, volume: int, price: float,
                         total_assets: float, current_positions: dict) -> dict:
    """Check single-stock position ≤ 20% total assets."""
    position_value = current_positions.get(symbol, 0) + volume * price
    pct = position_value / total_assets if total_assets > 0 else 1.0
    return {
        "rule": "single_stock_position",
        "passed": pct <= 0.20,
        "detail": f"持仓占比 {pct:.1%} / 限制 20%",
        "current_pct": round(pct, 4),
    }


def check_total_exposure(total_position_value: float, total_assets: float) -> dict:
    """Check total position ≤ 70% total assets."""
    pct = total_position_value / total_assets if total_assets > 0 else 1.0
    return {
        "rule": "total_exposure",
        "passed": pct <= 0.70,
        "detail": f"总仓位 {pct:.1%} / 限制 70%",
        "current_pct": round(pct, 4),
    }


def check_daily_drawdown(daily_pnl: float, total_assets: float) -> dict:
    """Check daily drawdown ≤ 5%."""
    drawdown_pct = abs(daily_pnl) / total_assets if daily_pnl < 0 and total_assets > 0 else 0
    return {
        "rule": "daily_drawdown",
        "passed": drawdown_pct <= 0.05,
        "detail": f"日内回撤 {drawdown_pct:.2%} / 限制 5%",
        "current_pct": round(drawdown_pct, 4),
    }


def check_consecutive_loss(recent_trades: list[dict], max_strikes: int = 3) -> dict:
    """Check if there are N consecutive losing trades."""
    strikes = 0
    for t in reversed(recent_trades):
        if t.get("pnl", 0) < 0:
            strikes += 1
        else:
            break
    return {
        "rule": "consecutive_loss",
        "passed": strikes < max_strikes,
        "detail": f"连续亏损 {strikes} 笔 / 限制 {max_strikes}",
        "strikes": strikes,
    }


def check_st_ban(symbol: str) -> dict:
    """Ban ST/*ST stocks."""
    is_st = "ST" in symbol.upper() or "*ST" in symbol.upper()
    return {
        "rule": "st_ban",
        "passed": not is_st,
        "detail": "ST股票禁止交易" if is_st else "正常标的",
    }


# ── Full Assessment ─────────────────────────────────────────────

def pre_trade_check(signal: dict, account: dict) -> dict:
    """Run all pre-trade risk checks on a signal.

    account expects: {total_assets, cash, positions: {symbol: market_value}, daily_pnl}
    signal expects: {symbol, direction, price, volume}
    """
    total_assets = account.get("total_assets", 0)
    positions = account.get("positions", {})
    daily_pnl = account.get("daily_pnl", 0)

    # Estimate new position value
    new_value = signal["price"] * signal["volume"]
    if signal["direction"] == "SELL":
        new_value = -new_value
    projected_positions = dict(positions)
    projected_positions[signal["symbol"]] = projected_positions.get(signal["symbol"], 0) + new_value

    total_position = sum(v for v in projected_positions.values() if v > 0)

    checks = [
        check_st_ban(signal["symbol"]),
        check_position_limit(signal["symbol"], signal["volume"], signal["price"],
                             total_assets, positions),
        check_total_exposure(total_position, total_assets),
        check_daily_drawdown(daily_pnl, total_assets),
    ]

    all_passed = all(c["passed"] for c in checks)
    return {
        "type": "risk_decision",
        "signal": signal,
        "decision": "APPROVED" if all_passed else "REJECTED",
        "checks": {c["rule"]: c["passed"] for c in checks},
        "check_details": checks,
        "reason": "所有风控检查通过" if all_passed else
                  "; ".join(c["detail"] for c in checks if not c["passed"]),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


def publish_decision(decision: dict) -> Path:
    """Publish risk decision to the message bus for the trader."""
    bus_dir = get_config().bus_dir
    p = bus_dir / "from_risk_officer.json"
    # Append to existing (could contain multiple pending decisions)
    existing = []
    if p.exists():
        existing = json.loads(p.read_text(encoding="utf-8"))
    existing.append(decision)
    if len(existing) > 20:
        existing = existing[-20:]
    p.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
