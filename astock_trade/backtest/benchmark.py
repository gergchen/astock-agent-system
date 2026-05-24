"""Benchmark comparison — CSI 300 and CSI 500 index data loading and relative metrics.

No LLM dependency — purely deterministic calculations.
"""

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

# Standard A-share benchmark codes
BENCHMARK_CODES = {
    "CSI300": "000300",   # 沪深300
    "CSI500": "000905",   # 中证500
}


@dataclass
class BenchmarkMetrics:
    """Strategy performance relative to a benchmark."""

    benchmark_name: str
    benchmark_return_pct: float        # benchmark total return over period
    excess_return_pct: float           # strategy return - benchmark return
    alpha: float                        # annualized alpha (excess over risk-free)
    beta: float                         # market sensitivity
    information_ratio: float            # active return / tracking error
    tracking_error_pct: float           # std of excess daily returns (annualized)
    capture_up_pct: float              # up-market capture ratio
    capture_down_pct: float            # down-market capture ratio
    correlation: float                  # correlation between strategy and benchmark
    benchmark_values: list[float] = field(default_factory=list)  # daily benchmark equity curve


def load_benchmark_data(
    code: str,
    start_date: str,
    end_date: str,
    data_dir: str | Path = "data/backtest",
    initial_value: float = 100000,
) -> pd.DataFrame:
    """Load benchmark index K-line data and compute daily equity curve.

    Args:
        code: Benchmark index code (e.g. '000300' for CSI 300).
        start_date / end_date: Date range.
        data_dir: Cache directory for CSV data.
        initial_value: Starting value for the equity curve.

    Returns:
        DataFrame with columns: date, close, daily_return, equity_value.
    """
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    cache_file = data_dir / f"bm_{code}_{start_date}_{end_date}.csv"

    df = None

    if cache_file.exists():
        df = pd.read_csv(cache_file)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"])
            return _build_equity_curve(df, initial_value)

    # Try akshare
    try:
        import akshare as ak
        raw = ak.stock_zh_a_hist(
            symbol=code, period="daily",
            start_date=start_date, end_date=end_date,
        )
        if raw is not None and not raw.empty:
            df = pd.DataFrame({
                "date": pd.to_datetime(raw["日期"]),
                "close": raw["收盘"].astype(float),
            })
            df = df.sort_values("date").reset_index(drop=True)
            df.to_csv(cache_file, index=False)
    except Exception:
        pass

    # Try mootdx fallback
    if df is None:
        try:
            from astock_data.market.mootdx_quote import get_kline
            kline = get_kline(code, category="day", offset=500)
            if kline is not None and not kline.empty:
                if "close" in kline.columns:
                    df = pd.DataFrame({
                        "date": pd.to_datetime(kline.index)
                        if "date" not in kline.columns
                        else pd.to_datetime(kline["date"]),
                        "close": kline["close"].astype(float),
                    })
                    df = df.sort_values("date").reset_index(drop=True)
                    df.to_csv(cache_file, index=False)
        except Exception:
            pass

    if df is None or df.empty:
        return pd.DataFrame()

    return _build_equity_curve(df, initial_value)


def _build_equity_curve(df: pd.DataFrame, initial_value: float) -> pd.DataFrame:
    """Build daily equity curve from price data."""
    df = df.sort_values("date").reset_index(drop=True)
    df["daily_return"] = df["close"].pct_change().fillna(0.0)
    df["equity_value"] = initial_value * (1 + df["daily_return"]).cumprod()
    return df


def compare_to_benchmark(
    strategy_values: list[float],
    strategy_dates: list[str],
    benchmark_name: str = "CSI300",
    benchmark_df: pd.DataFrame | None = None,
    risk_free_rate: float = 0.02,
) -> BenchmarkMetrics:
    """Compare strategy equity curve to a benchmark.

    Args:
        strategy_values: Daily equity values for the strategy.
        strategy_dates: Dates corresponding to strategy_values (YYYY-MM-DD).
        benchmark_name: Label for the benchmark.
        benchmark_df: Pre-loaded benchmark equity curve (from load_benchmark_data).
        risk_free_rate: Annual risk-free rate for alpha calculation.

    Returns:
        BenchmarkMetrics with all relative performance measures.
    """
    if benchmark_df is None or benchmark_df.empty:
        return BenchmarkMetrics(
            benchmark_name=benchmark_name,
            benchmark_return_pct=0,
            excess_return_pct=0,
            alpha=0, beta=0, information_ratio=0, tracking_error_pct=0,
            capture_up_pct=0, capture_down_pct=0, correlation=0,
        )

    if len(strategy_values) < 2:
        return BenchmarkMetrics(
            benchmark_name=benchmark_name,
            benchmark_return_pct=0,
            excess_return_pct=0,
            alpha=0, beta=0, information_ratio=0, tracking_error_pct=0,
            capture_up_pct=0, capture_down_pct=0, correlation=0,
        )

    # Align dates
    date_to_bench = dict(zip(
        benchmark_df["date"].dt.strftime("%Y-%m-%d"),
        benchmark_df["equity_value"],
    ))

    aligned_bench = []
    aligned_strat = []
    strat_returns = []
    bench_returns = []

    for i, d in enumerate(strategy_dates):
        if d in date_to_bench and i < len(strategy_values):
            aligned_bench.append(date_to_bench[d])
            aligned_strat.append(strategy_values[i])

    if len(aligned_strat) < 2:
        return BenchmarkMetrics(
            benchmark_name=benchmark_name,
            benchmark_return_pct=0,
            excess_return_pct=0,
            alpha=0, beta=0, information_ratio=0, tracking_error_pct=0,
            capture_up_pct=0, capture_down_pct=0, correlation=0,
        )

    # Daily returns
    for i in range(1, len(aligned_strat)):
        if aligned_strat[i - 1] > 0 and aligned_bench[i - 1] > 0:
            strat_returns.append(
                (aligned_strat[i] - aligned_strat[i - 1]) / aligned_strat[i - 1]
            )
            bench_returns.append(
                (aligned_bench[i] - aligned_bench[i - 1]) / aligned_bench[i - 1]
            )

    if len(strat_returns) < 2:
        return BenchmarkMetrics(
            benchmark_name=benchmark_name,
            benchmark_return_pct=0,
            excess_return_pct=0,
            alpha=0, beta=0, information_ratio=0, tracking_error_pct=0,
            capture_up_pct=0, capture_down_pct=0, correlation=0,
        )

    n = len(strat_returns)

    # Total returns
    bench_total_ret = (aligned_bench[-1] / aligned_bench[0] - 1) * 100 if aligned_bench[0] > 0 else 0
    strat_total_ret = (aligned_strat[-1] / aligned_strat[0] - 1) * 100 if aligned_strat[0] > 0 else 0
    excess_return = strat_total_ret - bench_total_ret

    # Beta: Cov(strat, bench) / Var(bench)
    avg_s = sum(strat_returns) / n
    avg_b = sum(bench_returns) / n
    cov = sum((strat_returns[i] - avg_s) * (bench_returns[i] - avg_b) for i in range(n)) / n
    var_b = sum((r - avg_b) ** 2 for r in bench_returns) / n
    beta = cov / var_b if var_b > 0 else 1.0

    # Alpha (annualized): (avg_strat_ret - risk_free_daily) - beta * (avg_bench_ret - risk_free_daily)
    rf_daily = risk_free_rate / 252
    alpha = ((avg_s - rf_daily) - beta * (avg_b - rf_daily)) * 252 * 100

    # Tracking error
    excess_returns = [strat_returns[i] - bench_returns[i] for i in range(n)]
    avg_excess = sum(excess_returns) / n
    te_daily = math.sqrt(sum((e - avg_excess) ** 2 for e in excess_returns) / n)
    te_annual = te_daily * math.sqrt(252) * 100

    # Information ratio
    ir = (avg_excess * 252) / (te_daily * math.sqrt(252)) if te_daily > 0 else 0

    # Up/down capture
    up_strat = [strat_returns[i] for i in range(n) if bench_returns[i] > 0]
    up_bench = [bench_returns[i] for i in range(n) if bench_returns[i] > 0]
    down_strat = [strat_returns[i] for i in range(n) if bench_returns[i] < 0]
    down_bench = [bench_returns[i] for i in range(n) if bench_returns[i] < 0]

    if up_bench:
        avg_up_strat = sum(up_strat) / len(up_strat)
        avg_up_bench = sum(up_bench) / len(up_bench)
        capture_up = (avg_up_strat / avg_up_bench * 100) if avg_up_bench > 0 else 0
    else:
        capture_up = 0

    if down_bench:
        avg_down_strat = sum(down_strat) / len(down_strat)
        avg_down_bench = sum(down_bench) / len(down_bench)
        capture_down = (avg_down_strat / avg_down_bench * 100) if avg_down_bench < 0 else 0
    else:
        capture_down = 0

    # Correlation
    var_s = sum((r - avg_s) ** 2 for r in strat_returns) / n
    correlation = cov / (math.sqrt(var_s) * math.sqrt(var_b)) if var_s > 0 and var_b > 0 else 0

    return BenchmarkMetrics(
        benchmark_name=benchmark_name,
        benchmark_return_pct=round(bench_total_ret, 2),
        excess_return_pct=round(excess_return, 2),
        alpha=round(alpha, 2),
        beta=round(beta, 3),
        information_ratio=round(ir, 3),
        tracking_error_pct=round(te_annual, 2),
        capture_up_pct=round(capture_up, 2),
        capture_down_pct=round(capture_down, 2),
        correlation=round(correlation, 3),
        benchmark_values=aligned_bench,
    )
