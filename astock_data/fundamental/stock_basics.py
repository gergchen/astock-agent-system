"""Stock basic info via akshare — market cap, shares, industry, listing date."""

import akshare as ak

from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import AKShareError


@retry()
@rate_limit("akshare")
def get_stock_basics(code: str) -> dict:
    """Fetch basic stock info from akshare.

    Args:
        code: 6-digit stock code.

    Returns:
        Dict with: code, name, total_shares, float_shares, total_mcap,
        float_mcap, industry, listing_date. mcap in 元.
    """
    try:
        df = ak.stock_individual_info_em(symbol=str(code).zfill(6))
    except Exception as e:
        raise AKShareError(f"个股基本面 fetch failed for {code}: {e}") from e

    if df is None or df.empty:
        return {}

    result = {}
    for _, row in df.iterrows():
        item = str(row.get("item", ""))
        value = row.get("value", "")
        if "代码" in item:
            result["code"] = str(value)
        elif "简称" in item:
            result["name"] = str(value)
        elif "总股本" in item:
            result["total_shares"] = str(value)
        elif "流通股" in item:
            result["float_shares"] = str(value)
        elif "总市值" in item:
            result["total_mcap"] = str(value)
        elif "流通市值" in item:
            result["float_mcap"] = str(value)
        elif "行业" in item:
            result["industry"] = str(value)
        elif "上市时间" in item:
            result["listing_date"] = str(value)
    return result
