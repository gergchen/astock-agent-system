"""巨潮 cninfo announcements via akshare — all SSE/SZSE/BSE filings."""

import akshare as ak

from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import AKShareError


def get_cninfo_market(code: str) -> str:
    """6-digit code -> cninfo market string.

    akshare uses "沪深京" for all A-shares combined.
    """
    return "沪深京"


@retry()
@rate_limit("akshare")
def get_announcements(code: str) -> list[dict]:
    """Fetch full announcement list from 巨潮.

    Args:
        code: 6-digit stock code.

    Returns:
        List of dicts with: title, type, date, url.
    """
    try:
        df = ak.stock_zh_a_disclosure_report_cninfo(
            symbol=str(code).zfill(6),
            market="沪深京",
        )
    except Exception as e:
        raise AKShareError(f"巨潮公告 fetch failed for {code}: {e}") from e

    if df is None or df.empty:
        return []

    df = df.rename(columns={
        "公告标题": "title",
        "公告类型": "type",
        "公告日期": "date",
        "公告链接": "url",
    })
    return df.to_dict(orient="records")
