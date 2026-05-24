"""mootdx client — K-line, real-time quotes, order book, tick data.

Connect to TDX servers via TCP port 7709. No API key needed.
"""

import logging

import pandas as pd
from mootdx.quotes import Quotes

from ..config import get_config
from ..core.cache import cached
from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import DataUnavailableError, MootdxError
from ..core.datasource_manager import DataSourceManager

# Category mapping: mootdx category code -> human label
CATEGORY_MAP = {
    4: "day",
    5: "week",
    6: "month",
    7: "1m",
    8: "5m",
    9: "15m",
    10: "30m",
    11: "60m",
}

CATEGORY_FROM_NAME = {v: k for k, v in CATEGORY_MAP.items()}


def _parse_tdx_market(code: str) -> int:
    """6-digit code -> mootdx market (0=Shenzhen, 1=Shanghai)."""
    code = str(code).zfill(6)
    if code.startswith(("6", "9")):
        return 1
    return 0


class MootdxClient:
    """Singleton mootdx TCP client with auto-reconnect.

    Requires direct TCP access to TDX servers on port 7709.
    Gracefully degrades if unreachable.
    """

    def __init__(self):
        self._client: Quotes | None = None
        self._available: bool | None = None  # None = unchecked
        config = get_config()
        self._servers = config.tdx_servers

    @property
    def available(self) -> bool:
        """Check if mootdx is actually usable."""
        if self._available is None:
            try:
                self._find_best_server(timeout=5)
                self._available = True
            except Exception:
                self._available = False
        return self._available

    @property
    def client(self) -> Quotes:
        if self._client is None:
            best = self._find_best_server()
            self._client = Quotes.factory(market="std", server=best, timeout=10)
        return self._client

    def _find_best_server(self, timeout: int = 3) -> tuple[str, int]:
        """Try servers in order and return the first responsive one.

        No longer does a full protocol test — just TCP connectivity check
        since the protocol handshake can hang on certain networks.

        Raises MootdxError if no server is reachable.
        """
        import socket
        for srv in self._servers:
            ip, port = srv["ip"], srv["port"]
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(timeout)
                result = sock.connect_ex((ip, port))
                sock.close()
                if result == 0:
                    return (ip, port)
            except Exception:
                continue
        raise MootdxError(
            "All TDX servers unreachable. Check network/firewall/proxy settings. "
            "Use 'astock market valuation CODE' (Tencent Finance) as fallback "
            "for PE/PB/market cap data."
        )

    def reset(self):
        """Force reconnect on next call."""
        self._client = None

    @retry()
    @rate_limit("mootdx")
    def bars(self, symbol: str, category: int, offset: int = 100) -> pd.DataFrame:
        """Fetch K-line data.

        Args:
            symbol: 6-digit stock code.
            category: 4=day, 5=week, 6=month, 7=1m, 8=5m, 9=15m, 10=30m, 11=60m.
            offset: Number of bars to fetch (default 100).

        Returns:
            DataFrame with columns: open, close, high, low, vol, amount, datetime.
        """
        try:
            market = _parse_tdx_market(symbol)
            df = self.client.bars(symbol=symbol, category=category, offset=offset)
            if df is None or df.empty:
                raise MootdxError(f"No K-line data for {symbol} category={category}")
            return df
        except MootdxError:
            raise
        except Exception as e:
            self.reset()
            raise MootdxError(f"mootdx bars failed for {symbol}: {e}") from e

    @retry()
    @rate_limit("mootdx")
    def quotes(self, symbols: list[str]) -> pd.DataFrame:
        """Fetch real-time quotes for one or more symbols (46 fields).

        Fields include: price, open, high, low, last_close, bid1-5, ask1-5,
        bid_vol1-5, ask_vol1-5, vol, amount, servertime.
        """
        try:
            df = self.client.quotes(symbol=symbols)
            if df is None or df.empty:
                raise MootdxError(f"No quote data for {symbols}")
            return df
        except MootdxError:
            raise
        except Exception as e:
            self.reset()
            raise MootdxError(f"mootdx quotes failed for {symbols}: {e}") from e

    @retry()
    @rate_limit("mootdx")
    def transaction(self, symbol: str, date: str) -> pd.DataFrame:
        """Fetch tick-by-tick transaction data for a given date.

        Returns: time, price, vol, num, buyorsell (0=buy, 1=sell, 2=neutral).
        """
        try:
            df = self.client.transaction(symbol=symbol, date=date)
            if df is None:
                return pd.DataFrame()
            return df
        except Exception as e:
            self.reset()
            raise MootdxError(f"mootdx transaction failed for {symbol} on {date}: {e}") from e


# Module-level singleton
_client: MootdxClient | None = None


def _get_client() -> MootdxClient:
    global _client
    if _client is None:
        _client = MootdxClient()
    return _client


def _get_sina_kline(code: str, category: str = "day", offset: int = 100) -> pd.DataFrame | None:
    """Fallback: fetch K-line via Sina finance (akshare stock_zh_a_daily).

    Sina returns data with turnover, works without proxy/VPN.
    Returns None on failure.
    """
    try:
        import akshare as ak

        prefix = "sh" if str(code).startswith("6") else "sz"
        df = ak.stock_zh_a_daily(symbol=f"{prefix}{code}")
        if df is None or df.empty:
            return None

        df = df.rename(columns={
            "volume": "vol",
        })
        # Sina returns newest first, reverse to oldest-first (mootdx convention)
        df = df.sort_values("date").reset_index(drop=True)

        # Apply offset: return last N rows
        if offset and len(df) > offset:
            df = df.tail(offset).reset_index(drop=True)
        return df
    except Exception:
        import logging
        logging.getLogger(__name__).debug("Sina K-line fallback failed", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# DataSourceManager: mootdx TCP → Sina HTTP automatic fallback
# ---------------------------------------------------------------------------
_kline_manager: DataSourceManager | None = None


def _init_kline_manager() -> DataSourceManager:
    """Register K-line sources in priority order."""
    mgr = DataSourceManager()

    def _mootdx_source(code: str, category: str | int = "day", offset: int = 100) -> pd.DataFrame:
        """Primary: mootdx TCP (supports all periods)."""
        if isinstance(category, str):
            cat_int = CATEGORY_FROM_NAME.get(category, 4)
        else:
            cat_int = category
        df = _get_client().bars(symbol=str(code).zfill(6), category=cat_int, offset=offset)
        if df is None or df.empty:
            raise MootdxError(f"No K-line data from mootdx for {code}")
        return df

    def _sina_source(code: str, category: str | int = "day", offset: int = 100) -> pd.DataFrame:
        """Fallback: Sina HTTP (only day and 15m)."""
        if isinstance(category, str):
            cat_name = category
        else:
            cat_name = CATEGORY_MAP.get(category, "day")
        if cat_name not in ("day", "15m"):
            raise MootdxError(f"Sina fallback does not support category '{cat_name}'")
        result = _get_sina_kline(code, cat_name, offset)
        if result is None or result.empty:
            raise MootdxError(f"No K-line data from Sina for {code}")
        return result

    mgr.register("mootdx", _mootdx_source, priority=0)
    mgr.register("sina", _sina_source, priority=1)
    return mgr


def _get_kline_manager() -> DataSourceManager:
    global _kline_manager
    if _kline_manager is None:
        _kline_manager = _init_kline_manager()
    return _kline_manager


@cached(ttl_key="kline_daily")
def get_kline(code: str, category: str | int = "day", offset: int = 100) -> pd.DataFrame:
    """Fetch K-line data. category: 'day','week','month','1m','5m','15m','30m','60m' or int 4-11.

    Auto-fallback: mootdx TCP → Sina HTTP. Cached per kline_daily TTL.
    """
    try:
        return _get_kline_manager().fetch(
            code,
            category=category,
            offset=offset,
            required_columns=["open", "high", "low", "close", "vol"],
            positive_columns=["open", "high", "low", "close", "vol"],
            cross_validate=True,
        )
    except DataUnavailableError:
        return pd.DataFrame()


def batch_kline(
    codes: list[str],
    category: str = "day",
    offset: int = 100,
    max_workers: int = 5,
) -> dict[str, pd.DataFrame]:
    """Fetch K-line for multiple stocks in parallel.

    Each stock goes through the normal get_kline() path (mootdx → Sina
    fallback) independently. ThreadPoolExecutor is used since the bottleneck
    is network I/O, not CPU.

    Caching applies per-stock — repeated calls with the same codes within
    TTL window return instantly from cache.

    Args:
        codes: List of 6-digit stock codes.
        category: K-line period (default "day").
        offset: Number of bars per stock (default 100).
        max_workers: Max concurrent fetches (default 5).

    Returns:
        Dict mapping code -> DataFrame (empty/failed codes omitted).
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    logger = logging.getLogger(__name__)
    codes = [str(c).zfill(6) for c in codes]
    results: dict[str, pd.DataFrame] = {}

    logger.info("Fetching K-line for %d stocks (parallel=%d)...", len(codes), max_workers)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(get_kline, code, category, offset): code
            for code in codes
        }
        for future in as_completed(futures):
            code = futures[future]
            try:
                df = future.result()
                if df is not None and not df.empty:
                    results[code] = df
                else:
                    logger.warning("No data for %s", code)
            except Exception as e:
                logger.error("Failed to fetch %s: %s", code, e)

    logger.info("Fetched %d/%d stocks successfully", len(results), len(codes))
    return results


def get_quotes(codes: list[str]) -> pd.DataFrame:
    """Fetch real-time quotes for a list of stock codes."""
    codes = [str(c).zfill(6) for c in codes]
    return _get_client().quotes(symbols=codes)


def get_transactions(code: str, date: str) -> pd.DataFrame:
    """Fetch tick data for a stock on a specific date (YYYYMMDD)."""
    return _get_client().transaction(symbol=str(code).zfill(6), date=date)


def get_order_book(code: str) -> dict:
    """Fetch real-time quote with 5-level order book for a single stock.

    Returns a dict with buy/sell levels.
    """
    df = get_quotes([code])
    if df.empty:
        raise MootdxError(f"No order book data for {code}")
    row = df.iloc[0]
    return {
        "code": str(code).zfill(6),
        "price": float(row.get("price", 0) or 0),
        "open": float(row.get("open", 0) or 0),
        "high": float(row.get("high", 0) or 0),
        "low": float(row.get("low", 0) or 0),
        "last_close": float(row.get("last_close", 0) or 0),
        "vol": float(row.get("vol", 0) or 0),
        "amount": float(row.get("amount", 0) or 0),
        "bid1": float(row.get("bid1", 0) or 0),
        "bid2": float(row.get("bid2", 0) or 0),
        "bid3": float(row.get("bid3", 0) or 0),
        "bid4": float(row.get("bid4", 0) or 0),
        "bid5": float(row.get("bid5", 0) or 0),
        "ask1": float(row.get("ask1", 0) or 0),
        "ask2": float(row.get("ask2", 0) or 0),
        "ask3": float(row.get("ask3", 0) or 0),
        "ask4": float(row.get("ask4", 0) or 0),
        "ask5": float(row.get("ask5", 0) or 0),
    }
