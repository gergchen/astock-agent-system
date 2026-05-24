"""抖音带货监控 Agent.

职责:
- 定时扫描已配置的抖音用户最新视频
- 通过 LLM 分析文案识别带货商品
- 发现带货时推送飞书通知
"""

import logging

from ..base import BaseAgent
from ...skills.douyin_skills import DouyinSkills

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是抖音带货监控 Agent，负责监测指定抖音用户的最新视频，识别带货商品。

## 核心职责
1. 定时扫描监控列表中的抖音用户
2. 分析视频文案，识别品牌、产品名称、品类、价格等信息
3. 发现带货商品立即推送飞书通知
4. 支持手动分析指定的视频或用户

## 可用能力
- scan_all: 扫描所有已配置用户
- scan_user: 扫描指定用户
- analyze_video: 分析单个视频
- list_users: 列出监控中的用户

## 输出要求
- 检测到带货时提供结构化信息：品牌、产品、品类、价格
- 置信度低于 30% 的不推送
"""


class DouyinMonitor(BaseAgent):
    """抖音带货监控 Agent."""

    def __init__(self):
        self.skills_api = DouyinSkills()
        super().__init__(name="douyin_monitor", role="抖音监控")

    def system_prompt(self) -> str:
        return SYSTEM_PROMPT

    def _register_skills(self):
        self._skills.update({
            "scan_all": self.skills_api.scan_all_users,
            "scan_user": self.skills_api.scan_user,
            "analyze_video": self.skills_api.analyze_video,
            "list_users": self.skills_api.list_users,
            "get_user_info": self.skills_api.get_user_info,
        })

    def run_forever(self, interval: int | None = None) -> None:
        """启动轮询 (类似 Sentinel.run_sentinel)."""
        from ...douyin.crawler import DouyinCrawler
        crawler = DouyinCrawler()
        crawler.run_forever(interval)
