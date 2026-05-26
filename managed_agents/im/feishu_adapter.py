import json
import logging
import re
import threading
import time
from urllib.request import Request, urlopen

from .adapter import IMAdapter, MessageHandler
from .message import InboundMessage, SendResult

logger = logging.getLogger(__name__)

FEISHU_DOMAIN = "https://open.feishu.cn"
MSG_MAX = 8000

_EVENT_DEDUP: dict[str, float] = {}
_EVENT_DEDUP_WINDOW = 60.0

# 租户 token 缓存：key -> (token, expire_at)
_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_TOKEN_CACHE_TTL = 5400  # 1.5h（飞书 token 有效期 2h）


def _get_tenant_token(app_id: str, app_secret: str) -> str:
    now = time.time()
    cache_key = f"{app_id}:{app_secret}"
    cached = _TOKEN_CACHE.get(cache_key)
    if cached and now < cached[1]:
        return cached[0]

    payload = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode()
    req = Request(
        f"{FEISHU_DOMAIN}/open-apis/auth/v3/tenant_access_token/internal",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    resp = json.loads(urlopen(req, timeout=10).read())
    token = resp["tenant_access_token"]
    _TOKEN_CACHE[cache_key] = (token, now + _TOKEN_CACHE_TTL)
    return token


class FeishuAdapter(IMAdapter):
    """Feishu adapter - send (bot API) + receive (lark_oapi WS)."""

    def __init__(self, app_id: str, app_secret: str):
        self._app_id = app_id
        self._app_secret = app_secret
        self._client = None
        self._running = False

    @property
    def name(self) -> str:
        return "feishu"

    def send(self, chat_id: str, text: str) -> SendResult:
        if not self._app_id or not chat_id:
            return SendResult(False, error="app_id or chat_id empty")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                token = _get_tenant_token(self._app_id, self._app_secret)
                content = json.dumps({"text": text[:MSG_MAX]})
                body = json.dumps({
                    "receive_id": chat_id,
                    "msg_type": "text",
                    "content": content,
                }).encode()
                url = f"{FEISHU_DOMAIN}/open-apis/im/v1/messages?receive_id_type=chat_id"

                req = Request(url, data=body, headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                })
                resp = json.loads(urlopen(req, timeout=10).read())
                msg_id = (resp.get("data") or {}).get("message_id", "")
                if msg_id:
                    logger.info(f"Feishu sent: {text[:40]}...")
                    return SendResult(True, message_id=msg_id)
                logger.warning(f"Feishu send returned no msg_id (attempt {attempt+1})")
            except Exception as e:
                logger.warning(f"Feishu send failed (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                continue

        return SendResult(False, error=f"Failed after {max_retries} attempts")

    def start(self, handler: MessageHandler) -> None:
        from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
        from lark_oapi.ws import Client

        event_handler = (
            EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(
                lambda e: self._on_message(e, handler)
            )
            .build()
        )

        self._client = Client(
            app_id=self._app_id,
            app_secret=self._app_secret,
            event_handler=event_handler,
            domain="https://open.feishu.cn",
        )
        self._running = True
        logger.info("Feishu WS starting...")
        self._client.start()

    def stop(self) -> None:
        self._running = False

    def send_card(self, chat_id: str, card_dict: dict) -> SendResult:
        """发送交互式卡片消息，返回 SendResult (含 message_id)。"""
        max_retries = 2
        for attempt in range(max_retries):
            try:
                token = _get_tenant_token(self._app_id, self._app_secret)
                content = json.dumps(card_dict, ensure_ascii=False)
                body = json.dumps({
                    "receive_id": chat_id,
                    "msg_type": "interactive",
                    "content": content,
                }).encode()
                url = f"{FEISHU_DOMAIN}/open-apis/im/v1/messages?receive_id_type=chat_id"
                req = Request(url, data=body, headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                })
                resp = json.loads(urlopen(req, timeout=10).read())
                msg_id = (resp.get("data") or {}).get("message_id", "")
                if msg_id:
                    logger.info(f"Feishu card sent, msg_id={msg_id}")
                    return SendResult(True, message_id=msg_id)
                logger.warning(f"Feishu card send no msg_id (attempt {attempt+1})")
            except Exception as e:
                logger.warning(f"Feishu card send failed (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
        return SendResult(False, error="card send failed")

    def update_card(self, message_id: str, card_dict: dict) -> bool:
        """更新已发送的卡片消息（PATCH）。"""
        max_retries = 2
        for attempt in range(max_retries):
            try:
                token = _get_tenant_token(self._app_id, self._app_secret)
                content = json.dumps(card_dict, ensure_ascii=False)
                body = json.dumps({"content": content}).encode()
                url = f"{FEISHU_DOMAIN}/open-apis/im/v1/messages/{message_id}"
                req = Request(url, data=body, headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                }, method="PATCH")
                resp = json.loads(urlopen(req, timeout=10).read())
                ok = resp.get("code", -1) == 0
                if ok:
                    return True
                logger.warning(f"Feishu card update failed: {resp.get('msg','')} (attempt {attempt+1})")
            except Exception as e:
                logger.warning(f"Feishu card update error (attempt {attempt+1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(1)
        return False

    def startable(self) -> bool:
        return bool(self._app_id and self._app_secret)

    def _on_message(self, event, handler: MessageHandler) -> None:
        try:
            event_id = ""
            try:
                event_id = getattr(event, "event_id", "") or (
                    event.header.event_id if hasattr(event, "header") else ""
                )
            except Exception:
                pass

            msg = event.event.message

            now_s = time.time()
            try:
                ct = int(msg.create_time) / 1000
                if now_s - ct > 300:
                    logger.info(f"Drop old msg ({now_s - ct:.0f}s old)")
                    return
            except (AttributeError, ValueError, TypeError):
                pass

            if event_id:
                if event_id in _EVENT_DEDUP and now_s - _EVENT_DEDUP[event_id] < _EVENT_DEDUP_WINDOW:
                    return
                _EVENT_DEDUP[event_id] = now_s

            if msg.message_type != "text":
                return

            chat_id = msg.chat_id
            sender_id = event.event.sender.sender_id.user_id if event.event.sender else "unknown"
            raw_content = json.loads(msg.content)
            user_text = raw_content.get("text", "")

            if sender_id == self._app_id:
                return

            user_text = re.sub(r'@_\\w+\\s*', '', user_text).strip()
            if not user_text:
                return

            chat_type = getattr(msg, "chat_type", "group")
            logger.info(f"Feishu recv: {chat_type} sender={sender_id} [{chat_id}] {user_text[:50]}")

            inbound = InboundMessage(
                chat_id=chat_id,
                text=user_text,
                chat_type=chat_type,
                sender_id=sender_id,
                platform="feishu",
            )

            # 异步处理，不阻塞 WS 事件循环
            threading.Thread(
                target=self._handle_async,
                args=(inbound, handler),
                daemon=True,
            ).start()

        except Exception as e:
            logger.warning(f"Feishu msg error: {e}")

    def _handle_async(self, inbound: InboundMessage, handler: MessageHandler) -> None:
        try:
            reply = handler(inbound)
            if reply:
                self.send(inbound.chat_id, reply)
            else:
                logger.info("Handler returned empty reply for %s", inbound.chat_id)
        except Exception as e:
            logger.error(f"Feishu handle error: {e}", exc_info=True)
            try:
                self.send(inbound.chat_id, "系统处理异常，请稍后重试")
            except Exception:
                pass
