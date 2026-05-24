# 技术分析模块配置

# 指标计算参数
INDICATOR_DEFAULT_THRESHOLD = 120     # 返回最近N行数据
INDICATOR_CALC_THRESHOLD = None       # 计算窗口限制（None=全部）

# K线形态参数
PATTERN_THRESHOLD = 120               # 返回最近N行数据
PATTERN_CALC_THRESHOLD = 12           # 计算窗口（最近N根K线）

# CYQ筹码分布参数
CYQ_ACCURACY_FACTOR = 150             # 精度因子（纵轴刻度数）
CYQ_RANGE = 120                       # 计算K线条数
CYQ_DAYS = 210                        # 计算筹码分布的交易天数

# 买入信号阈值
BUY_SIGNALS = {
    "KDJ_K": {"op": ">=", "value": 80},
    "KDJ_D": {"op": ">=", "value": 70},
    "KDJ_J": {"op": ">=", "value": 100},
    "RSI_6": {"op": ">=", "value": 80},
    "CCI": {"op": ">=", "value": 100},
    "CR": {"op": ">=", "value": 300},
    "WR_6": {"op": ">=", "value": -20},
    "VR": {"op": ">=", "value": 160},
}

# 卖出信号阈值
SELL_SIGNALS = {
    "KDJ_K": {"op": "<", "value": 20},
    "KDJ_D": {"op": "<", "value": 30},
    "KDJ_J": {"op": "<", "value": 10},
    "RSI_6": {"op": "<", "value": 20},
    "CCI": {"op": "<", "value": -100},
    "CR": {"op": "<", "value": 40},
    "WR_6": {"op": "<", "value": -80},
    "VR": {"op": "<", "value": 40},
}
