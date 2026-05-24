"""Enhanced backtest strategies using TA-Lib indicators and K-line patterns.

These strategies depend on TA-Lib and are loaded when available.
Each function follows the standard signature:
    strategy(df: pd.DataFrame, **params) -> list[dict]

Signal dict: {date, direction (BUY/SELL), price, reason}
"""

import numpy as np
import pandas as pd

try:
    import talib as tl
    _TA_AVAILABLE = True
except ImportError:
    _TA_AVAILABLE = False


def multi_indicator_strategy(
    df: pd.DataFrame,
    rsi_oversold: float = 30,
    rsi_overbought: float = 70,
    bb_period: int = 20,
    macd_fast: int = 12,
    macd_slow: int = 26,
    macd_signal: int = 9,
) -> list[dict]:
    """多指标综合策略：RSI + 布林带 + MACD 三重确认。

    BUY 条件（需同时满足）:
        1. RSI < oversold（超卖）
        2. 收盘价在布林下轨附近（close <= mid）
        3. MACD柱线向上拐头（hist 从负转正或正在收窄）

    SELL 条件（满足任一）:
        1. RSI > overbought（超买）
        2. 收盘价突破布林上轨后回落至上轨以内
    """
    if not _TA_AVAILABLE:
        return []
    if df.empty or len(df) < max(bb_period, macd_slow):
        return []

    data = df.copy()
    close = data["close"].values.astype(float)
    high = data["high"].values.astype(float)
    low = data["low"].values.astype(float)

    # RSI
    rsi_arr = tl.RSI(close, timeperiod=14)
    data["rsi"] = np.nan_to_num(rsi_arr, 50)

    # 布林带
    ub, mid, lb = tl.BBANDS(close, timeperiod=bb_period, nbdevup=2, nbdevdn=2, matype=0)
    data["boll_mid"] = np.nan_to_num(mid, 0)
    data["boll_lb"] = np.nan_to_num(lb, 0)
    data["boll_ub"] = np.nan_to_num(ub, 0)

    # MACD
    macd, macds, _ = tl.MACD(close, fastperiod=macd_fast, slowperiod=macd_slow, signalperiod=macd_signal)
    data["macd_hist"] = np.nan_to_num(macd, 0) - np.nan_to_num(macds, 0)

    signals = []
    in_position = False
    for i, (_, row) in enumerate(data.iterrows()):
        if i < 1:
            continue
        date = str(row.get("date") or row.name)[:10]
        rsi = row["rsi"]
        hist = row["macd_hist"]
        hist_prev = data["macd_hist"].iloc[i - 1]

        buy_confirmed = (
            rsi < rsi_oversold
            and row["close"] <= row["boll_mid"]
            and hist > hist_prev
        )
        sell_signal = rsi > rsi_overbought or (
            row["close"] > row["boll_ub"] and row["close"] <= row["boll_ub"]
        )

        if buy_confirmed and not in_position:
            in_position = True
            signals.append({
                "date": date, "direction": "BUY", "price": float(row["close"]),
                "reason": f"多指标买入(RSI={rsi:.0f},MACD转正,布林中轨以下)",
            })
        elif sell_signal and in_position:
            in_position = False
            signals.append({
                "date": date, "direction": "SELL", "price": float(row["close"]),
                "reason": f"多指标卖出(RSI={rsi:.0f},布林上轨回落)",
            })

    return signals


def pattern_based_strategy(
    df: pd.DataFrame,
    buy_patterns: tuple = ("hammer", "morning_star", "piercing", "three_white_soldiers"),
    sell_patterns: tuple = ("shooting_star", "evening_star", "dark_cloud_cover", "three_black_crows"),
) -> list[dict]:
    """K线形态策略：基于 TA-Lib CDL 形态识别。

    BUY 当出现买入形态（锤头/晨星/刺透/三白兵等）。
    SELL 当出现卖出形态（射击之星/暮星/乌云盖顶/三乌鸦等）。

    Args:
        buy_patterns: 触发买入的形态名元组。
        sell_patterns: 触发卖出的形态名元组。
    """
    if not _TA_AVAILABLE:
        return []
    if df.empty or len(df) < 5:
        return []

    data = df.copy()
    o = data["open"].values.astype(float)
    h = data["high"].values.astype(float)
    l = data["low"].values.astype(float)
    c = data["close"].values.astype(float)

    # 形态映射
    _FUNC_MAP = {
        "hammer": tl.CDLHAMMER,
        "shooting_star": tl.CDLSHOOTINGSTAR,
        "morning_star": tl.CDLMORNINGSTAR,
        "evening_star": tl.CDLEVENINGSTAR,
        "piercing": tl.CDLPIERCING,
        "dark_cloud_cover": tl.CDLDARKCLOUDCOVER,
        "three_white_soldiers": tl.CDL3WHITESOLDIERS,
        "three_black_crows": tl.CDL3BLACKCROWS,
        "engulfing": tl.CDLENGULFING,
        "doji": tl.CDLDOJI,
        "harami": tl.CDLHARAMI,
        "morning_doji_star": tl.CDLMORNINGDOJISTAR,
        "evening_doji_star": tl.CDLEVENINGDOJISTAR,
        "inverted_hammer": tl.CDLINVERTEDHAMMER,
        "hanging_man": tl.CDLHANGINGMAN,
    }

    # 计算所有需要的形态
    needed = set(buy_patterns) | set(sell_patterns)
    pattern_cols = {}
    for name in needed:
        func = _FUNC_MAP.get(name)
        if func:
            arr = func(o, h, l, c)
            pattern_cols[name] = np.nan_to_num(arr, 0)

    signals = []
    in_position = False
    for i, (_, row) in enumerate(data.iterrows()):
        if i < 3:
            continue
        date = str(row.get("date") or row.name)[:10]

        # 检查买入形态
        buy_hit = None
        for name in buy_patterns:
            if name in pattern_cols and pattern_cols[name][i] > 0:
                buy_hit = name
                break

        # 检查卖出形态
        sell_hit = None
        for name in sell_patterns:
            if name in pattern_cols and pattern_cols[name][i] < 0:
                sell_hit = name
                break

        if buy_hit and not in_position:
            in_position = True
            signals.append({"date": date, "direction": "BUY", "price": float(row["close"]),
                            "reason": f"K线形态买入({buy_hit})"})
        elif sell_hit and in_position:
            in_position = False
            signals.append({"date": date, "direction": "SELL", "price": float(row["close"]),
                            "reason": f"K线形态卖出({sell_hit})"})

    return signals
