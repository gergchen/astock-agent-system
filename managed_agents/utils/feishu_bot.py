"""飞书应用机器人 — 后向兼容层，委托给 im/feishu_adapter.py."""

import logging
import threading

from managed_agents.im.feishu_adapter import FeishuAdapter
from managed_agents.im.message import SendResult

logger = logging.getLogger(__name__)

# ── 全局单例 ──
_adapter: FeishuAdapter | None = None
_receiver: object | None = None
_thread: threading.Thread | None = None

MessageHandler = callable  # (chat_id: str, user_text: str, chat_type: str) -> str | None


def send_message(chat_id: str, text: str, app_id: str = "", app_secret: str = "") -> bool:
    """向指定群聊发送文本消息（后向兼容函数）。"""
    global _adapter

    if not app_id:
        from ..config import get_config
        cfg = get_config()
        app_id = cfg.feishu_app_id
        app_secret = cfg.feishu_app_secret

    if not app_id or not chat_id:
        return False

    if _adapter is None:
        _adapter = FeishuAdapter(app_id, app_secret)

    result = _adapter.send(chat_id, text)
    return result.success


def start_bot(app_id: str, app_secret: str, handler: MessageHandler) -> None:
    """启动飞书机器人（后向兼容，委托给 FeishuAdapter）。"""
    global _adapter, _receiver, _thread

    if _adapter:
        return

    _adapter = FeishuAdapter(app_id, app_secret)

    def _wrapped_handler(inbound):
        reply = handler(inbound.chat_id, inbound.text, inbound.chat_type)
        return reply

    _adapter.start(_wrapped_handler)


def stop_bot() -> None:
    """停止飞书机器人。"""
    global _adapter
    if _adapter:
        _adapter.stop()
        _adapter = None
