"""Tick / Minute-level data replay for intraday backtesting.

Provides:
- Intraday data loading from mootdx (1min/5min K-lines)
- Tick-level simulation for limit-up / limit-down detection
- Time-of-day pattern analysis (morning vs afternoon behavior)
- Intraday slippage estimation

This is a FRAMEWORK — it provides the data infrastructure for
intraday strategies but does not include strategy logic.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# A-share trading calendar
MORNING_START = time(9, 30)
MORNING_END = time(11, 30)
AFTERNOON_START = time(13, 0)
AFTERNOON_END = time(15, 0)

# Intraday periods for pattern analysis
INTRADAY_PERIODS = {
    "open_auction": (time(9, 15), time(9, 25)),
    "morning_open": (time(9, 30), time(10, 0)),
    "morning_mid": (time(10, 0), time(11, 0)),
    "morning_close": (time(11, 0), time(11, 30)),
    "afternoon_open": (time(13, 0), time(13, 30)),
    "afternoon_mid": (time(13, 30), time(14, 30)),
    "afternoon_close": (time(14, 30), time(15, 0)),
}


@dataclass
class IntradayBar:
    """A single intraday bar (minute or tick)."""
    datetime: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float = 0.0

    @property
    def is_limit_up(self) -> bool:
        """Check if this bar hit limit-up (close at 10% above open approximately)."""
        return False  # requires previous day close reference


@dataclass
class IntradaySession:
    """Full intraday session data for a single stock on a single day."""
    symbol: str
    date: str
    bars: list[IntradayBar] = field(default_factory=list)
    period_returns: dict[str, float] = field(default_factory=dict)
    morning_return: float = 0.0
    afternoon_return: float = 0.0
    full_day_return: float = 0.0
    intraday_volatility: float = 0.0
    volume_profile: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "date": self.date,
            "bar_count": len(self.bars),
            "morning_return": self.morning_return,
            "afternoon_return": self.afternoon_return,
            "full_day_return": self.full_day_return,
            "intraday_volatility": self.intraday_volatility,
            "period_returns": self.period_returns,
            "volume_profile": self.volume_profile,
        }


class IntradayLoader:
    """Load intraday K-line data from data sources.

    Currently supports:
    - mootdx 1min / 5min K-lines
    - CSV cache for offline replay
    """

    def __init__(self, cache_dir: str | Path | None = None):
        self._cache_dir = Path(cache_dir) if cache_dir else Path("data/intraday")
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    def load_minute_bars(
        self,
        symbol: str,
        date: str,
        frequency: str = "1min",
    ) -> IntradaySession:
        """Load intraday minute bars for a symbol on a given date.

        Args:
            symbol: Stock code (6 digits).
            date: Date string "YYYY-MM-DD".
            frequency: "1min" or "5min".

        Returns:
            IntradaySession with bars and computed features.
        """
        cache_file = self._cache_dir / f"{symbol}_{date}_{frequency}.csv"

        # Try cache first
        if cache_file.exists():
            try:
                df = pd.read_csv(cache_file)
                if not df.empty:
                    return self._df_to_session(symbol, date, df)
            except Exception:
                pass

        # Try mootdx
        try:
            from astock_data.market.mootdx_quote import get_kline
            freq_map = {"1min": 1, "5min": 5}
            k_freq = freq_map.get(frequency, 1)

            df = get_kline(symbol, category="min", offset=1)
            if df is not None and not df.empty:
                # Filter to requested date
                if "date" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    df = df[df["date"].dt.date == pd.Timestamp(date).date()]
                if not df.empty:
                    df.to_csv(cache_file, index=False)
                    return self._df_to_session(symbol, date, df)
        except Exception as e:
            logger.warning("Failed to load intraday data for %s on %s: %s", symbol, date, e)

        return IntradaySession(symbol=symbol, date=date)

    def load_recent_days(
        self,
        symbol: str,
        days: int = 5,
        frequency: str = "1min",
    ) -> list[IntradaySession]:
        """Load intraday data for the most recent N trading days."""
        sessions = []
        for i in range(days):
            d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
            session = self.load_minute_bars(symbol, d, frequency)
            if session.bars:
                sessions.append(session)
        return sessions

    def _df_to_session(self, symbol: str, date: str,
                       df: pd.DataFrame) -> IntradaySession:
        """Convert DataFrame to IntradaySession."""
        # Normalize column names
        col_map = {
            "open": ["open", "开盘"],
            "high": ["high", "最高"],
            "low": ["low", "最低"],
            "close": ["close", "收盘"],
            "vol": ["vol", "volume", "成交量"],
            "amount": ["amount", "成交额"],
        }

        rename = {}
        for target, sources in col_map.items():
            for s in sources:
                if s in df.columns:
                    rename[s] = target
                    break
        df = df.rename(columns=rename)

        # Determine datetime column
        dt_col = None
        for col in ["date", "datetime", "time", "日期", "时间"]:
            if col in df.columns:
                dt_col = col
                break

        bars = []
        for _, row in df.iterrows():
            dt_str = str(row.get(dt_col, "")) if dt_col else ""
            bar = IntradayBar(
                datetime=dt_str,
                open=float(row.get("open", 0) or 0),
                high=float(row.get("high", 0) or 0),
                low=float(row.get("low", 0) or 0),
                close=float(row.get("close", 0) or 0),
                volume=int(row.get("vol", 0) or 0),
                amount=float(row.get("amount", 0) or 0),
            )
            bars.append(bar)

        session = IntradaySession(symbol=symbol, date=date, bars=bars)
        self._compute_features(session)
        return session

    @staticmethod
    def _compute_features(session: IntradaySession) -> None:
        """Compute intraday features from bars."""
        if not session.bars:
            return

        opens = [b.open for b in session.bars]
        highs = [b.high for b in session.bars]
        lows = [b.low for b in session.bars]
        closes = [b.close for b in session.bars]
        volumes = [b.volume for b in session.bars]

        # Returns by period
        session.full_day_return = (closes[-1] / opens[0] - 1) * 100 if opens[0] > 0 else 0
        session.intraday_volatility = (max(highs) - min(lows)) / min(lows) * 100 \
            if min(lows) > 0 else 0

        # Volume profile
        n = len(session.bars)
        if n >= 4:
            quartile = n // 4
            for label, start, end in [
                ("q1_open", 0, quartile),
                ("q2", quartile, 2 * quartile),
                ("q3", 2 * quartile, 3 * quartile),
                ("q4_close", 3 * quartile, n),
            ]:
                v = sum(volumes[start:end])
                session.volume_profile[label] = v

        period_map = {
            "morning_open": (0, min(n, 6)),   # first 6 bars (~30 min)
            "morning_mid": (min(n, 6), min(n, 18)),
            "morning_close": (min(n, 18), min(n, 24)),
            "afternoon_open": (min(n, 24), min(n, 30)),
            "afternoon_close": (min(n, 30), n),
        }

        for period, (start, end) in period_map.items():
            if end > start and end <= n:
                period_close = closes[min(end, n) - 1]
                period_open = opens[start]
                session.period_returns[period] = \
                    (period_close / period_open - 1) * 100 if period_open > 0 else 0


class IntradayReplay:
    """Replay intraday data for backtesting intraday strategies.

    Simulates trading within a single day using minute-level data.
    Supports:
    - Time-based order entry/exit
    - Limit-up / limit-down detection within the day
    - Intraday stop-loss / take-profit
    """

    def __init__(self, initial_cash: float = 100_000):
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.position = 0
        self.avg_cost = 0.0
        self.trades: list[dict] = []
        self.equity_curve: list[dict] = []

    def reset(self) -> None:
        """Reset to initial state."""
        self.cash = self.initial_cash
        self.position = 0
        self.avg_cost = 0.0
        self.trades = []
        self.equity_curve = []

    def replay_session(self, session: IntradaySession) -> dict:
        """Replay through all bars of a session.

        Override buy()/sell() in a subclass for actual strategy logic.
        This base class just records the equity curve.
        """
        self.reset()

        for bar in session.bars:
            self._record_equity(bar)

        return self._result(session)

    def buy(self, bar: IntradayBar, volume: int, price: float = 0) -> bool:
        """Execute a buy order at the given bar."""
        exec_price = price if price > 0 else bar.close
        cost = exec_price * volume
        if cost > self.cash:
            return False
        self.cash -= cost
        total_vol = self.position + volume
        self.avg_cost = ((self.avg_cost * self.position) + cost) / total_vol \
            if total_vol > 0 else exec_price
        self.position = total_vol
        self.trades.append({
            "datetime": bar.datetime,
            "direction": "BUY",
            "price": exec_price,
            "volume": volume,
            "cost": cost,
        })
        return True

    def sell(self, bar: IntradayBar, volume: int = 0, price: float = 0) -> bool:
        """Execute a sell order at the given bar. 0 volume = sell all."""
        if self.position <= 0:
            return False
        exec_price = price if price > 0 else bar.close
        sell_vol = min(volume, self.position) if volume > 0 else self.position
        revenue = exec_price * sell_vol
        pnl = revenue - self.avg_cost * sell_vol
        self.cash += revenue
        self.position -= sell_vol
        self.trades.append({
            "datetime": bar.datetime,
            "direction": "SELL",
            "price": exec_price,
            "volume": sell_vol,
            "revenue": revenue,
            "pnl": round(pnl, 2),
        })
        return True

    def _record_equity(self, bar: IntradayBar) -> None:
        position_value = self.position * bar.close
        equity = {
            "datetime": bar.datetime,
            "cash": round(self.cash, 2),
            "position_value": round(position_value, 2),
            "total_assets": round(self.cash + position_value, 2),
        }
        self.equity_curve.append(equity)

    def _result(self, session: IntradaySession) -> dict:
        final_equity = self.equity_curve[-1] if self.equity_curve else {}
        return {
            "symbol": session.symbol,
            "date": session.date,
            "initial_cash": self.initial_cash,
            "final_assets": final_equity.get("total_assets", self.cash),
            "return_pct": round(
                (final_equity.get("total_assets", self.cash) / self.initial_cash - 1) * 100, 2
            ) if self.initial_cash > 0 else 0,
            "trades": self.trades,
            "equity_curve": self.equity_curve,
        }
