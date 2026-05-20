"""飞书应用机器人 — 使用官方 lark-oapi SDK 长连接接收消息."""

import json
import logging
import re
import threading
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

FEISHU_DOMAIN = "https://open.feishu.cn"
MSG_MAX = 8000


# ── Token 管理 ──
def _get_tenant_token(app_id: str, app_secret: str) -> str:
    payload = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = Request(
        f"{FEISHU_DOMAIN}/open-apis/auth/v3/tenant_access_token/internal",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    resp = json.loads(urlopen(req, timeout=10).read())
    return resp["tenant_access_token"]


# ── 消息发送 ──
def send_message(chat_id: str, text: str, app_id: str = "", app_secret: str = "") -> bool:
    """向指定群聊发送文本消息."""
    if not app_id:
        from ..config import get_config
        cfg = get_config()
        app_id = cfg.feishu_app_id
        app_secret = cfg.feishu_app_secret
    if not app_id or not chat_id:
        return False

    token = _get_tenant_token(app_id, app_secret)
    content = json.dumps({"text": text[:MSG_MAX]})
    body = json.dumps({"receive_id": chat_id, "msg_type": "text", "content": content}).encode()
    url = f"{FEISHU_DOMAIN}/open-apis/im/v1/messages?receive_id_type=chat_id"

    try:
        req = Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        })
        urlopen(req, timeout=10)
        return True
    except Exception as e:
        logger.warning(f"发送失败: {e}")
        return False


# ── SDK 长连接接收器 ──
MessageHandler = callable  # (chat_id: str, user_text: str) -> str | None


class Receiver:
    """基于官方 SDK 的飞书长连接接收器."""

    def __init__(self, app_id: str, app_secret: str, handler: MessageHandler):
        self._app_id = app_id
        self._app_secret = app_secret
        self._handler = handler
        self._client = None
        self._running = False

    def start(self) -> None:
        from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
        from lark_oapi.ws import Client
        from lark_oapi.api.im.v1.model.p2_im_message_receive_v1 import P2ImMessageReceiveV1

        handler = (
            EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(lambda e: self._on_message(e))
            .build()
        )

        self._client = Client(
            app_id=self._app_id,
            app_secret=self._app_secret,
            event_handler=handler,
            domain="https://open.feishu.cn",
        )
        self._running = True
        logger.info("飞书长连接启动中...")
        self._client.start()

    def stop(self) -> None:
        self._running = False

    def _on_message(self, event) -> None:
        try:
            msg = event.event.message
            if msg.message_type != "text":
                return

            chat_id = msg.chat_id
            content = json.loads(msg.content)
            user_text = content.get("text", "")

            # 去除 @mention
            user_text = re.sub(r'@_\w+\s*', '', user_text).strip()
            if not user_text:
                return

            logger.info(f"收到: [{chat_id}] {user_text[:50]}")
            reply = self._handler(chat_id, user_text)
            if reply:
                send_message(chat_id, reply, self._app_id, self._app_secret)
        except Exception as e:
            logger.warning(f"消息处理异常: {e}")


# ── 后台管理 ──
_receiver: Receiver | None = None
_thread: threading.Thread | None = None


def start_bot(app_id: str, app_secret: str, handler: MessageHandler) -> None:
    global _receiver, _thread
    if _receiver:
        return
    _receiver = Receiver(app_id, app_secret, handler)
    _thread = threading.Thread(target=_receiver.start, daemon=True, name="feishu-bot")
    _thread.start()
    logger.info("飞书机器人已启动")


def stop_bot() -> None:
    global _receiver
    if _receiver:
        _receiver.stop()
        _receiver = None
