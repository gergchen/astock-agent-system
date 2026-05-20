"""mootdx client — K-line, real-time quotes, order book, tick data.

Connect to TDX servers via TCP port 7709. No API key needed.
"""

import pandas as pd
from mootdx.quotes import Quotes

from ..config import get_config
from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import MootdxError

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


def get_kline(code: str, category: str | int = "day", offset: int = 100) -> pd.DataFrame:
    """Fetch K-line data. category: 'day','week','month','1m','5m','15m','30m','60m' or int 4-11."""
    if isinstance(category, str):
        cat_int = CATEGORY_FROM_NAME.get(category, 4)
    else:
        cat_int = category
    return _get_client().bars(symbol=str(code).zfill(6), category=cat_int, offset=offset)


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
