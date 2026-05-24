# 32种技术指标计算
# 移植自 InStock (myhhub/stock) — 结果对齐同花顺/通达信

import logging
import numpy as np
import pandas as pd
import talib as tl

from astock_data.ta.config import INDICATOR_DEFAULT_THRESHOLD, INDICATOR_CALC_THRESHOLD

logger = logging.getLogger(__name__)

# 列名别名映射：统一标准化为 InStock 的列名
_COLUMN_ALIASES = {
    "vol": "volume",       # mootdx 使用 vol
    "datetime": "date",    # mootdx 使用 datetime
    "date": "date",
    "open": "open",
    "close": "close",
    "high": "high",
    "low": "low",
    "volume": "volume",
    "amount": "amount",
}


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """统一输入 DataFrame 的列名并确保数值列类型为 float64。"""
    renamed = {}
    for col in df.columns:
        col_lower = col.lower().strip()
        if col_lower in _COLUMN_ALIASES:
            target = _COLUMN_ALIASES[col_lower]
            if target != col:
                renamed[col] = target
    if renamed:
        df = df.rename(columns=renamed)
    # 确保OHLCV列为float64（TA-Lib要求）
    for col in ["open", "close", "high", "low", "volume", "amount"]:
        if col in df.columns:
            df[col] = df[col].astype(np.float64)
    return df


def _required_columns(df: pd.DataFrame) -> bool:
    """检查必要的OHLCV列是否存在。"""
    required = {"open", "close", "high", "low", "volume"}
    missing = required - set(df.columns)
    if missing:
        logger.error(f"指标计算缺少必要列: {missing}")
        return False
    return True


# ──────────────────────────────────────────────
# 公开函数
# ──────────────────────────────────────────────

def compute_indicators(
    data: pd.DataFrame,
    end_date: str | None = None,
    threshold: int | None = INDICATOR_DEFAULT_THRESHOLD,
    calc_threshold: int | None = INDICATOR_CALC_THRESHOLD,
) -> pd.DataFrame | None:
    """计算32种技术指标，返回添加了指标列的 DataFrame。

    Args:
        data: 包含 open/close/high/low/volume/amount 列的OHLCV数据。
        end_date: 可选，只计算该日期之前的数据。
        threshold: 返回最近 N 行（None=全部）。
        calc_threshold: 计算窗口限制（None=全部）。

    Returns:
        添加了指标列的 DataFrame，或 None（出错时）。
    """
    try:
        data = _normalize_columns(data)
        if not _required_columns(data):
            return None

        is_copy = False
        if end_date is not None and "date" in data.columns:
            mask = data["date"] <= end_date
            data = data.loc[mask]
            is_copy = True
        if calc_threshold is not None:
            data = data.tail(n=calc_threshold)
            is_copy = True
        if is_copy:
            data = data.copy()

        # 补齐 p_change
        close_arr = data["close"].values.astype(np.float64)
        p_change = np.nan_to_num(tl.ROC(close_arr, 1), 0)

        # 将 p_change 加入 DataFrame（仅一列，不会引起碎片化）
        data["p_change"] = p_change
        # 使用 dict 收集所有指标列，避免逐个插入导致的碎片化问题
        out = {}
        with np.errstate(divide="ignore", invalid="ignore"):
            _compute_macd(data, out)
            _compute_kdj(data, out)
            _compute_boll(data, out)
            _compute_trix(data, out)
            _compute_cr(data, out)
            _compute_rsi(data, out)
            _compute_vr(data, out)
            _compute_atr(data, out)
            _compute_dmi(data, out)
            _compute_wr(data, out)
            _compute_cci(data, out)
            _compute_dma(data, out)
            _compute_tema(data, out)
            _compute_mfi(data, out)
            _compute_vwma(data, out)
            _compute_ppo(data, out)
            _compute_stochrsi(data, out)
            _compute_wt(data, out)
            _compute_supertrend(data, out)
            _compute_roc(data, out)
            _compute_obv(data, out)
            _compute_sar(data, out)
            _compute_psy(data, out)
            _compute_brar(data, out)
            _compute_emv(data, out)
            _compute_bias(data, out)
            _compute_dpo(data, out)
            _compute_vhf(data, out)
            _compute_rvi(data, out)
            _compute_fi(data, out)
            _compute_ene(data, out)
            _compute_vol_ma(data, out)
            _compute_ma(data, out)

        # 一次性将所有指标列应用到 DataFrame
        for col_name, col_data in out.items():
            data[col_name] = col_data

        if threshold is not None:
            data = data.tail(n=threshold).copy()
        return data

    except Exception as e:
        code = data.get("code", "unknown") if isinstance(data, pd.DataFrame) else "unknown"
        logger.error(f"compute_indicators 异常 [{code}]: {e}")
        return None


def get_latest_indicators(
    data: pd.DataFrame,
    calc_threshold: int = 90,
) -> dict:
    """计算并返回最后一行的所有指标值（供 Agent / CLI 使用）。

    Args:
        data: OHLCV DataFrame。
        calc_threshold: 计算窗口。

    Returns:
        {指标名: 值} 字典，出错返回空 dict。
    """
    result = compute_indicators(data, threshold=1, calc_threshold=calc_threshold)
    if result is None or len(result) == 0:
        return {}

    row = result.iloc[0]
    # 排除原始OHLCV列，只保留指标列
    exclude = {"date", "code", "open", "close", "high", "low",
               "volume", "amount", "p_change", "prev_close"}
    indicators = {}
    for col in result.columns:
        if col not in exclude:
            val = row[col]
            if isinstance(val, (int, float, np.floating, np.integer)):
                indicators[col] = round(float(val), 4) if not np.isnan(val) and not np.isinf(val) else 0.0
            else:
                indicators[col] = val
    return indicators


# ──────────────────────────────────────────────
# 各指标计算（私有）
# ──────────────────────────────────────────────

def _sfill(arr, fill=0.0):
    """安全填充 NaN/Inf 到 fill 值，返回 numpy 数组。"""
    return np.nan_to_num(np.asarray(arr, dtype=np.float64), nan=fill, posinf=fill, neginf=fill)


def _compute_macd(data, out):
    close = data["close"].values.astype(np.float64)
    macd, macds, macdh = tl.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    out["macd"] = _sfill(macd)
    out["macds"] = _sfill(macds)
    out["macdh"] = _sfill(macdh)


def _compute_kdj(data, out):
    h = data["high"].values.astype(np.float64)
    l = data["low"].values.astype(np.float64)
    c = data["close"].values.astype(np.float64)
    k, d = tl.STOCH(h, l, c, fastk_period=9, slowk_period=5, slowk_matype=1,
                    slowd_period=5, slowd_matype=1)
    k = _sfill(k)
    d = _sfill(d)
    out["kdjk"] = k
    out["kdjd"] = d
    out["kdjj"] = 3 * k - 2 * d


def _compute_boll(data, out):
    close = data["close"].values.astype(np.float64)
    ub, mid, lb = tl.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0)
    out["boll_ub"] = _sfill(ub)
    out["boll"] = _sfill(mid)
    out["boll_lb"] = _sfill(lb)


def _compute_trix(data, out):
    close = data["close"].values.astype(np.float64)
    trix = tl.TRIX(close, timeperiod=12)
    trix = _sfill(trix)
    out["trix"] = trix
    out["trix_20_sma"] = _sfill(tl.MA(trix, timeperiod=20))


def _compute_cr(data, out):
    amt = data["amount"].values.astype(np.float64)
    vol = data["volume"].values.astype(np.float64)
    high = data["high"].values.astype(np.float64)
    low = data["low"].values.astype(np.float64)
    close = data["close"].values.astype(np.float64)
    m_price = np.divide(amt, vol, out=np.zeros_like(amt), where=vol != 0)
    m_price_sf1 = np.insert(m_price[:-1], 0, 0.0)
    h_m = high - np.minimum(m_price_sf1, high)
    m_l = m_price_sf1 - np.minimum(m_price_sf1, low)
    h_m_sum = _sfill(tl.SUM(h_m, timeperiod=26))
    m_l_sum = _sfill(tl.SUM(m_l, timeperiod=26))
    cr = np.divide(h_m_sum, m_l_sum, out=np.zeros_like(h_m_sum), where=m_l_sum != 0) * 100
    out["cr"] = _sfill(cr)
    for p, i in [(5, 1), (10, 2), (20, 3)]:
        out[f"cr-ma{i}"] = _sfill(tl.MA(cr, timeperiod=p))


def _compute_rsi(data, out):
    close = data["close"].values.astype(np.float64)
    out["rsi"] = _sfill(tl.RSI(close, timeperiod=14))
    out["rsi_6"] = _sfill(tl.RSI(close, timeperiod=6))
    out["rsi_12"] = _sfill(tl.RSI(close, timeperiod=12))
    out["rsi_24"] = _sfill(tl.RSI(close, timeperiod=24))


def _compute_vr(data, out):
    pchg = data["p_change"]
    vol = data["volume"].values.astype(np.float64)
    av = np.where(pchg > 0, vol, 0)
    bv = np.where(pchg < 0, vol, 0)
    cv = np.where(pchg == 0, vol, 0)
    avs = _sfill(tl.SUM(av, timeperiod=26))
    bvs = _sfill(tl.SUM(bv, timeperiod=26))
    cvs = _sfill(tl.SUM(cv, timeperiod=26))
    denom = bvs + cvs / 2
    vr = np.divide(avs + cvs / 2, denom, out=np.zeros_like(avs), where=denom != 0) * 100
    out["vr"] = _sfill(vr)
    out["vr_6_sma"] = _sfill(tl.MA(vr, timeperiod=6))


def _compute_atr(data, out):
    h = data["high"].values.astype(np.float64)
    l = data["low"].values.astype(np.float64)
    c = data["close"].values.astype(np.float64)
    out["atr"] = _sfill(tl.ATR(h, l, c, timeperiod=14))


def _compute_dmi(data, out):
    """使用 stockstats 风格公式（与同花顺/通达信对齐）。"""
    h = data["high"].values.astype(np.float64)
    l = data["low"].values.astype(np.float64)
    atr = out["atr"]  # 已经计算好
    high_delta = np.insert(np.diff(h), 0, 0.0)
    low_delta = np.insert(-np.diff(l), 0, 0.0)
    high_m = (high_delta + abs(high_delta)) / 2
    low_m = (low_delta + abs(low_delta)) / 2
    pdm = _sfill(tl.EMA(np.where(high_m > low_m, high_m, 0), timeperiod=14))
    mdm = _sfill(tl.EMA(np.where(low_m > high_m, low_m, 0), timeperiod=14))
    pdi = np.divide(pdm, atr, out=np.zeros_like(pdm), where=atr != 0) * 100
    mdi = np.divide(mdm, atr, out=np.zeros_like(mdm), where=atr != 0) * 100
    sum_dm = pdi + mdi
    dx = np.divide(abs(pdi - mdi), sum_dm, out=np.zeros_like(pdi), where=sum_dm != 0) * 100
    out["pdi"] = _sfill(pdi)
    out["mdi"] = _sfill(mdi)
    out["dx"] = _sfill(dx)
    out["adx"] = _sfill(tl.EMA(dx, timeperiod=6))
    out["adxr"] = _sfill(tl.EMA(out["adx"], timeperiod=6))


def _compute_wr(data, out):
    h = data["high"].values.astype(np.float64)
    l = data["low"].values.astype(np.float64)
    c = data["close"].values.astype(np.float64)
    for p in (6, 10, 14):
        out[f"wr_{p}"] = _sfill(tl.WILLR(h, l, c, timeperiod=p))


def _compute_cci(data, out):
    h = data["high"].values.astype(np.float64)
    l = data["low"].values.astype(np.float64)
    c = data["close"].values.astype(np.float64)
    out["cci"] = _sfill(tl.CCI(h, l, c, timeperiod=14))
    out["cci_84"] = _sfill(tl.CCI(h, l, c, timeperiod=84))


def _compute_dma(data, out):
    close = data["close"].values.astype(np.float64)
    ma10 = _sfill(tl.MA(close, timeperiod=10))
    ma50 = _sfill(tl.MA(close, timeperiod=50))
    out["ma10"] = ma10
    out["ma50"] = ma50
    out["dma"] = ma10 - ma50
    out["dma_10_sma"] = _sfill(tl.MA(out["dma"], timeperiod=10))


def _compute_tema(data, out):
    close = data["close"].values.astype(np.float64)
    out["tema"] = _sfill(tl.TEMA(close, timeperiod=14))


def _compute_mfi(data, out):
    h = data["high"].values.astype(np.float64)
    l = data["low"].values.astype(np.float64)
    c = data["close"].values.astype(np.float64)
    v = data["volume"].values.astype(np.float64)
    out["mfi"] = _sfill(tl.MFI(h, l, c, v, timeperiod=14))
    out["mfisma"] = _sfill(tl.MA(out["mfi"], timeperiod=6))


def _compute_vwma(data, out):
    amt = data["amount"].values.astype(np.float64)
    vol = data["volume"].values.astype(np.float64)
    tpv = _sfill(tl.SUM(amt, timeperiod=14))
    v14 = _sfill(tl.SUM(vol, timeperiod=14))
    vwma = np.divide(tpv, v14, out=np.zeros_like(tpv), where=v14 != 0)
    out["vwma"] = _sfill(vwma)
    out["mvwma"] = _sfill(tl.MA(vwma, timeperiod=6))


def _compute_ppo(data, out):
    close = data["close"].values.astype(np.float64)
    ppo = _sfill(tl.PPO(close, fastperiod=12, slowperiod=26, matype=1))
    out["ppo"] = ppo
    out["ppos"] = _sfill(tl.EMA(ppo, timeperiod=9))
    out["ppoh"] = ppo - out["ppos"]


def _compute_stochrsi(data, out):
    """stockstats 风格（非 TA-Lib 原生 STOCHRSI）。"""
    rsi = out["rsi"]
    rsi_min = _sfill(tl.MIN(rsi, timeperiod=14))
    rsi_max = _sfill(tl.MAX(rsi, timeperiod=14))
    denom = rsi_max - rsi_min
    k = np.divide(rsi - rsi_min, denom, out=np.zeros_like(rsi), where=denom != 0) * 100
    out["stochrsi_k"] = _sfill(k)
    out["stochrsi_d"] = _sfill(tl.MA(k, timeperiod=3))


def _compute_wt(data, out):
    m_price = np.divide(data["amount"].values.astype(np.float64),
                         data["volume"].values.astype(np.float64),
                         out=np.zeros(len(data), dtype=np.float64),
                         where=data["volume"].values != 0)
    esa = _sfill(tl.EMA(m_price, timeperiod=10))
    esa_d = _sfill(tl.EMA(abs(m_price - esa), timeperiod=10))
    denom = 0.015 * esa_d
    ci = np.divide(m_price - esa, denom, out=np.zeros_like(m_price), where=denom != 0)
    out["wt1"] = _sfill(tl.EMA(ci, timeperiod=21))
    out["wt2"] = _sfill(tl.MA(out["wt1"], timeperiod=4))


def _compute_supertrend(data, out):
    """SuperTrend — 迭代实现。"""
    h = data["high"].values.astype(np.float64)
    l = data["low"].values.astype(np.float64)
    c = data["close"].values.astype(np.float64)
    atr = out["atr"]
    m_atr = atr * 3
    hl_avg = (h + l) / 2.0
    b_ub = hl_avg + m_atr
    b_lb = hl_avg - m_atr
    size = len(data)
    ub = np.empty(size, dtype=np.float64)
    lb = np.empty(size, dtype=np.float64)
    st = np.empty(size, dtype=np.float64)
    for i in range(size):
        if i == 0:
            ub[i] = b_ub[i]
            lb[i] = b_lb[i]
            st[i] = ub[i] if c[i] <= ub[i] else lb[i]
            continue
        last_close = c[i - 1]
        curr_close = c[i]
        last_ub = ub[i - 1]
        last_lb = lb[i - 1]
        last_st = st[i - 1]
        ub[i] = b_ub[i] if (b_ub[i] < last_ub or last_close > last_ub) else last_ub
        lb[i] = b_lb[i] if (b_lb[i] > last_lb or last_close < last_lb) else last_lb
        if last_st == last_ub:
            st[i] = ub[i] if curr_close <= ub[i] else lb[i]
        else:
            st[i] = lb[i] if curr_close > lb[i] else ub[i]
    out["supertrend"] = st
    out["supertrend_ub"] = ub
    out["supertrend_lb"] = lb


def _compute_roc(data, out):
    close = data["close"].values.astype(np.float64)
    roc = _sfill(tl.ROC(close, timeperiod=12))
    out["roc"] = roc
    out["rocma"] = _sfill(tl.MA(roc, timeperiod=6))
    out["rocema"] = _sfill(tl.EMA(roc, timeperiod=9))


def _compute_obv(data, out):
    c = data["close"].values.astype(np.float64)
    v = data["volume"].values.astype(np.float64)
    out["obv"] = _sfill(tl.OBV(c, v))


def _compute_sar(data, out):
    h = data["high"].values.astype(np.float64)
    l = data["low"].values.astype(np.float64)
    out["sar"] = _sfill(tl.SAR(h, l))


def _compute_psy(data, out):
    close = data["close"].values.astype(np.float64)
    pc = np.insert(close[:-1], 0, 0.0)
    up = (close > pc).astype(np.float64)
    up_sum = _sfill(tl.SUM(up, timeperiod=12))
    out["psy"] = _sfill(up_sum / 12.0 * 100)
    out["psyma"] = _sfill(tl.MA(out["psy"], timeperiod=6))


def _compute_brar(data, out):
    o = data["open"].values.astype(np.float64)
    h = data["high"].values.astype(np.float64)
    l = data["low"].values.astype(np.float64)
    c = data["close"].values.astype(np.float64)
    pc = np.insert(c[:-1], 0, 0.0)
    h_o = h - o
    o_l = o - l
    h_o_sum = _sfill(tl.SUM(h_o, timeperiod=26))
    o_l_sum = _sfill(tl.SUM(o_l, timeperiod=26))
    ar = np.divide(h_o_sum, o_l_sum, out=np.zeros_like(h_o_sum), where=o_l_sum != 0) * 100
    out["ar"] = _sfill(ar)
    h_pc = h - pc
    pc_l = pc - l
    h_cy_sum = _sfill(tl.SUM(h_pc, timeperiod=26))
    cy_l_sum = _sfill(tl.SUM(pc_l, timeperiod=26))
    br = np.divide(h_cy_sum, cy_l_sum, out=np.zeros_like(h_cy_sum), where=cy_l_sum != 0) * 100
    out["br"] = _sfill(br)


def _compute_emv(data, out):
    o = data["open"].values.astype(np.float64)
    h = data["high"].values.astype(np.float64)
    l = data["low"].values.astype(np.float64)
    c = data["close"].values.astype(np.float64)
    v = data["volume"].values.astype(np.float64)
    amt = data["amount"].values.astype(np.float64)
    ph = np.insert(h[:-1], 0, 0.0)
    pl = np.insert(l[:-1], 0, 0.0)
    hl_avg = (h + l) / 2.0
    phl_avg = (ph + pl) / 2.0
    h_l = h - l
    emva = np.divide((hl_avg - phl_avg) * h_l, amt, out=np.zeros_like(amt), where=amt != 0)
    emv = _sfill(tl.SUM(emva, timeperiod=14))
    out["emv"] = emv
    out["emva"] = _sfill(tl.MA(emv, timeperiod=9))


def _compute_bias(data, out):
    close = data["close"].values.astype(np.float64)
    for p, col in [(6, "bias"), (12, "bias_12"), (24, "bias_24")]:
        ma = tl.MA(close, timeperiod=p)
        bias = np.divide(close - ma, ma, out=np.zeros_like(close), where=ma != 0) * 100
        out[col] = _sfill(bias)


def _compute_dpo(data, out):
    close = data["close"].values.astype(np.float64)
    c_m_11 = _sfill(tl.MA(close, timeperiod=11))
    dpo = close - np.insert(c_m_11[:-1], 0, 0.0)
    out["dpo"] = _sfill(dpo)
    out["madpo"] = _sfill(tl.MA(dpo, timeperiod=6))


def _compute_vhf(data, out):
    close = data["close"].values.astype(np.float64)
    hcp = _sfill(tl.MAX(close, timeperiod=28))
    lcp = _sfill(tl.MIN(close, timeperiod=28))
    pc = np.insert(close[:-1], 0, 0.0)
    diff_sum = _sfill(tl.SUM(abs(close - pc), timeperiod=28))
    vhf = np.divide(hcp - lcp, diff_sum, out=np.zeros_like(hcp), where=diff_sum != 0)
    out["vhf"] = _sfill(vhf)


def _compute_rvi(data, out):
    o = data["open"].values.astype(np.float64)
    h = data["high"].values.astype(np.float64)
    l = data["low"].values.astype(np.float64)
    c = data["close"].values.astype(np.float64)
    # 辅助偏移数组
    def _shift(arr, n, fill=0.0):
        if n == 0:
            return arr
        return np.concatenate([np.full(n, fill), arr[:-n]])
    pc = _shift(c, 1)
    o1 = _shift(o, 1)
    c2 = _shift(c, 2)
    o2 = _shift(o, 2)
    c3 = _shift(c, 3)
    o3 = _shift(o, 3)
    rvi_x = ((c - o) + 2 * (pc - o1) + 2 * (c2 - o2) + (c3 - o3)) / 6
    ph = _shift(h, 1)
    pl = _shift(l, 1)
    h2 = _shift(h, 2)
    l2 = _shift(l, 2)
    h3 = _shift(h, 3)
    l3 = _shift(l, 3)
    rvi_y = ((h - l) + 2 * (ph - pl) + 2 * (h2 - l2) + (h3 - l3)) / 6
    y_ma = _sfill(tl.MA(rvi_y, timeperiod=10))
    rvi = np.divide(_sfill(tl.MA(rvi_x, timeperiod=10)), y_ma,
                     out=np.zeros_like(rvi_x), where=y_ma != 0)
    out["rvi"] = _sfill(rvi)
    out["rvis"] = (rvi + 2 * _shift(rvi, 1) + 2 * _shift(rvi, 2) + _shift(rvi, 3)) / 6


def _compute_fi(data, out):
    close = data["close"].values.astype(np.float64)
    vol = data["volume"].values.astype(np.float64)
    fi = np.insert(np.diff(close), 0, 0.0) * vol
    out["fi"] = fi
    out["force_2"] = _sfill(tl.EMA(fi, timeperiod=2))
    out["force_13"] = _sfill(tl.EMA(fi, timeperiod=13))


def _compute_ene(data, out):
    ma10 = out["ma10"]
    out["ene_ue"] = (1 + 11 / 100) * ma10
    out["ene_le"] = (1 - 9 / 100) * ma10
    out["ene"] = (out["ene_ue"] + out["ene_le"]) / 2


def _compute_vol_ma(data, out):
    vol = data["volume"].values.astype(np.float64)
    out["vol_5"] = _sfill(tl.MA(vol, timeperiod=5))
    out["vol_10"] = _sfill(tl.MA(vol, timeperiod=10))


def _compute_ma(data, out):
    close = data["close"].values.astype(np.float64)
    out["ma20"] = _sfill(tl.MA(close, timeperiod=20))
    out["ma200"] = _sfill(tl.MA(close, timeperiod=200))
