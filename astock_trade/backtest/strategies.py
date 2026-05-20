"""Built-in backtest strategies — each takes a DataFrame and returns buy/sell signals.

A strategy function signature:
    strategy(df: pd.DataFrame, **params) -> list[dict]

Each signal dict:
    {date, symbol, direction (BUY/SELL), price, reason}
"""

import pandas as pd


def ma_crossover(
    df: pd.DataFrame, fast: int = 5, slow: int = 20
) -> list[dict]:
    """Simple MA crossover strategy.

    BUY when fast MA crosses above slow MA.
    SELL when fast MA crosses below slow MA.
    """
    if df.empty or len(df) < slow:
        return []

    data = df.copy()
    data["ma_fast"] = data["close"].rolling(window=fast).mean()
    data["ma_slow"] = data["close"].rolling(window=slow).mean()

    # Crossover signals
    data["cross"] = data["ma_fast"] - data["ma_slow"]
    data["cross_prev"] = data["cross"].shift(1)
    data["buy_signal"] = (data["cross_prev"] <= 0) & (data["cross"] > 0)
    data["sell_signal"] = (data["cross_prev"] >= 0) & (data["cross"] < 0)

    signals = []
    for _, row in data.iterrows():
        date = row.get("date") or row.name
        if row.get("buy_signal"):
            signals.append({
                "date": str(date)[:10],
                "direction": "BUY",
                "price": float(row["close"]),
                "reason": f"MA{fast}上穿MA{slow}",
            })
        elif row.get("sell_signal"):
            signals.append({
                "date": str(date)[:10],
                "direction": "SELL",
                "price": float(row["close"]),
                "reason": f"MA{fast}下穿MA{slow}",
            })

    return signals


def price_breakout(
    df: pd.DataFrame, lookback: int = 20, threshold_pct: float = 3.0
) -> list[dict]:
    """Price breakout strategy.

    BUY when close breaks above the highest high of lookback period.
    SELL when close breaks below the lowest low of lookback period.
    """
    if df.empty or len(df) < lookback:
        return []

    data = df.copy()
    data["hh"] = data["high"].rolling(window=lookback).max().shift(1)
    data["ll"] = data["low"].rolling(window=lookback).min().shift(1)
    data["buy_signal"] = data["close"] > data["hh"] * (1 + threshold_pct / 100)
    data["sell_signal"] = data["close"] < data["ll"] * (1 - threshold_pct / 100)

    signals = []
    for _, row in data.iterrows():
        date = row.get("date") or row.name
        if row.get("buy_signal"):
            signals.append({
                "date": str(date)[:10],
                "direction": "BUY",
                "price": float(row["close"]),
                "reason": f"突破{lookback}日高点(>{threshold_pct}%)",
            })
        elif row.get("sell_signal"):
            signals.append({
                "date": str(date)[:10],
                "direction": "SELL",
                "price": float(row["close"]),
                "reason": f"跌破{lookback}日低点(>{threshold_pct}%)",
            })

    return signals


def ma_crossover_volume(
    df: pd.DataFrame, fast: int = 5, slow: int = 20, vol_factor: float = 1.2
) -> list[dict]:
    """MA crossover + volume confirmation.

    BUY when fast MA crosses above slow MA AND volume > vol_factor * avg volume.
    SELL when fast MA crosses below slow MA.
    """
    if df.empty or len(df) < slow:
        return []

    data = df.copy()
    data["ma_fast"] = data["close"].rolling(window=fast).mean()
    data["ma_slow"] = data["close"].rolling(window=slow).mean()
    data["vol_avg"] = data["vol"].rolling(window=20).mean()

    data["cross"] = data["ma_fast"] - data["ma_slow"]
    data["cross_prev"] = data["cross"].shift(1)
    data["golden_cross"] = (data["cross_prev"] <= 0) & (data["cross"] > 0)
    data["dead_cross"] = (data["cross_prev"] >= 0) & (data["cross"] < 0)
    data["vol_confirm"] = data["vol"] > data["vol_avg"] * vol_factor

    data["buy_signal"] = data["golden_cross"] & data["vol_confirm"]
    data["sell_signal"] = data["dead_cross"]

    signals = []
    for _, row in data.iterrows():
        date = row.get("date") or row.name
        if row.get("buy_signal"):
            signals.append({
                "date": str(date)[:10],
                "direction": "BUY",
                "price": float(row["close"]),
                "reason": f"MA{fast}金叉MA{slow}+放量",
            })
        elif row.get("sell_signal"):
            signals.append({
                "date": str(date)[:10],
                "direction": "SELL",
                "price": float(row["close"]),
                "reason": f"MA{fast}死叉MA{slow}",
            })

    return signals


def ma_crossover_trend(
    df: pd.DataFrame, fast: int = 5, slow: int = 20, trend: int = 60
) -> list[dict]:
    """MA crossover with trend filter — only trade in trend direction.

    BUY when golden cross AND close > MA(trend) (uptrend).
    SELL when dead cross OR close < MA(trend) (downtrend stop).
    """
    if df.empty or len(df) < max(slow, trend):
        return []

    data = df.copy()
    data["ma_fast"] = data["close"].rolling(window=fast).mean()
    data["ma_slow"] = data["close"].rolling(window=slow).mean()
    data["ma_trend"] = data["close"].rolling(window=trend).mean()

    data["cross"] = data["ma_fast"] - data["ma_slow"]
    data["cross_prev"] = data["cross"].shift(1)
    data["golden_cross"] = (data["cross_prev"] <= 0) & (data["cross"] > 0)
    data["dead_cross"] = (data["cross_prev"] >= 0) & (data["cross"] < 0)
    data["uptrend"] = data["close"] > data["ma_trend"]

    data["buy_signal"] = data["golden_cross"] & data["uptrend"]
    data["sell_signal"] = data["dead_cross"] | (~data["uptrend"])

    signals = []
    in_position = False
    for _, row in data.iterrows():
        date = row.get("date") or row.name
        if row.get("buy_signal") and not in_position:
            in_position = True
            signals.append({
                "date": str(date)[:10],
                "direction": "BUY",
                "price": float(row["close"]),
                "reason": f"MA{fast}金叉MA{slow}+趋势向上",
            })
        elif row.get("sell_signal") and in_position:
            in_position = False
            signals.append({
                "date": str(date)[:10],
                "direction": "SELL",
                "price": float(row["close"]),
                "reason": f"卖出(死叉或破MA{trend})",
            })

    return signals


def triple_filter(
    df: pd.DataFrame,
    fast: int = 5,
    slow: int = 20,
    trend: int = 60,
    rsi_period: int = 14,
    rsi_buy_max: float = 70,
    vol_factor: float = 1.0,
) -> list[dict]:
    """Triple-filter strategy: MA crossover + trend + RSI + volume.

    BUY when:
      1. Fast MA crosses above slow MA (golden cross)
      2. Price above MA(trend) — trend is up
      3. RSI < rsi_buy_max — not overbought
      4. Volume > vol_factor * avg volume — confirmation

    SELL when dead cross OR RSI > 80 OR price breaks below MA(trend).
    """
    min_len = max(slow, trend, rsi_period)
    if df.empty or len(df) < min_len:
        return []

    data = df.copy()
    data["ma_fast"] = data["close"].rolling(window=fast).mean()
    data["ma_slow"] = data["close"].rolling(window=slow).mean()
    data["ma_trend"] = data["close"].rolling(window=trend).mean()
    data["vol_avg"] = data["vol"].rolling(window=20).mean()

    # RSI
    delta = data["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=rsi_period).mean()
    avg_loss = loss.rolling(window=rsi_period).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    data["rsi"] = 100 - (100 / (1 + rs))

    data["cross"] = data["ma_fast"] - data["ma_slow"]
    data["cross_prev"] = data["cross"].shift(1)
    data["golden_cross"] = (data["cross_prev"] <= 0) & (data["cross"] > 0)
    data["dead_cross"] = (data["cross_prev"] >= 0) & (data["cross"] < 0)
    data["uptrend"] = data["close"] > data["ma_trend"]
    data["vol_ok"] = data["vol"] > data["vol_avg"] * vol_factor
    data["rsi_ok"] = data["rsi"] < rsi_buy_max

    data["buy_signal"] = (
        data["golden_cross"] & data["uptrend"] & data["rsi_ok"] & data["vol_ok"]
    )
    data["sell_signal"] = (
        data["dead_cross"] | (data["rsi"] > 80) | (~data["uptrend"])
    )

    signals = []
    in_position = False
    for _, row in data.iterrows():
        date = row.get("date") or row.name
        if row.get("buy_signal") and not in_position:
            in_position = True
            signals.append({
                "date": str(date)[:10],
                "direction": "BUY",
                "price": float(row["close"]),
                "reason": f"三重过滤:金叉+趋势+RSI{row['rsi']:.0f}+放量",
            })
        elif row.get("sell_signal") and in_position:
            in_position = False
            sell_reason = "死叉" if row.get("dead_cross") else (
                "RSI超买" if row["rsi"] > 80 else f"跌破MA{trend}"
            )
            signals.append({
                "date": str(date)[:10],
                "direction": "SELL",
                "price": float(row["close"]),
                "reason": f"卖出({sell_reason})",
            })

    return signals


def buy_and_hold(df: pd.DataFrame) -> list[dict]:
    """Buy on first day, sell on last day — benchmark strategy."""
    if df.empty:
        return []

    data = df.reset_index(drop=True)
    first_row = data.iloc[0]
    last_row = data.iloc[-1]
    first_date = first_row.get("date") or str(first_row.name)[:10]
    last_date = last_row.get("date") or str(last_row.name)[:10]

    return [
        {
            "date": first_date,
            "direction": "BUY",
            "price": float(first_row["close"]),
            "reason": "买入持有",
        },
        {
            "date": last_date,
            "direction": "SELL",
            "price": float(last_row["close"]),
            "reason": "卖出(期末)",
        },
    ]
