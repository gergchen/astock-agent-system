"""Backtest engine — replay historical data through signal → risk → execution.

Usage:
    from astock_trade.backtest import BacktestEngine
    from astock_trade.backtest.strategies import ma_crossover

    engine = BacktestEngine(initial_cash=100000)
    result = engine.run(
        symbols=["600519", "000858"],
        strategy=ma_crossover,
        strategy_params={"fast": 5, "slow": 20},
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
    result.report()
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from ..broker.base import OrderSide
from ..broker.mock_broker import MockBroker
from ..skills.risk_assessor import pre_trade_check
from .metrics import BacktestMetrics, calculate_metrics


@dataclass
class BacktestResult:
    """Results from a completed backtest run."""

    symbol: str
    strategy_name: str
    start_date: str
    end_date: str
    initial_cash: float
    metrics: BacktestMetrics
    trades: list[dict] = field(default_factory=list)
    daily_equity: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "strategy": self.strategy_name,
            "period": f"{self.start_date} → {self.end_date}",
            "initial_cash": self.initial_cash,
            "final_value": self.metrics.end_value,
            "total_return_pct": self.metrics.total_return_pct,
            "annual_return_pct": self.metrics.annual_return_pct,
            "sharpe_ratio": self.metrics.sharpe_ratio,
            "max_drawdown_pct": self.metrics.max_drawdown_pct,
            "win_rate_pct": self.metrics.win_rate_pct,
            "total_trades": self.metrics.total_trades,
            "winning_trades": self.metrics.winning_trades,
            "losing_trades": self.metrics.losing_trades,
            "avg_win_pct": self.metrics.avg_win_pct,
            "avg_loss_pct": self.metrics.avg_loss_pct,
            "profit_factor": self.metrics.profit_factor,
        }

    def report(self) -> str:
        """Generate a formatted report."""
        m = self.metrics
        lines = [
            f"{'='*56}",
            f"  回测报告: {self.symbol}  {self.strategy_name}",
            f"  周期: {self.start_date} → {self.end_date}",
            f"{'='*56}",
            f"  初始资金:    {self.initial_cash:>12,.0f}",
            f"  最终净值:    {m.end_value:>12,.0f}",
            f"  ─────────────────────────────────",
            f"  总收益率:    {m.total_return_pct:>+11.2f}%",
            f"  年化收益:    {m.annual_return_pct:>+11.2f}%",
            f"  夏普比率:    {m.sharpe_ratio:>12.2f}",
            f"  最大回撤:    {m.max_drawdown_pct:>11.2f}%",
            f"  ─────────────────────────────────",
            f"  总交易次数:  {m.total_trades:>12}",
            f"  胜率:        {m.win_rate_pct:>11.2f}%",
            f"  盈利/亏损:   {m.winning_trades:>6} / {m.losing_trades:<6}",
            f"  平均盈利:    {m.avg_win_pct:>+11.2f}%",
            f"  平均亏损:    {m.avg_loss_pct:>11.2f}%",
            f"  盈亏比:      {m.profit_factor:>12.2f}",
            f"{'='*56}",
        ]
        return "\n".join(lines)

    def save(self, path: str | Path) -> Path:
        """Save result as JSON."""
        path = Path(path)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path


class BacktestEngine:
    """Replay historical K-line data through strategy → risk → execution."""

    def __init__(
        self,
        initial_cash: float = 100_000,
        commission_pct: float = 0.03,
        slippage_pct: float = 0.01,
        max_position_pct: float = 0.30,
        max_total_exposure: float = 0.70,
        single_trade_pct: float = 0.20,
        data_dir: str | Path = "data/backtest",
    ):
        self.initial_cash = initial_cash
        self.commission_pct = commission_pct
        self.slippage_pct = slippage_pct
        self.max_position_pct = max_position_pct
        self.max_total_exposure = max_total_exposure
        self.single_trade_pct = single_trade_pct
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        symbol: str,
        strategy: Callable,
        strategy_params: dict | None = None,
        start_date: str = "2024-01-01",
        end_date: str = "2024-12-31",
        df: pd.DataFrame | None = None,
    ) -> BacktestResult:
        """Run a backtest for a single symbol.

        Args:
            symbol: Stock code.
            strategy: Callable that takes (df, **params) and returns signal list.
            strategy_params: Extra kwargs for the strategy function.
            start_date / end_date: Date range (ignored if df provided directly).
            df: Pre-loaded DataFrame with columns [date, open, high, low, close, vol].
        """
        strategy_params = strategy_params or {}
        strategy_name = getattr(strategy, "__name__", "custom")

        # Load or use provided data
        if df is not None:
            data = df.copy()
        else:
            data = self._load_data(symbol, start_date, end_date)

        if data.empty:
            raise ValueError(f"No data for {symbol} in {start_date} → {end_date}")

        # Normalize columns
        data = self._normalize_columns(data)
        data = data.sort_values("date").reset_index(drop=True)

        # Generate strategy signals
        signals = strategy(data, **strategy_params)
        if not signals:
            raise ValueError(
                f"Strategy {strategy_name} produced no signals for {symbol}"
            )

        # Run simulation
        return self._simulate(
            symbol=symbol,
            data=data,
            signals=signals,
            strategy_name=strategy_name,
            start_date=str(data["date"].iloc[0])[:10],
            end_date=str(data["date"].iloc[-1])[:10],
        )

    def _load_data(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """Load K-line data from mootdx or local cache."""
        cache_file = self.data_dir / f"{symbol}_{start}_{end}.csv"

        if cache_file.exists():
            df = pd.read_csv(cache_file)
            if not df.empty:
                return df

        # Try mootdx
        try:
            from astock_data.market.mootdx_quote import get_kline

            df = get_kline(symbol, category="day", offset=500)
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "open": "open", "close": "close", "high": "high",
                    "low": "low", "vol": "vol", "amount": "amount",
                })
                if "date" not in df.columns and df.index.name != "date":
                    df = df.reset_index()
                df.to_csv(cache_file, index=False)
                return df
        except Exception:
            pass

        # Try akshare
        try:
            import akshare as ak

            df = ak.stock_zh_a_hist(
                symbol=symbol, period="daily", start_date=start, end_date=end
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "日期": "date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low", "成交量": "vol", "成交额": "amount",
                })
                df.to_csv(cache_file, index=False)
                return df
        except Exception:
            pass

        raise RuntimeError(
            f"无法获取 {symbol} 的历史数据。请检查网络或手动放入 {cache_file}"
        )

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure standard column names: date, open, high, low, close, vol."""
        aliases = {
            "open": ["open", "开盘", "OPEN"],
            "high": ["high", "最高", "HIGH"],
            "low": ["low", "最低", "LOW"],
            "close": ["close", "收盘", "CLOSE"],
            "vol": ["vol", "volume", "成交量", "VOL"],
            "date": ["date", "日期", "datetime", "time", "DATE"],
        }

        rename_map = {}
        for target, sources in aliases.items():
            for s in sources:
                if s in df.columns:
                    rename_map[s] = target
                    break

        if rename_map:
            df = df.rename(columns=rename_map)

        # Ensure date column
        if "date" not in df.columns:
            if df.index.name and df.index.name.lower() in ("date", "日期", "datetime"):
                df = df.reset_index()
            else:
                df = df.reset_index()
                if "index" in df.columns:
                    df = df.rename(columns={"index": "date"})

        return df

    def _simulate(
        self,
        symbol: str,
        data: pd.DataFrame,
        signals: list[dict],
        strategy_name: str,
        start_date: str,
        end_date: str,
    ) -> BacktestResult:
        """Run the day-by-day simulation."""
        broker = MockBroker(initial_cash=self.initial_cash)

        # Index signals by date
        sig_by_date: dict[str, list[dict]] = {}
        for s in signals:
            d = s["date"]
            sig_by_date.setdefault(d, []).append(s)

        trades: list[dict] = []
        daily_equity: list[dict] = []

        # Walk through each trading day
        for _, row in data.iterrows():
            date = str(row["date"])[:10]
            close = float(row["close"])
            broker.update_position_prices({symbol: close})

            # Process signals for this date
            day_signals = sig_by_date.get(date, [])
            for sig in day_signals:
                direction = sig["direction"]
                price = sig["price"]

                # Apply slippage
                if direction == "BUY":
                    exec_price = price * (1 + self.slippage_pct / 100)
                else:
                    exec_price = price * (1 - self.slippage_pct / 100)

                account = broker.get_account()

                if direction == "BUY":
                    # Position sizing — respect both risk limit and cash
                    max_trade_value = account.total_assets * self.single_trade_pct
                    volume = int(max_trade_value / exec_price / 100) * 100
                    max_affordable = int(account.cash / (exec_price * (1 + self.commission_pct / 100)) / 100) * 100
                    volume = max(100, min(volume, max_affordable))
                    if volume < 100:
                        continue

                    # Risk check
                    signal = {
                        "symbol": symbol,
                        "direction": "BUY",
                        "price": exec_price,
                        "volume": volume,
                    }
                    positions = {
                        p.symbol: p.market_value for p in account.positions
                    }
                    total_pos = sum(positions.values())
                    risk_account = {
                        "total_assets": account.total_assets,
                        "positions": positions,
                        "daily_pnl": 0,
                    }
                    decision = pre_trade_check(signal, risk_account)

                    if decision["decision"] != "APPROVED":
                        continue

                    # Apply commission
                    cost = exec_price * volume * (1 + self.commission_pct / 100)
                    order = broker.place_order(
                        symbol=symbol,
                        side=OrderSide.BUY,
                        price=exec_price,
                        volume=volume,
                    )
                    trades.append({
                        "date": date,
                        "symbol": symbol,
                        "direction": "BUY",
                        "price": exec_price,
                        "volume": volume,
                        "cost": round(cost, 2),
                        "reason": sig.get("reason", ""),
                        "pnl": None,
                        "pnl_pct": None,
                    })

                elif direction == "SELL":
                    positions = broker.get_positions()
                    pos = next((p for p in positions if p.symbol == symbol), None)
                    if pos is None:
                        continue
                    volume = pos.volume
                    if volume <= 0:
                        continue

                    # Record P&L before selling
                    buy_trade = next(
                        (t for t in reversed(trades)
                         if t["symbol"] == symbol and t["direction"] == "BUY" and t["pnl"] is None),
                        None,
                    )

                    order = broker.place_order(
                        symbol=symbol,
                        side=OrderSide.SELL,
                        price=exec_price,
                        volume=volume,
                    )
                    revenue = exec_price * volume * (1 - self.commission_pct / 100)

                    if buy_trade:
                        pnl = revenue - buy_trade["cost"]
                        pnl_pct = (pnl / buy_trade["cost"]) * 100
                        buy_trade["pnl"] = round(pnl, 2)
                        buy_trade["pnl_pct"] = round(pnl_pct, 2)

                    trades.append({
                        "date": date,
                        "symbol": symbol,
                        "direction": "SELL",
                        "price": exec_price,
                        "volume": volume,
                        "revenue": round(revenue, 2),
                        "reason": sig.get("reason", ""),
                        "pnl": None,
                        "pnl_pct": None,
                    })

            # End of day: mark to market
            account = broker.get_account()
            daily_equity.append({
                "date": date,
                "total_assets": round(account.total_assets, 2),
                "cash": round(account.cash, 2),
                "position_value": round(
                    sum(p.market_value for p in account.positions), 2
                ),
            })

        # Final equity curve values
        equity_values = [e["total_assets"] for e in daily_equity]

        # Force-sell remaining positions at last price
        final_account = broker.get_account()
        if final_account.positions:
            last_row = data.iloc[-1]
            last_close = float(last_row["close"])
            last_date = str(last_row["date"])[:10]
            for pos in final_account.positions:
                broker.place_order(
                    symbol=pos.symbol,
                    side=OrderSide.SELL,
                    price=last_close,
                    volume=pos.volume,
                )
                trades.append({
                    "date": last_date,
                    "symbol": pos.symbol,
                    "direction": "SELL",
                    "price": last_close,
                    "volume": pos.volume,
                    "reason": "强制平仓(期末)",
                    "pnl": None,
                    "pnl_pct": None,
                })
            final_account = broker.get_account()
            equity_values[-1] = final_account.total_assets
            daily_equity[-1]["total_assets"] = round(final_account.total_assets, 2)

        metrics = calculate_metrics(equity_values, trades)

        return BacktestResult(
            symbol=symbol,
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            initial_cash=self.initial_cash,
            metrics=metrics,
            trades=trades,
            daily_equity=daily_equity,
        )
