"""Market monitor — real-time intraday market scanning (09:30-15:00)."""

from datetime import datetime

from astock_data.signal.ths_hotspot import get_hot_sectors
from astock_data.signal.northbound import get_northbound_realtime
from astock_data.market.mootdx_quote import get_quotes as _get_quotes
from astock_data.market.mootdx_quote import get_kline as _get_kline


def scan_hotspots() -> list[dict]:
    return get_hot_sectors()


def scan_hotspots_detail() -> list[dict]:
    """Get hot stocks for early signal detection.

    NOTE: ths_hotspot API only returns: 代码, 名称, 题材归因, 市场
    It does NOT include gain% data. Real-time gains are fetched
    separately via Tencent Finance in generate_early_signals().

    Returns raw hot stock list with available fields.
    Empty list if no data available.
    """
    from astock_data.signal.ths_hotspot import get_hot_stocks
    df = get_hot_stocks()
    if df.empty:
        return []
    return df.to_dict(orient="records")


def scan_northbound() -> list[dict]:
    df = get_northbound_realtime()
    if df.empty:
        return []
    return df.to_dict(orient="records")


def get_quotes(symbols: list[str]) -> list[dict]:
    df = _get_quotes(symbols)
    if df.empty:
        return []
    return df.to_dict(orient="records")


def get_kline(symbol: str, period: str = "5m", count: int = 50) -> list[dict]:
    df = _get_kline(symbol, period, count)
    if df.empty:
        return []
    return df.to_dict(orient="records")


def scan_now() -> dict:
    nb = scan_northbound()
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "hotspots": scan_hotspots()[:10],
        "northbound_latest": nb[-1] if nb else {},
    }
