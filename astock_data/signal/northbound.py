"""同花顺 Northbound capital flow — hsgtApi realtime + historical.

Source: data.hexin.cn/market/hsgtApi/
Zero auth. Realtime: 262 data points per day (09:10-15:00).
Historical: daily since 2024-07-08, ~663KB per type.
"""

import pandas as pd
import requests

from ..config import get_config
from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import THSError


HSGT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "Chrome/117.0.0.0 Safari/537.36"
    ),
    "Host": "data.hexin.cn",
    "Referer": "https://data.hexin.cn/",
}

HSGT_REALTIME_URL = "https://data.hexin.cn/market/hsgtApi/method/dayChart/"
HSGT_HISTORY_URL = (
    'https://data.hexin.cn/market/hsgtApi/method/hsgtData/'
    '?filter=(MUTUAL_TYPE="{type}")'
)


@retry()
@rate_limit("ths")
def get_northbound_realtime() -> pd.DataFrame:
    """Fetch today's minute-level northbound capital flow.

    Returns DataFrame with columns: time, hgt_yi (沪股通累计净买入_亿),
    sgt_yi (深股通累计净买入_亿).

    Units: 亿元. Includes pre-market auction from 09:10.
    """
    try:
        r = requests.get(
            HSGT_REALTIME_URL,
            headers=HSGT_HEADERS,
            timeout=get_config().http_timeout,
        )
        r.raise_for_status()
        d = r.json()
    except requests.RequestException as e:
        raise THSError(f"北向资金实时 fetch failed: {e}") from e

    times = d.get("time", [])
    hgt = d.get("hgt", [])
    sgt = d.get("sgt", [])

    n = len(times)
    return pd.DataFrame({
        "time": times,
        "hgt_yi": hgt[:n] + [None] * (n - len(hgt)),
        "sgt_yi": sgt[:n] + [None] * (n - len(sgt)),
    })


@retry()
@rate_limit("ths")
def get_northbound_history(mutual_type: str = "001") -> dict:
    """Fetch daily historical northbound flow.

    Args:
        mutual_type: "001" = 沪股通, "003" = 深股通.

    Returns:
        Raw dict with 'chart' key containing time + amount arrays.
    """
    try:
        r = requests.get(
            HSGT_HISTORY_URL.format(type=mutual_type),
            headers=HSGT_HEADERS,
            timeout=get_config().http_timeout + 5,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise THSError(f"北向资金历史 fetch failed: {e}") from e
