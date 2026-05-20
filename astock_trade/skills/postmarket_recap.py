"""Post-market recap — end-of-day performance review (15:00-16:00)."""

from datetime import date, datetime

from astock_data.signal.ths_hotspot import get_hot_sectors
from astock_data.signal.northbound import get_northbound_realtime
from ..trade_journal import query_trades, trade_summary


def today_hotspots() -> list[dict]:
    return get_hot_sectors()


def today_northbound_final() -> dict:
    df = get_northbound_realtime()
    if df.empty:
        return {}
    items = df.to_dict(orient="records")
    first_hgt = items[0]["hgt_yi"] or 0
    first_sgt = items[0]["sgt_yi"] or 0
    last_hgt = items[-1]["hgt_yi"] or 0
    last_sgt = items[-1]["sgt_yi"] or 0
    return {
        "final_hgt": round(last_hgt - first_hgt, 2),
        "final_sgt": round(last_sgt - first_sgt, 2),
        "cumulative_net": round((last_hgt + last_sgt) - (first_hgt + first_sgt), 2),
    }


def daily_recap(d: date | None = None) -> dict:
    if d is None:
        d = date.today()

    trades = query_trades(d, d)
    summary = trade_summary(d, d)

    buys = [t for t in trades if t["direction"] == "BUY"]
    sells = [t for t in trades if t["direction"] == "SELL"]

    by_symbol = {}
    for t in trades:
        sym = t["symbol"]
        if sym not in by_symbol:
            by_symbol[sym] = {"buys": 0, "sells": 0, "buy_amount": 0, "sell_amount": 0}
        if t["direction"] == "BUY":
            by_symbol[sym]["buys"] += t["volume"]
            by_symbol[sym]["buy_amount"] += t["amount"]
        else:
            by_symbol[sym]["sells"] += t["volume"]
            by_symbol[sym]["sell_amount"] += t["amount"]

    return {
        "date": d.isoformat(),
        "summary": summary,
        "by_symbol": by_symbol,
        "hotspots": today_hotspots()[:10],
        "northbound": today_northbound_final(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
