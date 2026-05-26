"""Progress reporter — real-time Feishu card updates.

Usage:
    reporter = FeishuCardProgressReporter(feishu_adapter, chat_id)
    reporter.start("A股交易助手", ["获取数据", "分析", "生成结论"])
    ...
    reporter.update("获取数据", "done", "OK")
    reporter.update("分析", "running")
    ...
    reporter.finish("最终结果文本")
"""

import json
import logging

logger = logging.getLogger(__name__)


class FeishuCardProgressReporter:
    """通过飞书交互式卡片实时展示处理进度。

    使用方式:
        1. start() — 发送初始卡片
        2. update(stage, status, detail) — 逐阶段更新
        3. finish(final_text) — 标记完成并展示结果
    """

    def __init__(self, adapter, chat_id: str):
        self._adapter = adapter
        self._chat_id = chat_id
        self._message_id: str | None = None
        # stages: [(label, status, detail)]
        #   status: "pending" | "running" | "done" | "error"
        self._stages: list[list[str]] = []

    # ── 公开 API ──

    def start(self, title: str = "A股交易助手", stages: list[str] | None = None) -> None:
        """发送初始卡片，标题 + 阶段列表 (全部 pending)。"""
        self._stages = [[s, "pending", ""] for s in (stages or [])]
        card = self._build_card(title)
        result = self._adapter.send_card(self._chat_id, card)
        if result.success and result.message_id:
            self._message_id = result.message_id
            logger.info(f"Progress card sent: {self._message_id}")
        else:
            logger.warning("Failed to send initial progress card")

    def update(self, stage_label: str, status: str, detail: str = "") -> None:
        """更新阶段状态并刷新卡片。status: pending|running|done|error"""
        for s in self._stages:
            if s[0] == stage_label:
                s[1] = status
                if detail:
                    s[2] = detail
                break
        if self._message_id:
            card = self._build_card()
            self._adapter.update_card(self._message_id, card)

    def finish(self, final_text: str = "") -> None:
        """所有未完成阶段标记为 done，显示最终文本。"""
        for s in self._stages:
            if s[1] in ("pending", "running"):
                s[1] = "done"
        if final_text:
            self._stages.append(["完成", "done", final_text[:200]])
        if self._message_id:
            card = self._build_card()
            self._adapter.update_card(self._message_id, card)
            logger.info("Progress card finalized")

    def error(self, stage_label: str, detail: str = "") -> None:
        """标记阶段为错误状态。"""
        self.update(stage_label, "error", detail)

    # ── 内部 ──

    def _build_card(self, title: str = "A股交易助手") -> dict:
        elements: list[dict] = []
        for label, status, detail in self._stages:
            icon = {
                "pending": "⏺",
                "running": "⏳",
                "done": "✅",
                "error": "❌",
            }.get(status, "⏺")
            line = f"{icon} **{label}**"
            if detail:
                line += f"\n_{detail}_"
            elements.append({"tag": "markdown", "content": line})
            elements.append({"tag": "hr"})

        # 移除最后一个 hr
        if elements and elements[-1]["tag"] == "hr":
            elements.pop()

        # 页脚 — 更新时间
        from datetime import datetime
        elements.append({
            "tag": "note",
            "elements": [
                {"tag": "plain_text", "content": f"⏱ {datetime.now().strftime('%H:%M:%S')}"}
            ],
        })

        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": elements,
        }
