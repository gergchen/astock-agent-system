"""mootdx F10 — 9 categories of text-based company data.

Categories include: company overview, shareholder research, financial analysis, etc.
"""

from mootdx.quotes import Quotes

from ..config import get_config
from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import MootdxError


F10_CATEGORIES = [
    "最新提示",
    "公司概况",
    "财务分析",
    "股东研究",
    "股本结构",
    "资本运作",
    "业内点评",
    "行业分析",
    "公司大事",
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
def get_f10(code: str, category: str = "公司概况") -> str:
    """Fetch F10 text data for a given category.

    Args:
        code: 6-digit stock code.
        category: One of F10_CATEGORIES.

    Returns:
        Text content of the F10 category.
    """
    if category not in F10_CATEGORIES:
        raise MootdxError(
            f"Unknown F10 category: {category}. Valid: {F10_CATEGORIES}"
        )

    try:
        client = _get_client()
        text = client.F10(symbol=str(code).zfill(6), name=category)
        return text or ""
    except Exception as e:
        global _client
        _client = None
        raise MootdxError(
            f"mootdx F10 failed for {code} category={category}: {e}"
        ) from e
