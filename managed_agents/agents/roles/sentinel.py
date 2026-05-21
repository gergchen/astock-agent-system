"""哨兵 Sentinel — 实时盯盘，异动秒级预警.

职责:
- 交易时段内每 N 秒扫描一次市场（热点变化、北向资金、快讯）
- 检测到异动立即推送预警到微信
- 盘后自动静默，不发送任何消息

触发条件:
- 题材排名大幅变化（新题材进入TOP3 或 昨日TOP3消失），5分钟内不重复
- 北向资金5分钟内大幅流入/流出
- 财联社突发重大快讯（仅保留真正突发事件）
"""

import logging
import time
from datetime import datetime

from ..base import BaseAgent
from ...skills.market_skills import MarketSkills
from ...sessions.session_store import SessionStore

logger = logging.getLogger(__name__)

SENTINEL_PROMPT = """你是一个A股市场哨兵，负责实时盯盘和异动预警。

## 你的职责
1. 每120秒扫描一次市场数据（热点、北向资金、快讯）
2. 发现异动立即生成简洁预警报告（≤200字）
3. 判断异动严重程度：🟢普通 🟡关注 🔴紧急

## 输出格式
```
[时间] [严重程度] 异动标题
- 关键数据
- 建议关注方向
```

## 注意
- 只报告异常变化，不重复已知信息
- 优先报告北向资金方向变化和题材突变
- 语言简洁，直接给结论
"""

# 快讯关键词 — 只保留真正的突发事件
BREAKING_KW = ["突发", "紧急", "暴涨", "暴跌", "熔断", "停牌", "黑天鹅", "债务违约"]

# 冷却时间（秒）
HOTSPOT_COOLDOWN = 600    # 热点 TOP3 变化：10分钟内不重复
GLOBAL_COOLDOWN = 300     # 全局告警：5分钟内最多发一批


class Sentinel(BaseAgent):
    """市场哨兵 Agent."""

    def __init__(self):
        self.skills_api = MarketSkills()
        self._store = SessionStore()
        super().__init__(name="sentinel", role="哨兵")
        self._last_hotspots: dict | None = None
        self._last_northbound: float | None = None
        self._alerted_burst: set = set()
        self._alerted_news: set = set()
        self._alerted_nb_direction: str = ""
        self._last_alert_time: float = 0            # 上次告警时间戳
        self._hotspot_cooldowns: dict[str, float] = {}  # 题材名 -> 上次告警时间

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
            "get_hotspots": self.skills_api.get_sector_hotspots,
            "get_northbound": self.skills_api.get_northbound,
            "get_flash_news": self.skills_api.get_flash_news,
        })

    def scan(self) -> dict:
        """执行一次市场扫描，返回异动报告。非交易时段直接返回空。"""
        now = datetime.now().strftime("%H:%M:%S")

        if not self._is_trading_time():
            return {"time": now, "alerts": [], "hotspot_top3": [], "northbound": {}}

        alerts = []
        current_hour = datetime.now().hour
        now_min = datetime.now().minute
        is_market_open = (current_hour == 9 and now_min >= 30) or (10 <= current_hour < 15)

        # 1. 扫描题材热点
        if is_market_open:
            try:
                hotspots = self.skills_api.get_sector_hotspots()
                alerts += self._check_hotspot_changes(hotspots)
                self._last_hotspots = hotspots
            except Exception as e:
                logger.error(f"热点扫描失败: {e}")

            # 2. 扫描北向资金
            try:
                nb = self.skills_api.get_northbound()
                alerts += self._check_northbound_alert(nb)
                self._last_northbound = nb.get("total", 0)
            except Exception as e:
                logger.error(f"北向扫描失败: {e}")

        # 3. 扫描快讯
        try:
            news = self.skills_api.get_flash_news(limit=5)
            alerts += self._check_breaking_news(news)
        except Exception as e:
            logger.error(f"快讯扫描失败: {e}")

        # 全局冷却：距上次告警不足2分钟，丢弃所有告警
        now_ts = time.time()
        if alerts and self._last_alert_time > 0:
            if now_ts - self._last_alert_time < GLOBAL_COOLDOWN:
                alerts = []
        if alerts:
            self._last_alert_time = now_ts

        return {
            "time": now,
            "alerts": alerts,
            "hotspot_top3": self._extract_top3(hotspots if 'hotspots' in dir() else None),
            "northbound": nb if 'nb' in dir() else {},
        }

    def _check_hotspot_changes(self, current: dict) -> list[dict]:
        alerts = []
        sectors = current.get("sectors", [])
        if not sectors:
            return alerts

        top3_now = {s["name"] for s in sectors[:3]}
        now_ts = time.time()

        if self._last_hotspots:
            top3_before = {s["name"] for s in self._last_hotspots.get("sectors", [])[:3]}
            new_in = top3_now - top3_before
            dropped = top3_before - top3_now

            # 过滤冷却期内的题材
            new_in = {n for n in new_in
                      if self._hotspot_cooldowns.get(n, 0) + HOTSPOT_COOLDOWN < now_ts}
            dropped = {d for d in dropped
                       if self._hotspot_cooldowns.get(d, 0) + HOTSPOT_COOLDOWN < now_ts}

            now_ts = time.time()

            # 合并进入+退出为一条消息，减少刷屏
            parts = []
            if new_in:
                for name in new_in:
                    self._hotspot_cooldowns[name] = now_ts
                parts.append(f"↑{', '.join(new_in)}")
            if dropped:
                for name in dropped:
                    self._hotspot_cooldowns[name] = now_ts
                parts.append(f"↓{', '.join(dropped)}")
            if parts:
                alerts.append({
                    "level": "关注",
                    "title": f"TOP3轮动: {' '.join(parts)}",
                    "detail": f"当前TOP3: {', '.join(top3_now)}",
                })

        # 题材数量暴增 — 去重：同一题材只告警一次
        top1 = sectors[0]
        if top1["count"] >= 10 and top1["name"] not in self._alerted_burst:
            self._alerted_burst.add(top1["name"])
            alerts.append({
                "level": "紧急",
                "title": f"题材集中爆发: {top1['name']} ({top1['count']}家涨停)",
                "detail": "板块效应极强，关注持续性",
            })

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

    def _extract_top3(self, hotspots) -> list[str]:
        if hotspots is None:
            return []
        return [s["name"] for s in hotspots.get("sectors", [])[:3]]
