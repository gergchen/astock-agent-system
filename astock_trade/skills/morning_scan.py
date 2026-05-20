"""Morning scan — pre-market briefing data collection (09:00-09:25)."""

from datetime import date

from astock_data.signal.ths_hotspot import get_hot_sectors, get_hot_stocks
from astock_data.signal.northbound import get_northbound_realtime
from astock_data.news.cls_news import get_flash_news as _get_flash_news


def yesterday_hotspots() -> list[dict]:
    return get_hot_sectors()


def latest_flash_news(n: int = 20) -> list[dict]:
    items = _get_flash_news()
    return items[:n] if items else []


def northbound_summary() -> dict:
    """Get yesterday's northbound flow summary.

    hgt_yi/sgt_yi are cumulative (累计净买入). Session total = last - first.
    """
    df = get_northbound_realtime()
    if df.empty:
        return {"latest_hgt": 0, "latest_sgt": 0, "session_total": 0}

    items = df.to_dict(orient="records")
    first_hgt = items[0].get("hgt_yi", 0) or 0
    first_sgt = items[0].get("sgt_yi", 0) or 0
    last_hgt = items[-1].get("hgt_yi", 0) or 0
    last_sgt = items[-1].get("sgt_yi", 0) or 0

    return {
        "latest_hgt": round(last_hgt - first_hgt, 2),
        "latest_sgt": round(last_sgt - first_sgt, 2),
        "session_total": round((last_hgt + last_sgt) - (first_hgt + first_sgt), 2),
    }


def premarket_scan() -> dict:
    return {
        "date": date.today().isoformat(),
        "hotspots": yesterday_hotspots()[:10],
        "news": latest_flash_news(10),
        "northbound": northbound_summary(),
    }
