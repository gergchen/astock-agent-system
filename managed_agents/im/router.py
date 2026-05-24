import logging
import time
import threading
from collections.abc import Callable

from .adapter import IMAdapter
from .message import InboundMessage, SendResult
from .dedup import MessageDedup

logger = logging.getLogger(__name__)

_USER_DEDUP_WINDOW = 30.0


class MessageRouter:
    """Unified message router managing multiple IM adapters."""

    def __init__(self):
        self._adapters: dict[str, IMAdapter] = {}
        self._dedup = MessageDedup(ttl=600)
        self._user_dedup: dict[str, float] = {}
        self._user_dedup_lock = threading.Lock()
        self._route_fn = None

    def register(self, adapter: IMAdapter) -> None:
        self._adapters[adapter.name] = adapter
        logger.info(f"Router: registered {adapter.name} adapter")

    def get(self, name: str) -> IMAdapter | None:
        return self._adapters.get(name)

    @property
    def platforms(self) -> list[str]:
        return list(self._adapters.keys())

    def start_all(self) -> None:
        for name, adapter in self._adapters.items():
            if adapter.startable():
                logger.info(f"Router: starting {name}")
                adapter.start(lambda msg: self._on_message(msg))
            else:
                logger.warning(f"Router: {name} not configured, skipped")

    def stop_all(self) -> None:
        for adapter in self._adapters.values():
            adapter.stop()

    def send(self, text: str, chat_id: str = "", platform: str = "") -> SendResult:
        if platform:
            adapter = self._adapters.get(platform)
            if not adapter:
                return SendResult(False, error=f"unknown platform: {platform}")
            return adapter.send(chat_id, text)
        if "feishu" in self._adapters:
            return self._adapters["feishu"].send(chat_id, text)
        return SendResult(False, error="no available adapter")

    def set_route_fn(self, fn: Callable[[InboundMessage], str | None]) -> None:
        self._route_fn = fn

    def _on_message(self, msg: InboundMessage) -> str | None:
        dedup_key = f"{msg.platform}|{msg.chat_id}|{msg.text}"
        with self._user_dedup_lock:
            now = time.time()
            if dedup_key in self._user_dedup and now - self._user_dedup[dedup_key] < _USER_DEDUP_WINDOW:
                return None
            self._user_dedup[dedup_key] = now

        if self._route_fn:
            return self._route_fn(msg)
        return None
