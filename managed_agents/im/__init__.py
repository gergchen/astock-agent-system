"""IM 平台适配层 — 统一消息收发接口."""

from .adapter import IMAdapter
from .message import InboundMessage, SendResult
from .router import MessageRouter
from .feishu_adapter import FeishuAdapter

__all__ = ["IMAdapter", "InboundMessage", "SendResult", "MessageRouter", "FeishuAdapter"]
