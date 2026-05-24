"""Tencent Finance HTTP API — PE, PB, market cap, turnover, price limits.

HTTP GET, GBK encoding, ~-delimited 88 fields. No API key, no IP ban.

Field index (calibrated 2026-05):
  1=name, 3=price, 4=last_close, 5=open,
  31=change_amt, 32=change_pct, 33=high, 34=low,
  37=amount(wan), 38=turnover_pct,
  39=PE(TTM), 43=amplitude%(NOT PB!), 44=mcap(yi),
  45=float_mcap(yi), 46=PB, 47=limit_up, 48=limit_down,
  49=vol_ratio, 52=PE(static)
"""

import logging
import urllib.request

from ..config import get_config
from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import TencentFinanceError


# 指数代码 → 腾讯前缀映射（get_market_prefix 默认规则对指数无效）
INDEX_PREFIX_MAP: dict[str, str] = {
    "000001": "sh",  # 上证指数
    "000688": "sh",  # 科创50
    "000300": "sh",  # 沪深300
    "000016": "sh",  # 上证50
    "000905": "sh",  # 中证500
    "399001": "sz",  # 深证成指
    "399006": "sz",  # 创业板指
}


def get_market_prefix(code: str) -> str:
    """6-digit code -> Tencent market prefix (sh/sz/bj)."""
    code = str(code).zfill(6)
    if code in INDEX_PREFIX_MAP:
        return INDEX_PREFIX_MAP[code]
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith("8"):
        return "bj"
    return "sz"


@retry()
@rate_limit("tencent")
def _fetch_raw(codes: list[str]) -> str:
    """Raw HTTP GET from Tencent Finance."""
    prefixed = [f"{get_market_prefix(c)}{c}" for c in codes]
    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", get_config().http_user_agent)
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.read().decode("gbk")
    except Exception as e:
        raise TencentFinanceError(f"Tencent Finance fetch failed: {e}") from e


def _validate_field_positive(vals: list[str], idx: int, name: str, code: str) -> float:
    """Parse and validate a numeric field must be positive."""
    raw = vals[idx] if idx < len(vals) else ""
    try:
        val = float(raw)
    except (ValueError, TypeError):
        val = 0.0
    if val <= 0:
        raise TencentFinanceError(f"{code}: {name}={raw} (invalid)")
    return val


def _parse_response(raw: str) -> dict[str, dict]:
    """Parse Tencent semicolon-delimited ~-separated response.

    Validates critical fields are present and internally consistent.
    Raises TencentFinanceError for individual stocks with bad data.
    """
    result = {}
    for line in raw.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        try:
            # Validate critical price fields (must be positive)
            price = _validate_field_positive(vals, 3, "price", code)
            last_close = _validate_field_positive(vals, 4, "last_close", code)
            open_ = float(vals[5]) if vals[5] else 0
            high = _validate_field_positive(vals, 33, "high", code)
            low = float(vals[34]) if vals[34] else 0

            # Range sanity: high >= low, high >= price >= low
            if low <= 0 or high < low:
                raise TencentFinanceError(f"{code}: high={high} < low={low} (inverted)")
            if price > high * 1.1 or price < low * 0.9:
                raise TencentFinanceError(f"{code}: price={price} outside [{low}, {high}]")

            result[code] = {
                "name": vals[1],
                "price": price,
                "last_close": last_close,
                "open": open_,
                "change_amt": float(vals[31]) if vals[31] else 0,
                "change_pct": float(vals[32]) if vals[32] else 0,
                "high": high,
                "low": low,
                "amount_wan": float(vals[37]) if vals[37] else 0,
                "turnover_pct": float(vals[38]) if vals[38] else 0,
                "pe_ttm": float(vals[39]) if vals[39] else 0,
                "amplitude_pct": float(vals[43]) if vals[43] else 0,
                "mcap_yi": float(vals[44]) if vals[44] else 0,
                "float_mcap_yi": float(vals[45]) if vals[45] else 0,
                "pb": float(vals[46]) if vals[46] else 0,
                "limit_up": float(vals[47]) if vals[47] else 0,
                "limit_down": float(vals[48]) if vals[48] else 0,
                "vol_ratio": float(vals[49]) if vals[49] else 0,
                "pe_static": float(vals[52]) if vals[52] else 0,
            }
        except (ValueError, IndexError, TencentFinanceError) as e:
            logger = logging.getLogger(__name__)
            logger.warning("Skipping %s: %s", code, e)
            continue
    return result


def get_valuation(codes: list[str] | str) -> dict[str, dict]:
    """Fetch PE, PB, market cap, turnover, price limits for one or more stocks.

    Args:
        codes: Single code string or list of 6-digit code strings.

    Returns:
        Dict mapping code -> valuation dict.
    """
    if isinstance(codes, str):
        codes = [codes]
    codes = [str(c).zfill(6) for c in codes]
    raw = _fetch_raw(codes)
    result = _parse_response(raw)
    if not result:
        raise TencentFinanceError(f"No valuation data for {codes}")
    return result
