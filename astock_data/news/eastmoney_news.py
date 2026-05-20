"""Eastmoney news via akshare — individual stock news + global finance."""

import pandas as pd
import requests
import akshare as ak

from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import AKShareError


def _fetch_stock_news_direct(code: str) -> list[dict]:
    """Directly fetch stock news from Eastmoney API, bypassing akshare's broken regex."""
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "sr": -1, "page_size": 50, "page_index": 1,
        "ann_type": "A", "client_source": "web",
        "stock_list": code,
    }
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json().get("data", {})
    items = data.get("list", [])
    return [
        {
            "title": i.get("title", ""),
            "content": i.get("content", "").replace("　", ""),
            "datetime": i.get("notice_date", ""),
            "source": i.get("src", ""),
            "url": i.get("url", ""),
        }
        for i in items
    ]


@retry()
@rate_limit("akshare")
def get_stock_news(code: str) -> list[dict]:
    """Fetch individual stock news from Eastmoney.

    Args:
        code: 6-digit stock code.

    Returns:
        List of dicts with: title, content, datetime, source, url.
    """
    try:
        return _fetch_stock_news_direct(str(code).zfill(6))
    except Exception as e:
        raise AKShareError(f"个股新闻 fetch failed for {code}: {e}") from e


@retry()
@rate_limit("akshare")
def get_global_news() -> list[dict]:
    """Fetch global financial news from Eastmoney.

    Returns:
        List of dicts with: title, summary, datetime, url.
    """
    try:
        df = ak.stock_info_global_em()
    except Exception as e:
        raise AKShareError(f"全球资讯 fetch failed: {e}") from e

    if df is None or df.empty:
        return []

    return df.to_dict(orient="records")
