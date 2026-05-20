"""mootdx finance snapshot — 37-field quarterly report data.

TCP protocol via mootdx.quotes.Quotes.finance().
"""

import pandas as pd
from mootdx.quotes import Quotes

from ..config import get_config
from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import MootdxError


FINANCE_FIELDS = [
    "liutongguben",  # 流通股本
    "zongguben",     # 总股本
    "eps",           # 每股收益
    "bvps",          # 每股净资产
    "roe",           # 净资产收益率%
    "profit",        # 净利润
    "income",        # 主营收入
]


_client: Quotes | None = None


def _get_client() -> Quotes:
    global _client
    if _client is None:
        config = get_config()
        srv = config.tdx_servers[0]
        _client = Quotes.factory(
            market="std",
            server=(srv["ip"], srv["port"]),
        )
    return _client


@retry()
@rate_limit("mootdx")
def get_finance(code: str) -> dict:
    """Fetch quarterly financial snapshot (37 fields).

    Args:
        code: 6-digit stock code.

    Returns:
        Dict with all available financial fields.
    """
    try:
        client = _get_client()
        result = client.finance(symbol=str(code).zfill(6))
        if result is None:
            return {}
        if isinstance(result, pd.DataFrame):
            return result.to_dict(orient="records")[0] if not result.empty else {}
        return result
    except Exception as e:
        global _client
        _client = None
        raise MootdxError(f"mootdx finance failed for {code}: {e}") from e
