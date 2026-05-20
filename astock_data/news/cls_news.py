"""财联社 flash news — minute-level "telegram" news via akshare.

Source: akshare.stock_info_global_cls()
The fastest news source among all A-stock data providers.
"""

import akshare as ak

from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import CLSError


@retry()
@rate_limit("akshare")
def get_flash_news() -> list[dict]:
    """Fetch 财联社 flash (telegram) news — minute-level updates.

    Returns:
        List of dicts with: title, content, datetime.
    """
    try:
        df = ak.stock_info_global_cls()
    except Exception as e:
        raise CLSError(f"财联社快讯 fetch failed: {e}") from e

    if df is None or df.empty:
        return []

    df = df.rename(columns={
        "标题": "title",
        "内容": "content",
        "发布时间": "datetime",
    })
    return df.to_dict(orient="records")
