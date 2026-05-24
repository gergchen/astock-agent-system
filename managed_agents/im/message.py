from dataclasses import dataclass, field


@dataclass
class InboundMessage:
    """收到的消息."""
    chat_id: str
    text: str
    chat_type: str  # "p2p" | "group"
    sender_id: str
    platform: str  # "feishu" | "wechat" | ...
    raw: dict = field(default_factory=dict)


@dataclass
class SendResult:
    success: bool
    message_id: str | None = None
    error: str = ""
