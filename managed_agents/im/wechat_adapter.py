import logging
from .adapter import IMAdapter, MessageHandler
from .message import SendResult

logger = logging.getLogger(__name__)


class WechatAdapter(IMAdapter):
    """WeChat adapter skeleton."""

    def __init__(self, bot_token: str = "", base_url: str = ""):
        self._bot_token = bot_token
        self._base_url = base_url or "https://ilinkai.weixin.qq.com"

    @property
    def name(self) -> str:
        return "wechat"

    def send(self, chat_id: str, text: str) -> SendResult:
        if not self._bot_token:
            return SendResult(False, error="wechat not configured")
        logger.warning(f"WeChat send not implemented: [{chat_id}] {text[:40]}")
        return SendResult(False, error="WeChat adapter not yet implemented")

    def start(self, handler: MessageHandler) -> None:
        logger.info("WeChat adapter not implemented")

    def stop(self) -> None:
        pass

    def startable(self) -> bool:
        return bool(self._bot_token)
