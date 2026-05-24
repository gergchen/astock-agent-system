# 61种K线形态识别
# 移植自 InStock (myhhub/stock)，基于 TA-Lib CDL* 函数族

import logging
import numpy as np
import pandas as pd
import talib as tl

logger = logging.getLogger(__name__)

# ── 61种K线形态定义 ──────────────────────────
# {字段名: {name_cn: 中文名, func: TA-Lib函数}}
# 正=买入信号, 0=无信号, 负=卖出信号

STOCK_KLINE_PATTERNS = {
    "tow_crows": {"name_cn": "两只乌鸦", "func": tl.CDL2CROWS},
    "upside_gap_two_crows": {"name_cn": "向上跳空的两只乌鸦", "func": tl.CDLUPSIDEGAP2CROWS},
    "three_black_crows": {"name_cn": "三只乌鸦", "func": tl.CDL3BLACKCROWS},
    "identical_three_crows": {"name_cn": "三胞胎乌鸦", "func": tl.CDLIDENTICAL3CROWS},
    "three_line_strike": {"name_cn": "三线打击", "func": tl.CDL3LINESTRIKE},
    "dark_cloud_cover": {"name_cn": "乌云压顶", "func": tl.CDLDARKCLOUDCOVER},
    "evening_doji_star": {"name_cn": "十字暮星", "func": tl.CDLEVENINGDOJISTAR},
    "doji_star": {"name_cn": "十字星", "func": tl.CDLDOJISTAR},
    "hanging_man": {"name_cn": "上吊线", "func": tl.CDLHANGINGMAN},
    "hikkake_pattern": {"name_cn": "陷阱", "func": tl.CDLHIKKAKE},
    "modified_hikkake": {"name_cn": "修正陷阱", "func": tl.CDLHIKKAKEMOD},
    "in_neck": {"name_cn": "颈内线", "func": tl.CDLINNECK},
    "on_neck": {"name_cn": "颈上线", "func": tl.CDLONNECK},
    "thrusting": {"name_cn": "插入", "func": tl.CDLTHRUSTING},
    "shooting_star": {"name_cn": "射击之星", "func": tl.CDLSHOOTINGSTAR},
    "stalled": {"name_cn": "停顿形态", "func": tl.CDLSTALLEDPATTERN},
    "advance_block": {"name_cn": "大敌当前", "func": tl.CDLADVANCEBLOCK},
    "high_wave": {"name_cn": "风高浪大线", "func": tl.CDLHIGHWAVE},
    "engulfing": {"name_cn": "吞噬模式", "func": tl.CDLENGULFING},
    "abandoned_baby": {"name_cn": "弃婴", "func": tl.CDLABANDONEDBABY},
    "closing_marubozu": {"name_cn": "收盘缺影线", "func": tl.CDLCLOSINGMARUBOZU},
    "doji": {"name_cn": "十字", "func": tl.CDLDOJI},
    "up_down_gap": {"name_cn": "向上/下跳空并列阳线", "func": tl.CDLGAPSIDESIDEWHITE},
    "long_legged_doji": {"name_cn": "长脚十字", "func": tl.CDLLONGLEGGEDDOJI},
    "rickshaw_man": {"name_cn": "黄包车夫", "func": tl.CDLRICKSHAWMAN},
    "marubozu": {"name_cn": "光头光脚/缺影线", "func": tl.CDLMARUBOZU},
    "three_inside": {"name_cn": "三内部上涨和下跌", "func": tl.CDL3INSIDE},
    "three_outside": {"name_cn": "三外部上涨和下跌", "func": tl.CDL3OUTSIDE},
    "three_stars_south": {"name_cn": "南方三星", "func": tl.CDL3STARSINSOUTH},
    "three_white_soldiers": {"name_cn": "三个白兵", "func": tl.CDL3WHITESOLDIERS},
    "belt_hold": {"name_cn": "捉腰带线", "func": tl.CDLBELTHOLD},
    "breakaway": {"name_cn": "脱离", "func": tl.CDLBREAKAWAY},
    "concealing_baby": {"name_cn": "藏婴吞没", "func": tl.CDLCONCEALBABYSWALL},
    "counterattack": {"name_cn": "反击线", "func": tl.CDLCOUNTERATTACK},
    "dragonfly_doji": {"name_cn": "蜻蜓十字/T形十字", "func": tl.CDLDRAGONFLYDOJI},
    "evening_star": {"name_cn": "暮星", "func": tl.CDLEVENINGSTAR},
    "gravestone_doji": {"name_cn": "墓碑十字/倒T十字", "func": tl.CDLGRAVESTONEDOJI},
    "hammer": {"name_cn": "锤头", "func": tl.CDLHAMMER},
    "harami": {"name_cn": "母子线", "func": tl.CDLHARAMI},
    "harami_cross": {"name_cn": "十字孕线", "func": tl.CDLHARAMICROSS},
    "homing_pigeon": {"name_cn": "家鸽", "func": tl.CDLHOMINGPIGEON},
    "inverted_hammer": {"name_cn": "倒锤头", "func": tl.CDLINVERTEDHAMMER},
    "kicking": {"name_cn": "反冲形态", "func": tl.CDLKICKING},
    "kicking_length": {"name_cn": "由较长缺影线决定的反冲形态", "func": tl.CDLKICKINGBYLENGTH},
    "ladder_bottom": {"name_cn": "梯底", "func": tl.CDLLADDERBOTTOM},
    "long_line": {"name_cn": "长蜡烛", "func": tl.CDLLONGLINE},
    "matching_low": {"name_cn": "相同低价", "func": tl.CDLMATCHINGLOW},
    "mat_hold": {"name_cn": "铺垫", "func": tl.CDLMATHOLD},
    "morning_doji_star": {"name_cn": "十字晨星", "func": tl.CDLMORNINGDOJISTAR},
    "morning_star": {"name_cn": "晨星", "func": tl.CDLMORNINGSTAR},
    "piercing": {"name_cn": "刺透形态", "func": tl.CDLPIERCING},
    "rising_falling_three": {"name_cn": "上升/下降三法", "func": tl.CDLRISEFALL3METHODS},
    "separating_lines": {"name_cn": "分离线", "func": tl.CDLSEPARATINGLINES},
    "short_line": {"name_cn": "短蜡烛", "func": tl.CDLSHORTLINE},
    "spinning_top": {"name_cn": "纺锤", "func": tl.CDLSPINNINGTOP},
    "stick_sandwich": {"name_cn": "条形三明治", "func": tl.CDLSTICKSANDWICH},
    "takuri": {"name_cn": "探水竿", "func": tl.CDLTAKURI},
    "tasuki_gap": {"name_cn": "跳空并列阴阳线", "func": tl.CDLTASUKIGAP},
    "tristar": {"name_cn": "三星", "func": tl.CDLTRISTAR},
    "unique_3_river": {"name_cn": "奇特三河床", "func": tl.CDLUNIQUE3RIVER},
    "upside_downside_gap": {"name_cn": "上升/下降跳空三法", "func": tl.CDLXSIDEGAP3METHODS},
}

# 所有TA-Lib CDL函数的统一调用签名: func(open, high, low, close)


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """统一列名。"""
    aliases = {"datetime": "date", "vol": "volume"}
    renamed = {c: aliases[c.lower().strip()] for c in df.columns
               if c.lower().strip() in aliases}
    if renamed:
        df = df.rename(columns=renamed)
    return df


def compute_patterns(
    data: pd.DataFrame,
    end_date: str | None = None,
    threshold: int | None = 120,
    calc_threshold: int | None = None,
) -> pd.DataFrame | None:
    """识别61种K线形态，返回添加了形态列的 DataFrame。

    Args:
        data: 包含 open/close/high/low 列的OHLCV数据。
        end_date: 可选日期过滤。
        threshold: 返回最近 N 行。
        calc_threshold: 计算窗口限制。

    Returns:
        添加了形态列的 DataFrame（列值: -100/0/100）。
    """
    try:
        data = _normalize_columns(data)
        is_copy = False
        if end_date is not None and "date" in data.columns:
            data = data.loc[data["date"] <= end_date]
            is_copy = True
        if calc_threshold is not None:
            data = data.tail(n=calc_threshold)
            is_copy = True
        if is_copy:
            data = data.copy()

        for key, pat in STOCK_KLINE_PATTERNS.items():
            try:
                data[key] = pat["func"](
                    data["open"].values, data["high"].values,
                    data["low"].values, data["close"].values)
            except Exception:
                data[key] = 0

        if threshold is not None:
            data = data.tail(n=threshold).copy()
        return data

    except Exception as e:
        logger.error(f"compute_patterns 异常: {e}")
        return None


def get_latest_patterns(data: pd.DataFrame, calc_threshold: int = 12) -> dict:
    """返回最后一行所有形态识别结果。

    Returns:
        {字段名: 值}，值 -100/0/100。
    """
    result = compute_patterns(data, threshold=1, calc_threshold=calc_threshold)
    if result is None or len(result) == 0:
        return {}
    row = result.iloc[0]
    base_cols = {"date", "code", "open", "close", "high", "low", "volume", "amount"}
    return {
        col: int(row[col]) for col in STOCK_KLINE_PATTERNS
        if col in result.columns
    }


def get_pattern_buy_signals(data: pd.DataFrame, calc_threshold: int = 12) -> list[dict]:
    """返回出现买入信号（正值）的形态列表。"""
    patterns = get_latest_patterns(data, calc_threshold)
    signals = []
    for key, val in patterns.items():
        if val > 0 and key in STOCK_KLINE_PATTERNS:
            signals.append({
                "field": key,
                "name_cn": STOCK_KLINE_PATTERNS[key]["name_cn"],
                "signal": "buy",
                "value": val,
            })
    return signals


def get_pattern_sell_signals(data: pd.DataFrame, calc_threshold: int = 12) -> list[dict]:
    """返回出现卖出信号（负值）的形态列表。"""
    patterns = get_latest_patterns(data, calc_threshold)
    signals = []
    for key, val in patterns.items():
        if val < 0 and key in STOCK_KLINE_PATTERNS:
            signals.append({
                "field": key,
                "name_cn": STOCK_KLINE_PATTERNS[key]["name_cn"],
                "signal": "sell",
                "value": int(val),
            })
    return signals
