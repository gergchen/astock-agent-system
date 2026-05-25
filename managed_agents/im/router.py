import logging
from collections.abc import Callable

from .adapter import IMAdapter
from .message import InboundMessage, SendResult

logger = logging.getLogger(__name__)


class MessageRouter:
    """Unified message router managing multiple IM adapters."""

    def __init__(self):
        self._adapters: dict[str, IMAdapter] = {}
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
        if self._route_fn:
            return self._route_fn(msg)
        return None
