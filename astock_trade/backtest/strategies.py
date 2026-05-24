"""Built-in backtest strategies — each takes a DataFrame and returns buy/sell signals.

A strategy function signature:
    strategy(df: pd.DataFrame, **params) -> list[dict]

Each signal dict:
    {date, symbol, direction (BUY/SELL), price, reason}
"""

import numpy as np
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


# ── TA-Lib 增强策略 ────────────────────────────

def rsi_mean_reversion(
    df: pd.DataFrame, rsi_period: int = 14, oversold: float = 30, overbought: float = 70
) -> list[dict]:
    """RSI均值回归策略。

    BUY 当 RSI < oversold（超卖）。
    SELL 当 RSI > overbought（超买）。
    """
    if df.empty or len(df) < rsi_period:
        return []
    data = df.copy()
    close = data["close"].values
    delta = np.diff(close, prepend=close[0])
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(rsi_period).mean().values
    avg_loss = pd.Series(loss).rolling(rsi_period).mean().values
    rs = np.divide(avg_gain, avg_loss, out=np.zeros_like(avg_gain), where=avg_loss != 0)
    data["rsi"] = 100 - (100 / (1 + rs))
    data["rsi"] = data["rsi"].fillna(50)

    signals = []
    in_position = False
    for _, row in data.iterrows():
        date = str(row.get("date") or row.name)[:10]
        rsi = row["rsi"]
        if rsi < oversold and not in_position:
            in_position = True
            signals.append({"date": date, "direction": "BUY", "price": float(row["close"]),
                            "reason": f"RSI超卖({rsi:.0f}<{oversold})"})
        elif rsi > overbought and in_position:
            in_position = False
            signals.append({"date": date, "direction": "SELL", "price": float(row["close"]),
                            "reason": f"RSI超买({rsi:.0f}>{overbought})"})
    return signals


def macd_signal(df: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> list[dict]:
    """MACD金叉死叉策略。

    BUY 当 MACD 上穿信号线（金叉）。
    SELL 当 MACD 下穿信号线（死叉）。
    """
    if df.empty or len(df) < slow:
        return []
    import talib as tl
    data = df.copy()
    close = data["close"].values.astype(float)
    macd, macds, _ = tl.MACD(close, fastperiod=fast, slowperiod=slow, signalperiod=signal)
    data["macd"] = np.nan_to_num(macd, 0)
    data["macds"] = np.nan_to_num(macds, 0)
    data["hist"] = data["macd"] - data["macds"]
    data["hist_prev"] = data["hist"].shift(1).fillna(0)

    signals = []
    in_position = False
    for _, row in data.iterrows():
        date = str(row.get("date") or row.name)[:10]
        if row["hist_prev"] <= 0 and row["hist"] > 0 and not in_position:
            in_position = True
            signals.append({"date": date, "direction": "BUY", "price": float(row["close"]),
                            "reason": f"MACD金叉({fast},{slow},{signal})"})
        elif row["hist_prev"] >= 0 and row["hist"] < 0 and in_position:
            in_position = False
            signals.append({"date": date, "direction": "SELL", "price": float(row["close"]),
                            "reason": f"MACD死叉({fast},{slow},{signal})"})
    return signals


def bollinger_breakout(df: pd.DataFrame, period: int = 20, nbdev: float = 2.0) -> list[dict]:
    """布林带突破策略。

    BUY 当收盘价跌破下轨后回到下轨之上。
    SELL 当收盘价突破上轨后回到上轨之下。
    """
    if df.empty or len(df) < period:
        return []
    import talib as tl
    data = df.copy()
    close = data["close"].values.astype(float)
    ub, mid, lb = tl.BBANDS(close, timeperiod=period, nbdevup=nbdev, nbdevdn=nbdev, matype=0)
    data["boll_ub"] = np.nan_to_num(ub, 0)
    data["boll_lb"] = np.nan_to_num(lb, 0)
    data["boll_mid"] = np.nan_to_num(mid, 0)
    data["below_lb"] = data["close"] < data["boll_lb"]
    data["above_ub"] = data["close"] > data["boll_ub"]

    signals = []
    waiting_buy = False
    in_position = False
    for _, row in data.iterrows():
        date = str(row.get("date") or row.name)[:10]
        if row["below_lb"]:
            waiting_buy = True
        elif waiting_buy and row["close"] >= row["boll_lb"] and not in_position:
            waiting_buy = False
            in_position = True
            signals.append({"date": date, "direction": "BUY", "price": float(row["close"]),
                            "reason": "布林下轨反弹"})
        if row["above_ub"] and in_position:
            in_position = False
            signals.append({"date": date, "direction": "SELL", "price": float(row["close"]),
                            "reason": "布林上轨回落"})
    return signals


def kdj_signal(df: pd.DataFrame, k_period: int = 9, d_period: int = 3) -> list[dict]:
    """KDJ策略：K线上穿D线为金叉买入，下穿为死叉卖出。

    BUY 当 K 上穿 D（金叉）且 K < 50（低位金叉更可靠）。
    SELL 当 K 下穿 D（死叉）且 K > 50（高位死叉更可靠）。
    """
    if df.empty or len(df) < k_period:
        return []
    import talib as tl
    data = df.copy()
    k, d = tl.STOCH(data["high"].values.astype(float), data["low"].values.astype(float),
                     data["close"].values.astype(float),
                     fastk_period=k_period, slowk_period=d_period, slowk_matype=1,
                     slowd_period=d_period, slowd_matype=1)
    data["k"] = np.nan_to_num(k, 50)
    data["d"] = np.nan_to_num(d, 50)
    data["k_prev"] = data["k"].shift(1).fillna(50)
    data["d_prev"] = data["d"].shift(1).fillna(50)

    signals = []
    in_position = False
    for _, row in data.iterrows():
        date = str(row.get("date") or row.name)[:10]
        # K上穿D
        if row["k_prev"] <= row["d_prev"] and row["k"] > row["d"] and not in_position:
            in_position = True
            signals.append({"date": date, "direction": "BUY", "price": float(row["close"]),
                            "reason": f"KDJ金叉(K={row['k']:.0f},D={row['d']:.0f})"})
        # K下穿D
        elif row["k_prev"] >= row["d_prev"] and row["k"] < row["d"] and in_position:
            in_position = False
            signals.append({"date": date, "direction": "SELL", "price": float(row["close"]),
                            "reason": f"KDJ死叉(K={row['k']:.0f},D={row['d']:.0f})"})
    return signals


def supertrend_strategy(df: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> list[dict]:
    """SuperTrend 趋势跟踪策略。

    BUY 当价格上穿 SuperTrend（由跌转涨）。
    SELL 当价格下穿 SuperTrend（由涨转跌）。
    """
    if df.empty or len(df) < period:
        return []
    import talib as tl
    data = df.copy()
    high = data["high"].values.astype(float)
    low = data["low"].values.astype(float)
    close = data["close"].values.astype(float)
    atr = tl.ATR(high, low, close, timeperiod=period)
    atr = np.nan_to_num(atr, 0)
    hl_avg = (high + low) / 2
    b_ub = hl_avg + multiplier * atr
    b_lb = hl_avg - multiplier * atr
    size = len(data)
    ub = np.empty(size)
    lb = np.empty(size)
    st = np.empty(size)
    for i in range(size):
        if i == 0:
            ub[i] = b_ub[i]
            lb[i] = b_lb[i]
            st[i] = ub[i] if close[i] <= ub[i] else lb[i]
            continue
        last_close = close[i - 1]
        last_ub = ub[i - 1]
        last_lb = lb[i - 1]
        last_st = st[i - 1]
        ub[i] = b_ub[i] if (b_ub[i] < last_ub or last_close > last_ub) else last_ub
        lb[i] = b_lb[i] if (b_lb[i] > last_lb or last_close < last_lb) else last_lb
        if last_st == last_ub:
            st[i] = ub[i] if close[i] <= ub[i] else lb[i]
        else:
            st[i] = lb[i] if close[i] > lb[i] else ub[i]
    data["st"] = st
    data["st_prev"] = np.insert(st[:-1], 0, st[0])
    data["above_st"] = close > st
    data["above_prev"] = np.insert(data["above_st"].values[:-1], 0, data["above_st"].values[0])

    signals = []
    in_position = False
    for _, row in data.iterrows():
        date = str(row.get("date") or row.name)[:10]
        if not row["above_prev"] and row["above_st"] and not in_position:
            in_position = True
            signals.append({"date": date, "direction": "BUY", "price": float(row["close"]),
                            "reason": "SuperTrend转多"})
        elif row["above_prev"] and not row["above_st"] and in_position:
            in_position = False
            signals.append({"date": date, "direction": "SELL", "price": float(row["close"]),
                            "reason": "SuperTrend转空"})
    return signals
