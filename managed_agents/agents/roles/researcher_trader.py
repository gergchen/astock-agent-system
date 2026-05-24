"""量化研究员 — 盘前扫描、盘中监控、交易信号生成."""

import json
import logging

from ..base import BaseAgent

logger = logging.getLogger(__name__)

RESEARCHER_PROMPT = """你是A股量化研究员，负责市场扫描和信号发现。你不执行交易。

## 数据源与字段说明

### 1. 同花顺热点 (ths_hotspot)
来源: zx.10jqka.com.cn 打板列表，收录当日涨停/大涨股票
返回字段: 代码, 名称, 题材归因(同花顺编辑标注的概念标签), date, 市场
⚠️ 该数据源没有涨幅%、换手率、成交额、大单净量等字段
⚠️ 包含大量ST/*ST股票，需自行过滤
⚠️ 题材归因是编辑标注的热点概念标签，非官方行业分类，可能存在蹭热点

### 2. 北向资金 (northbound)
来源: data.hexin.cn 实时沪深港通数据
返回字段: time(分钟), hgt_yi(沪股通累计净买入_亿), sgt_yi(深股通累计净买入_亿)
单位: 亿元。09:10开始有数据，包含集合竞价时段

### 3. 实时行情 (tencent_finance)
来源: qt.gtimg.cn 腾讯财经
返回字段: name, price, change_pct(涨幅%), change_amt, high, low, vol_ratio(量比)
⚠️ 午休时段(11:30-13:00)数据为静态值

### 4. 财联社快讯 (cls_news)
来源: akshare → 财联社
返回字段: title, content, datetime(分钟级)
⚠️ 每条快讯可能只是标题，正文可能为空

### 5. 指数行情 (sentinel)
来源: 腾讯财经
支持指数: 000001(上证), 399001(深成指), 399006(创业板指), 000688(科创50), 000300(沪深300)

### 6. 技术分析 (TA-Lib)
通过 get_full_technical_analysis(symbol) 一键获取:
- 32种技术指标最新值: MACD, KDJ, RSI, CCI, BOLL, OBV, SAR, DMI, WR, VR 等
- 指标买卖信号: 基于阈值判断超买/超卖（如RSI>80为超买，<30为超卖）
- 61种K线形态: 锤头、吞没、晨星、暮星、十字星等（正值=买入，负值=卖出）
- 筹码分布: 平均成本、获利盘比例、集中度
支持个股代码查询: get_full_technical_analysis("600519")

## 数据使用规则
1. 同花顺热点 → 仅用于识别今日活跃板块，涨停股数不代表板块可操作性
2. 实时行情 → 用于判断个股是否已封涨停（涨幅≥9.5%为涨停），3-8%为可操作区间
3. 北向资金 → 大盘资金方向参考，单分钟数据波动大，看趋势而非绝对值
4. ST股票涨幅上限5%，不应与主板股票混合计算板块强度
5. 创业板(300xxx)/科创板(688xxx)涨停上限20%，注意与主板的10%区别

## 信号输出规则
- 信号必须有明确的置信度和理由
- 注明数据来源和时效
- 同一板块30分钟内不重复发信号
- 开盘前30分钟和收盘前15分钟减少信号密度
"""


class ResearcherTrader(BaseAgent):
    """量化研究员 Agent."""

    def __init__(self):
        from astock_trade.skills.market_monitor import scan_now, scan_hotspots, scan_hotspots_detail, scan_northbound, get_quotes
        from astock_trade.skills.signal_generator import generate_signals, generate_early_signals, generate_single_signal, publish_signal
        from astock_trade.skills.morning_scan import premarket_scan
        from astock_trade.skills.technical_analysis import TechnicalAnalysisSkills

        self._scan_now = scan_now
        self._scan_hotspots = scan_hotspots
        self._scan_hotspots_detail = scan_hotspots_detail
        self._scan_northbound = scan_northbound
        self._get_quotes = get_quotes
        self._generate_signals = generate_signals
        self._generate_early_signals = generate_early_signals
        self._generate_single_signal = generate_single_signal
        self._publish_signal = publish_signal
        self._premarket_scan = premarket_scan
        self._ta = TechnicalAnalysisSkills()

        super().__init__(name="researcher-trader", role="量化研究员")

    def system_prompt(self) -> str:
        return RESEARCHER_PROMPT

    def _validate_hot_stocks(self, stocks: list[dict]) -> list[dict]:
        """Validate and filter hot stocks data.

        - Removes ST/*ST stocks
        - Checks for required fields
        - Logs warnings for unusual data patterns
        """
        if not stocks:
            return []

        valid = []
        st_count = 0
        for s in stocks:
            name = s.get("名称", "")
            code = s.get("代码", "")
            tags = s.get("题材归因", "")

            # ST filter
            if name.startswith(("*ST", "ST")):
                st_count += 1
                continue

            # Must have code and at least one sector tag
            if not code or not tags:
                continue

            valid.append(s)

        if st_count > 0:
            logger.info(f"热点数据过滤: {st_count}只ST股票已跳过")
        return valid

    def _register_skills(self):
        # 数据验证包装: 在调用原始函数之前先做数据检查
        def _wrapped_scan_hotspots():
            data = self._scan_hotspots()
            if not data:
                logger.warning("scan_hotspots返回空数据")
            return data

        def _wrapped_scan_hotspots_detail():
            data = self._scan_hotspots_detail()
            if not data:
                logger.warning("scan_hotspots_detail返回空数据")
            return data

        def _wrapped_scan_northbound():
            data = self._scan_northbound()
            if not data:
                logger.warning("北向资金数据为空，可能非交易时段")
            elif len(data) < 5:
                logger.warning(f"北向资金数据不足5条(当前{len(data)}条)，趋势判断可能不准")
            return data

        self._skills.update({
            "scan_now": lambda: self._scan_now(),
            "scan_hotspots": _wrapped_scan_hotspots,
            "scan_hotspots_detail": _wrapped_scan_hotspots_detail,
            "scan_northbound": _wrapped_scan_northbound,
            "get_quotes": lambda symbols: self._get_quotes(symbols),
            "generate_signals": lambda h, n: self._generate_signals(h, n),
            "generate_early_signals": lambda stocks, nb: self._generate_early_signals(stocks, nb),
            "generate_single_signal": lambda **kw: self._generate_single_signal(**kw),
            "publish_signal": lambda s: str(self._publish_signal(s)),
            "premarket_scan": lambda: self._premarket_scan(),
            # 技术分析技能
            "get_technical_indicators": lambda symbol: self._ta.get_technical_indicators(symbol),
            "get_kline_patterns": lambda symbol: self._ta.get_kline_patterns(symbol),
            "get_pattern_signals": lambda symbol: self._ta.get_pattern_signals(symbol),
            "get_technical_signals": lambda symbol: self._ta.get_technical_signals(symbol),
            "get_chip_distribution": lambda symbol: self._ta.get_chip_distribution(symbol),
            "get_full_technical_analysis": lambda symbol: self._ta.get_full_technical_analysis(symbol),
        })

    def scan_and_generate(self, symbols: list[str] | None = None) -> dict:
        """执行一次完整的扫描+信号生成.

        同时生成两类信号:
        - signals:    原板块动量信号（已有涨停股，保留向后兼容）
        - early_signals: 早期机会信号（尚未封板的个股，可操作）

        Returns:
            {"signals": [...], "early_signals": [...], "scan": {...}}
        """
        try:
            scan = self._scan_now()
            hotspots = scan.get("hotspots", [])
            northbound_raw = self._scan_northbound()

            # 原板块级信号（向后兼容）
            signals = self._generate_signals(hotspots, northbound_raw)

            # 早期机会信号: 先取热点列表，过滤ST，再查实时涨幅
            hot_stocks = self._scan_hotspots_detail()
            hot_stocks = self._validate_hot_stocks(hot_stocks)
            if not hot_stocks:
                logger.info("热点数据为空或全部为ST股，跳过早期信号生成")
                early_signals = []
            else:
                early_signals = self._generate_early_signals(hot_stocks, northbound_raw)
        except Exception as e:
            logger.error(f"扫描信号失败: {e}")
            return {"error": str(e), "signals": [], "early_signals": []}

        for sig in signals:
            try:
                self._publish_signal(sig)
            except Exception as e:
                logger.error(f"发布信号失败: {e}")

        return {
            "signals": signals,
            "early_signals": early_signals,
            "scan": scan,
            "signal_count": len(signals),
            "early_count": len(early_signals),
        }
