"""同花顺热点 — daily strong stocks with editorial sector attribution tags.

Source: zx.10jqka.com.cn/event/api/getharden/
Zero auth, ~73ms response, ~125 stocks on active days.

Key field: 'reason' — editorial reason tags like "算力租赁+Token工厂+AI政务"
"""

from datetime import date as _date, timedelta

import pandas as pd
import requests

from ..config import get_config
from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import THSError


THS_HOT_URL = "http://zx.10jqka.com.cn/event/api/getharden/date/{date}/orderby/date/orderway/desc/charset/GBK/"

RENAME_MAP = {
    "name": "名称",
    "code": "代码",
    "reason": "题材归因",
    "close": "收盘价",
    "zhangdie": "涨跌额",
    "zhangfu": "涨幅%",
    "huanshou": "换手率%",
    "chengjiaoe": "成交额",
    "chengjiaoliang": "成交量",
    "ddejingliang": "大单净量",
    "market": "市场",
}

_MAX_FALLBACK_DAYS = 10


def _try_fetch(date_str: str) -> tuple[pd.DataFrame, str | None]:
    """Try to fetch hot stocks for a given date. Returns (df, error_str)."""
    url = THS_HOT_URL.format(date=date_str)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "Chrome/117.0.0.0 Safari/537.36"
        )
    }
    try:
        r = requests.get(url, headers=headers, timeout=get_config().http_timeout)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as e:
        return pd.DataFrame(), str(e)

    if data.get("errocode", 0) != 0:
        return pd.DataFrame(), data.get("errormsg", "unknown error")

    rows = data.get("data") or []
    if not rows:
        return pd.DataFrame(), None  # None = empty but not an error

    df = pd.DataFrame(rows)
    df = df.rename(columns={k: v for k, v in RENAME_MAP.items() if k in df.columns})
    return df, None


@retry()
@rate_limit("ths")
def get_hot_stocks(date: str | None = None) -> pd.DataFrame:
    """Fetch today's strong stocks with editorial reason tags.

    Falls back to previous days if today returns empty (weekend/holiday).

    Args:
        date: 'YYYY-MM-DD' format string, None = today.

    Returns:
        DataFrame with columns: 代码, 名称, 涨幅%, 题材归因, 换手率%, etc.
    """
    if date is None:
        date = _date.today().strftime("%Y-%m-%d")

    for offset in range(_MAX_FALLBACK_DAYS):
        if date is not None:
            try_date = (_date.fromisoformat(date) - timedelta(days=offset)).strftime("%Y-%m-%d")
        else:
            try_date = (_date.today() - timedelta(days=offset)).strftime("%Y-%m-%d")

        df, err = _try_fetch(try_date)
        if err:
            raise THSError(f"同花顺热点 fetch failed: {err}")
        if not df.empty:
            return df

    return pd.DataFrame()


def get_hot_sectors() -> list[dict]:
    """Extract top trending sectors from today's hot stocks.

    Returns list of {sector: str, count: int} sorted by prevalence.
    """
    from collections import Counter

    df = get_hot_stocks()
    if df.empty or "题材归因" not in df.columns:
        return []

    all_tags = []
    for r in df["题材归因"].dropna():
        tags = [t.strip() for t in str(r).split("+") if t.strip()]
        all_tags.extend(tags)

    cnt = Counter(all_tags)
    return [{"sector": tag, "count": n} for tag, n in cnt.most_common()]
