# astock_data.ta — 技术分析模块
# 移植自 myhhub/stock (InStock)，提供 TA-Lib 技术指标计算、
# K线形态识别、筹码分布分析等功能

from astock_data.ta.indicators import compute_indicators, get_latest_indicators
from astock_data.ta.patterns import (
    compute_patterns, get_latest_patterns,
    get_pattern_buy_signals, get_pattern_sell_signals,
)
from astock_data.ta.signals import get_buy_signals, get_sell_signals, get_technical_signals
from astock_data.ta.cyq import compute_chip_distribution

__version__ = "0.1.0"
