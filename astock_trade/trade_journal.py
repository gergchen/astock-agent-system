"""Trade journal — CRUD for trade records, daily P&L computation."""

import json
import os
from datetime import date, datetime
from pathlib import Path

from .config import get_config


def _journal_path(d: date) -> Path:
    return get_config().trade_journal_dir / f"{d.isoformat()}.json"


def _read_journal(d: date) -> list[dict]:
    p = _journal_path(d)
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _write_journal(d: date, records: list[dict]) -> None:
    p = _journal_path(d)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp, p)


def record_trade(
    symbol: str,
    direction: str,  # "BUY" or "SELL"
    price: float,
    volume: int,
    strategy: str | None = None,
    notes: str | None = None,
    timestamp: datetime | None = None,
) -> dict:
    """Record a trade. Returns the trade record."""
    d = date.today()
    records = _read_journal(d)
    ts = (timestamp or datetime.now()).isoformat(timespec="seconds")
    trade = {
        "symbol": symbol,
        "direction": direction.upper(),
        "price": price,
        "volume": volume,
        "amount": round(price * volume, 2),
        "strategy": strategy,
        "notes": notes,
        "timestamp": ts,
    }
    records.append(trade)
    _write_journal(d, records)
    return trade


def query_trades(
    start_date: date | None = None,
    end_date: date | None = None,
    symbol: str | None = None,
) -> list[dict]:
    """Query trade records in date range, optionally filtered by symbol."""
    if start_date is None:
        start_date = date.today()
    if end_date is None:
        end_date = date.today()

    result = []
    d = start_date
    while d <= end_date:
        records = _read_journal(d)
        for r in records:
            if symbol and r.get("symbol") != symbol:
                continue
            r["_date"] = d.isoformat()
            result.append(r)
        d = date.fromordinal(d.toordinal() + 1)
    return result


def daily_pnl(d: date | None = None) -> dict:
    """Compute realized P&L for a given date.

    Note: accurate P&L requires pairing buys with sells. This simplified
    version computes net cash flow and remaining position value.
    """
    if d is None:
        d = date.today()
    records = _read_journal(d)
    total_buy = sum(r["amount"] for r in records if r["direction"] == "BUY")
    total_sell = sum(r["amount"] for r in records if r["direction"] == "SELL")
    return {
        "date": d.isoformat(),
        "total_buy": round(total_buy, 2),
        "total_sell": round(total_sell, 2),
        "net_cash_flow": round(total_sell - total_buy, 2),
        "trade_count": len(records),
    }


def trade_summary(start_date: date, end_date: date) -> dict:
    """Aggregated summary over a date range."""
    records = query_trades(start_date, end_date)
    buys = [r for r in records if r["direction"] == "BUY"]
    sells = [r for r in records if r["direction"] == "SELL"]
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_trades": len(records),
        "buy_count": len(buys),
        "sell_count": len(sells),
        "total_buy_amount": round(sum(r["amount"] for r in buys), 2),
        "total_sell_amount": round(sum(r["amount"] for r in sells), 2),
        "symbols_traded": sorted({r["symbol"] for r in records}),
    }
