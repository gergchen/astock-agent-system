"""Alert routing — fan-out alerts to multiple channels with dedup.

Channels:
  - FeishuChannel: 飞书 webhook push (existing notifier)
  - FileAlertChannel: JSON Lines audit log on disk

AlertManager deduplicates by (title, level) within a configurable window.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

FEISHU_MAX_BODY = 8000


# ── Types ──────────────────────────────────────────────────────────

class AlertLevel(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass
class Alert:
    level: AlertLevel
    title: str
    body: str = ""
    source: str = ""
    ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── Channel interface ──────────────────────────────────────────────

class AlertChannel(Protocol):
    """A sink for alerts. Returns True on success."""

    def send(self, alert: Alert) -> bool:
        ...


# ── FeishuChannel ───────────────────────────────────────────────────

class FeishuChannel:
    """Send alerts via 飞书 webhook, respecting trading-hour window."""

    def __init__(self, webhook_url: str = ""):
        self._url = webhook_url

    def send(self, alert: Alert) -> bool:
        if not self._url:
            return False

        tag = {"info": "ℹ️", "warn": "⚠️", "critical": "🚨"}.get(alert.level.value, "📢")
        text = f"[台式机] {tag} {alert.title}"
        if alert.body:
            text += f"\n{alert.body}"
        text = text[:FEISHU_MAX_BODY]

        try:
            import json as _json
            from urllib.request import Request, urlopen

            payload = _json.dumps({"msg_type": "text", "content": {"text": text}}).encode()
            req = Request(self._url, data=payload, headers={"Content-Type": "application/json"})
            urlopen(req, timeout=5)
            return True
        except Exception:
            return False


# ── FileAlertChannel ────────────────────────────────────────────────

class FileAlertChannel:
    """Append alerts as JSON Lines to a local audit log."""

    def __init__(self, file_path: str | Path = "data/alerts/alert.log"):
        self._path = Path(file_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, alert: Alert) -> bool:
        try:
            entry = {
                "ts": alert.ts,
                "level": alert.level.value,
                "title": alert.title,
                "body": alert.body,
                "source": alert.source,
            }
            with open(self._path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
            return True
        except Exception as e:
            logger.warning(f"Alert file write failed: {e}")
            return False

    def history(self, limit: int = 50) -> list[dict]:
        """Return the last N alerts (newest first)."""
        if not self._path.exists():
            return []
        lines = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    lines.append(json.loads(line))
        return list(reversed(lines[-limit:]))


# ── AlertManager ────────────────────────────────────────────────────

@dataclass
class AlertManager:
    """Routes alerts to all registered channels with simple dedup."""

    channels: list[AlertChannel] = field(default_factory=list)
    _dedup_window_sec: float = 300  # 5 min
    _recent: dict[tuple[str, str], float] = field(default_factory=dict)

    def send(
        self,
        title: str,
        body: str = "",
        level: AlertLevel | str = AlertLevel.INFO,
        source: str = "",
    ) -> None:
        """Fan-out an alert to all channels."""
        if isinstance(level, str):
            level = AlertLevel(level)

        # Dedup: same title+level within window is suppressed
        key = (title, level.value)
        now = time.time()
        if key in self._recent and (now - self._recent[key]) < self._dedup_window_sec:
            return
        self._recent[key] = now

        alert = Alert(level=level, title=title, body=body, source=source)

        for ch in self.channels:
            try:
                ch.send(alert)
            except Exception as e:
                logger.warning(f"Alert channel {type(ch).__name__} failed: {e}")
