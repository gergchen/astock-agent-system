from abc import ABC, abstractmethod
from collections.abc import Callable
from .message import InboundMessage, SendResult

MessageHandler = Callable[[InboundMessage], str | None]


class IMAdapter(ABC):
    """IM platform adapter base class."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def send(self, chat_id: str, text: str) -> SendResult: ...

    @abstractmethod
    def start(self, handler: MessageHandler) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def startable(self) -> bool: ...
