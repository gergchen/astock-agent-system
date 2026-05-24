# 筹码分布 (CYQ) 计算
# 移植自 InStock (myhhub/stock)

import logging
import numpy as np
import pandas as pd

from astock_data.ta.config import CYQ_ACCURACY_FACTOR, CYQ_RANGE, CYQ_DAYS

logger = logging.getLogger(__name__)


def compute_chip_distribution(
    kdata: pd.DataFrame,
    index: int = -1,
    accuracy_factor: int = CYQ_ACCURACY_FACTOR,
    crange: int = CYQ_RANGE,
    cyq_days: int = CYQ_DAYS,
) -> dict | None:
    """计算筹码分布 (CYQ)。

    Args:
        kdata: 包含 open/close/high/low/volume/amount/turnover 列的OHLCV数据，
               按时间升序排列。
        index: 当前K线索引（默认 -1 即最后一行）。
        accuracy_factor: 精度因子（纵轴刻度数），默认 150。
        crange: 计算K线条数，默认 120。
        cyq_days: 筹码分布交易天数窗口，默认 210。

    Returns:
        {x, y, benefit_part, avg_cost, percent_chips, b, d, t}
        - x: 筹码堆叠数组（每个价格水平的累积股份）
        - y: 价格水平数组
        - benefit_part: 获利盘比例 (0~1)
        - avg_cost: 平均成本价
        - percent_chips: {90: {priceRange, concentration}, 70: {...}}
        - b: 盈亏分界下标
        - d: 交易日期
        - t: 使用的交易天数
    """
    try:
        # 列名归一化
        col_map = {"datetime": "date", "vol": "volume"}
        aliases = {}
        for c in kdata.columns:
            cl = c.lower().strip()
            if cl in col_map:
                aliases[c] = col_map[cl]
        if aliases:
            kdata = kdata.rename(columns=aliases)

        # 检查必要列
        required = {"open", "close", "high", "low", "turnover"}
        if "turnover" not in kdata.columns and "turnoverrate" in kdata.columns:
            kdata = kdata.rename(columns={"turnoverrate": "turnover"})
        missing = required - set(kdata.columns)
        if missing:
            logger.error(f"CYQ 缺少必要列: {missing}")
            return None

        if index == -1:
            index = len(kdata)

        # 切片数据
        end = index - crange + 1
        start = end - cyq_days
        if end <= 0:
            kdata_slice = kdata.tail(cyq_days).copy()
        else:
            kdata_slice = kdata.iloc[start:end].copy()

        if len(kdata_slice) < 2:
            logger.warning("CYQ 数据不足")
            return None

        # 计算价格区间
        maxprice = float(kdata_slice["high"].max())
        minprice = float(kdata_slice["low"].min())
        accuracy = max(0.01, (maxprice - minprice) / (accuracy_factor - 1))
        current_price = float(kdata_slice.iloc[-1]["close"])

        # 价格数组
        yrange = [round(minprice + accuracy * i, 2) for i in range(accuracy_factor)]

        # 找到盈亏分界
        boundary = -1
        for i, p in enumerate(yrange):
            if boundary == -1 and p >= current_price:
                boundary = i
                break

        # 筹码堆叠
        xdata = np.zeros(accuracy_factor, dtype=np.float64)

        for i in range(len(kdata_slice)):
            row = kdata_slice.iloc[i]
            o, c, h, l = float(row["open"]), float(row["close"]), float(row["high"]), float(row["low"])
            turnover_rate = min(1.0, float(row["turnover"]) / 100.0)
            avg = (o + c + h + l) / 4.0

            H = int((h - minprice) / accuracy)
            L = int((l - minprice) / accuracy + 0.99)
            # G点坐标
            if abs(h - l) < 1e-8:
                gpoint_val = accuracy_factor - 1
            else:
                gpoint_val = 2.0 / (h - l)
            gpoint_idx = int((avg - minprice) / accuracy)

            # 筹码衰减
            xdata *= (1 - turnover_rate)

            if abs(h - l) < 1e-8:
                # 一字板，矩形面积 = 三角形2倍
                xdata[gpoint_idx] += gpoint_val * turnover_rate / 2.0
            else:
                for j in range(L, min(H + 1, accuracy_factor)):
                    cur_price = minprice + accuracy * j
                    if cur_price <= avg:  # 上半三角
                        if abs(avg - l) < 1e-8:
                            xdata[j] += gpoint_val * turnover_rate
                        else:
                            xdata[j] += (cur_price - l) / (avg - l) * gpoint_val * turnover_rate
                    else:  # 下半三角
                        if abs(h - avg) < 1e-8:
                            xdata[j] += gpoint_val * turnover_rate
                        else:
                            xdata[j] += (h - cur_price) / (h - avg) * gpoint_val * turnover_rate

        total_chips = sum(float(f"{v:.12g}") for v in xdata)

        # 辅助：获取指定筹码处的成本
        def get_cost_by_chip(chip: float) -> float:
            cum = 0.0
            for i in range(accuracy_factor):
                v = float(f"{xdata[i]:.12g}")
                if cum + v > chip:
                    return minprice + i * accuracy
                cum += v
            return minprice + (accuracy_factor - 1) * accuracy

        # 辅助：计算指定百分比的筹码
        def compute_percent_chips(percent: float) -> dict:
            ps_low = (1 - percent) / 2
            ps_high = (1 + percent) / 2
            p0 = get_cost_by_chip(total_chips * ps_low)
            p1 = get_cost_by_chip(total_chips * ps_high)
            return {
                "priceRange": [f"{p0:.2f}", f"{p1:.2f}"],
                "concentration": 0.0 if abs(p0 + p1) < 1e-8 else (p1 - p0) / (p0 + p1),
            }

        # 辅助：获利比例
        def get_benefit_part(price: float) -> float:
            below = 0.0
            for i in range(accuracy_factor):
                v = float(f"{xdata[i]:.12g}")
                if price >= minprice + i * accuracy:
                    below += v
            return 0.0 if total_chips == 0 else below / total_chips

        avg_cost = get_cost_by_chip(total_chips * 0.5)
        benefit_part = get_benefit_part(current_price)

        result = {
            "x": [float(f"{v:.12g}") for v in xdata],
            "y": yrange,
            "benefit_part": round(benefit_part, 4),
            "avg_cost": f"{avg_cost:.2f}",
            "percent_chips": {
                "90": compute_percent_chips(0.9),
                "70": compute_percent_chips(0.7),
            },
            "b": boundary + 1 if boundary >= 0 else 0,
            "d": str(kdata_slice.iloc[-1].get("date", "")),
            "t": cyq_days,
        }
        return result

    except Exception as e:
        logger.error(f"compute_chip_distribution 异常: {e}")
        return None
