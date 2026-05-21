"""哨兵 Sentinel — 实时盯盘，异动秒级预警.

职责:
- 交易时段内每 N 秒扫描一次市场（大盘指数、北向资金、快讯）
- 检测到异动立即推送预警到微信
- 大盘砸盘（最高优先级，不受冷却限制）
- 北向资金大幅流入/流出
- 财联社突发重大快讯（仅保留真正突发事件）
"""

import logging
import time
from datetime import datetime

from ..base import BaseAgent
from ...skills.market_skills import MarketSkills

logger = logging.getLogger(__name__)

SENTINEL_PROMPT = """你是一个A股市场哨兵，负责实时盯盘和异动预警。

## 你的职责
1. 每120秒扫描一次市场数据（大盘指数、北向资金、快讯）
2. 发现异动立即生成简洁预警报告（≤200字）
3. 判断异动严重程度：🟢普通 🟡关注 🔴紧急

## 注意
- 大盘砸盘预警优先于一切
- 语言简洁，直接给结论
"""

# 快讯关键词 — 只保留真正的突发事件
BREAKING_KW = ["突发", "紧急", "暴涨", "暴跌", "熔断", "停牌", "黑天鹅", "债务违约"]

# 大盘指数监控配置
MONITORED_INDICES = ["000001", "399001", "399006", "000688", "000300"]
INDEX_NAMES = {
    "000001": "上证指数", "399001": "深证成指",
    "399006": "创业板指", "000688": "科创50",
    "000300": "沪深300",
}
# 跌幅阈值： (阈值%, 告警级别)
INDEX_THRESHOLDS = [
    (3.0, "紧急"),   # 跌超 3% → 紧急
    (2.0, "关注"),   # 跌超 2% → 关注
    (1.5, "关注"),   # 跌超 1.5% → 关注（仅上证）
]

# 冷却时间（秒）
GLOBAL_COOLDOWN = 300     # 普通告警：5分钟内最多发一批
INDEX_COOLDOWN = 600      # 大盘告警：10分钟内不重复


class Sentinel(BaseAgent):
    """市场哨兵 Agent."""

    def __init__(self):
        self.skills_api = MarketSkills()
        super().__init__(name="sentinel", role="哨兵")
        self._last_northbound: float | None = None
        self._alerted_news: set = set()
        self._alerted_nb_direction: str = ""
        self._last_alert_time: float = 0            # 上次普通告警时间戳
        self._index_alert_level: dict[str, str] = {}    # 指数 -> 已告警的最高级别
        self._last_index_alert_time: float = 0          # 上次指数告警时间戳

    @staticmethod
    def _is_trading_time() -> bool:
        """判断当前是否在A股交易时段（9:25-15:00，周一至周五）。"""
        now = datetime.now()
        if now.weekday() >= 5:
            return False
        t = now.hour * 60 + now.minute
        return (9 * 60 + 25) <= t <= (15 * 60)

    def system_prompt(self) -> str:
        return SENTINEL_PROMPT

    def _register_skills(self):
        self._skills.update({
            "get_northbound": self.skills_api.get_northbound,
            "get_flash_news": self.skills_api.get_flash_news,
            "get_index_quotes": self.skills_api.get_index_quotes,
        })

    def scan(self) -> dict:
        """执行一次市场扫描，返回异动报告。非交易时段直接返回空。"""
        now = datetime.now().strftime("%H:%M:%S")

        if not self._is_trading_time():
            return {"time": now, "alerts": [], "hotspot_top3": [], "northbound": {}}

        priority_alerts = []  # 大盘异动 — 必推，不受冷却限制
        normal_alerts = []    # 其他告警
        current_hour = datetime.now().hour
        now_min = datetime.now().minute
        is_market_open = (current_hour == 9 and now_min >= 30) or (10 <= current_hour < 15)

        # 1. 扫描大盘指数（最高优先级 — 砸盘必须推送）
        if is_market_open:
            try:
                index_data = self.skills_api.get_index_quotes(MONITORED_INDICES)
                priority_alerts += self._check_market_index(index_data)
            except Exception as e:
                logger.error(f"指数扫描失败: {e}")

            # 2. 扫描北向资金（比热点重要）
            try:
                nb = self.skills_api.get_northbound()
                normal_alerts += self._check_northbound_alert(nb)
                self._last_northbound = nb.get("total", 0)
            except Exception as e:
                logger.error(f"北向扫描失败: {e}")

        # 3. 扫描快讯
        try:
            news = self.skills_api.get_flash_news(limit=5)
            normal_alerts += self._check_breaking_news(news)
        except Exception as e:
            logger.error(f"快讯扫描失败: {e}")

        # 全局冷却：只有普通告警受冷却限制，大盘异动不受限
        now_ts = time.time()
        if normal_alerts and self._last_alert_time > 0:
            if now_ts - self._last_alert_time < GLOBAL_COOLDOWN:
                normal_alerts = []
        if normal_alerts:
            self._last_alert_time = now_ts

        alerts = priority_alerts + normal_alerts

        return {
            "time": now,
            "alerts": alerts,
            "hotspot_top3": [],
            "northbound": nb if 'nb' in dir() else {},
        }

    def _check_market_index(self, index_data: dict) -> list[dict]:
        """检查大盘指数跌幅，达到阈值时告警。同一指数同一级别不重复告警。"""
        alerts = []
        now_ts = time.time()

        # 距上次指数告警不足冷却期，跳过
        if now_ts - self._last_index_alert_time < INDEX_COOLDOWN:
            return alerts

        for code, data in index_data.items():
            name = INDEX_NAMES.get(code, data.get("name", code))
            change_pct = data.get("change_pct", 0)

            if change_pct >= 0:
                continue  # 上涨或平盘不告警

            abs_drop = abs(change_pct)

            # 确定当前应告警的级别
            current_level = None
            if abs_drop >= 3.0:
                current_level = "紧急"
            elif abs_drop >= 2.0:
                current_level = "关注"
            elif abs_drop >= 1.5 and code == "000001":
                current_level = "关注"
            else:
                continue  # 跌幅不足阈值

            # 同一指数已经告警过同等或更高级别，不再重复
            prev_level = self._index_alert_level.get(code, "")
            level_rank = {"紧急": 3, "关注": 2, "普通": 1}
            if prev_level and level_rank.get(current_level, 0) <= level_rank.get(prev_level, 0):
                continue

            self._index_alert_level[code] = current_level
            alerts.append({
                "level": current_level,
                "title": f"{'🔴' if current_level == '紧急' else '🟡'} 大盘跳水: {name} {change_pct:.1f}%",
                "detail": f"当前 {data['price']:.0f}  昨收 {data['last_close']:.0f}  日内 {data['low']:.0f}~{data['high']:.0f}",
            })

        if alerts:
            self._last_index_alert_time = now_ts

        return alerts

    def _check_northbound_alert(self, nb: dict) -> list[dict]:
        alerts = []
        total = nb.get("total", 0)

        if self._last_northbound is not None:
            delta = total - self._last_northbound
            if abs(delta) >= 20:
                direction = "流入" if delta > 0 else "流出"
                if direction != self._alerted_nb_direction:
                    self._alerted_nb_direction = direction
                    alerts.append({
                        "level": "紧急" if abs(delta) >= 30 else "关注",
                        "title": f"北向资金快速{direction}: {delta:+.1f}亿",
                        "detail": f"累计: {total:+.1f}亿",
                    })

        if total <= -50 and self._alerted_nb_direction != "流出":
            self._alerted_nb_direction = "流出"
            alerts.append({
                "level": "紧急",
                "title": f"北向大幅流出: {total:.1f}亿",
                "detail": "外资恐慌，全市场承压",
            })
        elif total >= 50 and self._alerted_nb_direction != "流入":
            self._alerted_nb_direction = "流入"
            alerts.append({
                "level": "紧急",
                "title": f"北向大幅流入: {total:.1f}亿",
                "detail": "外资抢筹，市场情绪回暖",
            })

        return alerts

    def _check_breaking_news(self, news: dict) -> list[dict]:
        alerts = []
        for item in news.get("news", []):
            title = item.get("title", "")
            if title in self._alerted_news:
                continue
            text = title + item.get("content", "")
            for kw in BREAKING_KW:
                if kw in text:
                    self._alerted_news.add(title)
                    alerts.append({
                        "level": "紧急" if kw in ["突发", "紧急", "暴涨", "暴跌"] else "关注",
                        "title": f"快讯预警: {title[:50]}",
                        "detail": item.get("content", "")[:100],
                    })
                    break
        return alerts
