"""mootdx F10 latest announcements/dividend summaries."""

from ..fundamental.mootdx_f10 import get_f10
from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import MootdxError


@retry()
@rate_limit("mootdx")
def get_latest_announcements(code: str) -> str:
    """Fetch latest announcement summary from mootdx F10 '最新提示'.

    Args:
        code: 6-digit stock code.

    Returns:
        Text content including recent filings, dividends, shareholder resolutions.
    """
    try:
        return get_f10(str(code).zfill(6), "最新提示")
    except MootdxError:
        raise
    except Exception as e:
        raise MootdxError(f"mootdx announcements failed for {code}: {e}") from e
