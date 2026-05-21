"""Backtest engine — replay historical data through signal → risk → execution.

All calculations are deterministic: same input data + same parameters = same results.
No LLM dependency, no random components, no external API calls during simulation.

Usage:
    from astock_trade.backtest import BacktestEngine
    from astock_trade.backtest.strategies import ma_crossover

    engine = BacktestEngine(initial_cash=100000)
    result = engine.run(
        symbol="600519",
        strategy=ma_crossover,
        strategy_params={"fast": 5, "slow": 20},
        start_date="2024-01-01",
        end_date="2024-12-31",
    )
    result.report()
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from ..broker.base import OrderSide, OrderStatus
from ..broker.mock_broker import MockBroker
from .benchmark import (
    BenchmarkMetrics,
    compare_to_benchmark,
    load_benchmark_data,
)
from .metrics import BacktestMetrics, calculate_metrics
from .models import (
    AShareCommission,
    CommissionModel,
    FixedCommission,
    FixedSlippage,
    SlippageModel,
    TickSlippage,
    get_commission_model,
    get_slippage_model,
)


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
        d = {
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
        for bm_name, bm in self.metrics.benchmarks.items():
            d[f"bm_{bm_name}_return"] = bm.benchmark_return_pct
            d[f"bm_{bm_name}_excess"] = bm.excess_return_pct
            d[f"bm_{bm_name}_alpha"] = bm.alpha
            d[f"bm_{bm_name}_beta"] = bm.beta
            d[f"bm_{bm_name}_ir"] = bm.information_ratio
        return d

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
        ]

        # Benchmark section
        for bm_name, bm in m.benchmarks.items():
            lines.extend([
                f"  ── {bm_name} 基准对比 ──",
                f"  基准收益:    {bm.benchmark_return_pct:>+11.2f}%",
                f"  超额收益:    {bm.excess_return_pct:>+11.2f}%",
                f"  Alpha(年化): {bm.alpha:>+11.2f}%",
                f"  Beta:         {bm.beta:>12.3f}",
                f"  信息比率:    {bm.information_ratio:>12.2f}",
                f"  跟踪误差:    {bm.tracking_error_pct:>11.2f}%",
                f"  上行捕获:    {bm.capture_up_pct:>11.1f}%",
                f"  下行捕获:    {bm.capture_down_pct:>11.1f}%",
            ])

        lines.append(f"{'='*56}")
        return "\n".join(lines)

    def save(self, path: str | Path) -> Path:
        """Save result as JSON."""
        path = Path(path)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path


class BacktestEngine:
    """Replay historical K-line data through strategy → risk → execution.

    All calculations are deterministic. Uses configurable slippage and commission
    models that match A-share market reality.
    """

    def __init__(
        self,
        initial_cash: float = 100_000,
        # New model-based parameters (preferred)
        slippage_model: SlippageModel | None = None,
        commission_model: CommissionModel | None = None,
        # Legacy percentage parameters (for backward compatibility)
        commission_pct: float | None = None,
        slippage_pct: float | None = None,
        # Risk limits
        max_position_pct: float = 0.30,
        max_total_exposure: float = 0.70,
        single_trade_pct: float = 0.20,
        data_dir: str | Path = "data/backtest",
        # Benchmark
        benchmark: str | list[str] | None = None,
    ):
        self.initial_cash = initial_cash
        self.max_position_pct = max_position_pct
        self.max_total_exposure = max_total_exposure
        self.single_trade_pct = single_trade_pct  # 单笔占比上限, 高股价时按最小一手处理
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Slippage model: prefer explicit model, fall back to legacy pct
        if slippage_model is not None:
            self.slippage_model = slippage_model
        elif slippage_pct is not None:
            bps = slippage_pct * 100  # convert pct to bps
            self.slippage_model = FixedSlippage(bps=bps)
        else:
            self.slippage_model = TickSlippage(tick_size=0.01, ticks=1)

        # Commission model: prefer explicit model, fall back to legacy pct
        if commission_model is not None:
            self.commission_model = commission_model
        elif commission_pct is not None:
            self.commission_model = FixedCommission(pct=commission_pct)
        else:
            self.commission_model = AShareCommission()

        # Benchmark codes
        if benchmark is None:
            self.benchmark_codes = []
        elif isinstance(benchmark, str):
            self.benchmark_codes = [benchmark]
        else:
            self.benchmark_codes = list(benchmark)

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

    @staticmethod
    def _clamp_price(price: float, ref_price: float, limit_pct: float = 0.10) -> float:
        """Clamp execution price within daily limit-up / limit-down bounds."""
        lower = round(ref_price * (1 - limit_pct), 2)
        upper = round(ref_price * (1 + limit_pct), 2)
        return max(lower, min(price, upper))

    @staticmethod
    def _is_suspension(row: pd.Series) -> bool:
        """Detect trading suspension: flat OHLC + zero volume."""
        vol = float(row.get("vol", 0) or 0)
        if vol > 0:
            return False
        o = float(row.get("open", 0) or 0)
        h = float(row.get("high", 0) or 0)
        l_val = float(row.get("low", 0) or 0)
        c = float(row.get("close", 0) or 0)
        return o == h == l_val == c and o > 0

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
            vol_today = float(row.get("vol", 0))

            # Skip suspension days (flat OHLC + zero volume)
            if self._is_suspension(row):
                continue

            broker.set_current_date(date)
            broker.update_position_prices({symbol: close})

            # Process signals for this date
            day_signals = sig_by_date.get(date, [])
            for sig in day_signals:
                direction = sig["direction"]
                price = sig["price"]

                # Apply slippage model
                slip_result = self.slippage_model.apply(
                    price=price,
                    direction=direction,
                    volume=int(sig.get("volume", 0) or 0),
                    daily_vol=vol_today,
                )
                exec_price = slip_result.exec_price

                # Clamp to daily limit-up / limit-down bounds
                exec_price = self._clamp_price(exec_price, close)

                account = broker.get_account()

                if direction == "BUY":
                    # Commission preview for sizing
                    comm_result = self.commission_model.calculate(
                        exec_price, 100, "BUY"
                    )
                    comm_rate = comm_result.total_cost / comm_result.trade_value if comm_result.trade_value > 0 else 0

                    # Position sizing
                    one_lot_cost = int(exec_price * 100 * (1 + comm_rate))
                    max_affordable = int(account.cash / one_lot_cost) * 100

                    # Single-trade percentage cap
                    max_trade_value = account.total_assets * self.single_trade_pct
                    volume_by_pct = int(max_trade_value / exec_price / 100) * 100

                    # Use percentage cap if it allows at least 1 lot,
                    # otherwise allow 1 lot if cash can afford it
                    if volume_by_pct >= 100:
                        volume = min(volume_by_pct, max_affordable)
                    elif max_affordable >= 100:
                        volume = min(100, max_affordable)
                    else:
                        volume = 0

                    if volume < 100:
                        continue

                    # Optional risk check — skipped by default in backtest
                    # (engine already applies its own position sizing above)

                    # Calculate exact commission
                    comm_result = self.commission_model.calculate(
                        exec_price, volume, "BUY"
                    )
                    cost = exec_price * volume + comm_result.total_cost

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
                        "commission": round(comm_result.total_cost, 2),
                        "slippage_bps": round(slip_result.slippage_pct * 100, 1),
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

                    # Calculate commission (A-share: stamp duty on sell)
                    comm_result = self.commission_model.calculate(
                        exec_price, volume, "SELL"
                    )

                    # Record P&L before selling
                    buy_trades = [
                        t for t in reversed(trades)
                        if t["symbol"] == symbol and t["direction"] == "BUY" and t["pnl"] is None
                    ]
                    buy_trade = buy_trades[0] if buy_trades else None

                    order = broker.place_order(
                        symbol=symbol,
                        side=OrderSide.SELL,
                        price=exec_price,
                        volume=volume,
                    )
                    # Skip if T+1 rejected (same-day sell)
                    if order.status == OrderStatus.REJECTED:
                        continue
                    revenue = exec_price * volume - comm_result.total_cost

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
                        "commission": round(comm_result.total_cost, 2),
                        "slippage_bps": round(slip_result.slippage_pct * 100, 1),
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
        equity_dates = [e["date"] for e in daily_equity]

        # Force-sell remaining positions at last price
        final_account = broker.get_account()
        if final_account.positions:
            last_row = data.iloc[-1]
            last_close = float(last_row["close"])
            last_date = str(last_row["date"])[:10]
            for pos in final_account.positions:
                comm_result = self.commission_model.calculate(
                    last_close, pos.volume, "SELL"
                )
                revenue = last_close * pos.volume - comm_result.total_cost

                broker.place_order(
                    symbol=pos.symbol,
                    side=OrderSide.SELL,
                    price=last_close,
                    volume=pos.volume,
                )

                # Find matching buy trade and record PnL
                buy_trades = [
                    t for t in reversed(trades)
                    if t["symbol"] == pos.symbol and t["direction"] == "BUY" and t["pnl"] is None
                ]
                if buy_trades:
                    buy_trade = buy_trades[0]
                    pnl = revenue - buy_trade["cost"]
                    pnl_pct = (pnl / buy_trade["cost"]) * 100
                    buy_trade["pnl"] = round(pnl, 2)
                    buy_trade["pnl_pct"] = round(pnl_pct, 2)

                trades.append({
                    "date": last_date,
                    "symbol": pos.symbol,
                    "direction": "SELL",
                    "price": last_close,
                    "volume": pos.volume,
                    "revenue": round(revenue, 2),
                    "commission": round(comm_result.total_cost, 2),
                    "reason": "强制平仓(期末)",
                    "pnl": None,
                    "pnl_pct": None,
                })
            final_account = broker.get_account()
            equity_values[-1] = final_account.total_assets
            daily_equity[-1]["total_assets"] = round(final_account.total_assets, 2)

        metrics = calculate_metrics(equity_values, trades)

        # Benchmark comparison
        for bm_code in self.benchmark_codes:
            bm_name = {"000300": "CSI300", "000905": "CSI500"}.get(bm_code, bm_code)
            try:
                bm_df = load_benchmark_data(
                    code=bm_code,
                    start_date=start_date,
                    end_date=end_date,
                    data_dir=self.data_dir,
                    initial_value=self.initial_cash,
                )
                bm_metrics = compare_to_benchmark(
                    strategy_values=equity_values,
                    strategy_dates=equity_dates,
                    benchmark_name=bm_name,
                    benchmark_df=bm_df if not bm_df.empty else None,
                )
                metrics.benchmarks[bm_name] = bm_metrics
            except Exception:
                pass

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

    def compare(
        self,
        symbol: str,
        strategies: list[tuple[str, Callable, dict]],
        start_date: str = "2024-01-01",
        end_date: str = "2024-12-31",
        df: pd.DataFrame | None = None,
    ) -> list[BacktestResult]:
        """Compare multiple strategies on the same stock. Returns all results."""
        results = []
        for name, fn, params in strategies:
            try:
                r = self.run(
                    symbol=symbol,
                    strategy=fn,
                    strategy_params=params,
                    start_date=start_date,
                    end_date=end_date,
                    df=df,
                )
                results.append(r)
            except Exception:
                pass
        return results
