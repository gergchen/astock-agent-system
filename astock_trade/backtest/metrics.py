"""Performance metrics for backtest results."""

import math
from dataclasses import dataclass


@dataclass
class BacktestMetrics:
    total_return_pct: float
    annual_return_pct: float
    sharpe_ratio: float
    max_drawdown_pct: float
    win_rate_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float
    start_value: float
    end_value: float
    benchmarks: dict | None = None


def calculate_metrics(
    daily_values: list[float],
    trades: list[dict],
    trading_days: int = 252,
    risk_free_rate: float = 0.02,
) -> BacktestMetrics:
    """Calculate performance metrics from daily equity curve and trade list."""
    if not daily_values or len(daily_values) < 2:
        return BacktestMetrics(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)

    start_val = daily_values[0]
    end_val = daily_values[-1]

    total_return = (end_val / start_val - 1) * 100 if start_val > 0 else 0

    # Annualized return
    years = len(daily_values) / trading_days
    annual_return = 0.0
    if years > 0 and start_val > 0:
        annual_return = ((end_val / start_val) ** (1 / years) - 1) * 100

    # Daily returns
    daily_returns = []
    for i in range(1, len(daily_values)):
        if daily_values[i - 1] > 0:
            daily_returns.append(
                (daily_values[i] - daily_values[i - 1]) / daily_values[i - 1]
            )

    # Sharpe ratio
    if daily_returns:
        avg_daily = sum(daily_returns) / len(daily_returns)
        std_daily = math.sqrt(
            sum((r - avg_daily) ** 2 for r in daily_returns) / len(daily_returns)
        )
        if std_daily > 0:
            sharpe = (avg_daily * trading_days - risk_free_rate) / (
                std_daily * math.sqrt(trading_days)
            )
        else:
            sharpe = 0.0
    else:
        sharpe = 0.0

    # Max drawdown
    peak = daily_values[0]
    max_dd = 0.0
    for v in daily_values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    # Trade stats
    closed_trades = [t for t in trades if t.get("pnl") is not None]
    if not closed_trades:
        return BacktestMetrics(
            total_return_pct=round(total_return, 2),
            annual_return_pct=round(annual_return, 2),
            sharpe_ratio=round(sharpe, 2),
            max_drawdown_pct=round(max_dd, 2),
            win_rate_pct=0,
            total_trades=0,
            winning_trades=0,
            losing_trades=0,
            avg_win_pct=0,
            avg_loss_pct=0,
            profit_factor=0,
            start_value=round(start_val, 2),
            end_value=round(end_val, 2),
        )

    wins = [t for t in closed_trades if t["pnl"] > 0]
    losses = [t for t in closed_trades if t["pnl"] <= 0]
    total_trades = len(closed_trades)
    win_rate = len(wins) / total_trades * 100 if total_trades > 0 else 0

    avg_win = sum(t["pnl_pct"] for t in wins) / len(wins) if wins else 0
    avg_loss = abs(sum(t["pnl_pct"] for t in losses) / len(losses)) if losses else 0

    total_wins = sum(t["pnl"] for t in wins) if wins else 0
    total_losses = abs(sum(t["pnl"] for t in losses)) if losses else 0
    profit_factor = total_wins / total_losses if total_losses > 0 else float("inf")

    return BacktestMetrics(
        total_return_pct=round(total_return, 2),
        annual_return_pct=round(annual_return, 2),
        sharpe_ratio=round(sharpe, 2),
        max_drawdown_pct=round(max_dd, 2),
        win_rate_pct=round(win_rate, 2),
        total_trades=total_trades,
        winning_trades=len(wins),
        losing_trades=len(losses),
        avg_win_pct=round(avg_win, 2),
        avg_loss_pct=round(avg_loss, 2),
        profit_factor=round(profit_factor, 2),
        start_value=round(start_val, 2),
        end_value=round(end_val, 2),
    )
