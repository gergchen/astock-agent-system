"""Agent message bus — file-based inter-agent communication.

Each agent reads/writes JSON messages in data/bus/.
Simple, debug-friendly, no external dependency. Upgrade to Redis if needed.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import get_config
from .exceptions import BusError

MESSAGE_TYPES = frozenset({
    "trade_signal",      # Researcher → Risk Officer
    "risk_decision",     # Risk Officer → Trader
    "trade_result",      # Trader → Everyone
    "portfolio_plan",    # Portfolio Manager → Researcher
    "alert",             # Anyone → User (via cc-connect)
    "status_update",     # Anyone → Anyone (heartbeat)
})


def _bus_dir() -> Path:
    d = get_config().bus_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def _channel_path(channel: str) -> Path:
    """Channel names: from_researcher, from_risk_officer, from_trader, alerts, status"""
    if channel not in ("from_researcher", "from_risk_officer", "from_trader",
                        "portfolio_plan", "alerts", "status"):
        raise BusError(f"Unknown channel: {channel}")
    return _bus_dir() / f"{channel}.json"


def publish(channel: str, message: dict) -> Path:
    """Publish a message to a channel. Appends to the channel file."""
    if "type" not in message:
        raise BusError("Message must have a 'type' field")
    if message["type"] not in MESSAGE_TYPES:
        raise BusError(f"Unknown message type: {message['type']}")

    message.setdefault("timestamp", datetime.now().isoformat(timespec="seconds"))
    p = _channel_path(channel)
    existing = []
    if p.exists():
        existing = json.loads(p.read_text(encoding="utf-8"))

    existing.append(message)
    if len(existing) > 50:
        existing = existing[-50:]

    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)
    return p


def consume(channel: str, n: int = 1) -> list[dict]:
    """Read and remove the oldest n messages from a channel."""
    p = _channel_path(channel)
    if not p.exists():
        return []

    existing = json.loads(p.read_text(encoding="utf-8"))
    messages = existing[:n]
    remaining = existing[n:]

    if remaining:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(remaining, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
    else:
        p.unlink(missing_ok=True)

    return messages


def peek(channel: str, limit: int = 10) -> list[dict]:
    """Read messages without removing them."""
    p = _channel_path(channel)
    if not p.exists():
        return []
    existing = json.loads(p.read_text(encoding="utf-8"))
    return existing[-limit:]


def clear_channel(channel: str) -> None:
    """Clear all messages from a channel."""
    p = _channel_path(channel)
    p.unlink(missing_ok=True)


def list_channels() -> list[str]:
    """List active channels that have messages."""
    d = _bus_dir()
    return sorted(p.stem for p in d.glob("*.json"))

# ── Convenience functions for each agent ─────────────────────────

def researcher_publish_signal(signal: dict) -> Path:
    """Researcher publishes a trade signal to the risk officer."""
    signal["type"] = "trade_signal"
    return publish("from_researcher", signal)


def risk_officer_consume_signals(n: int = 1) -> list[dict]:
    """Risk officer reads pending signals."""
    return consume("from_researcher", n)


def risk_officer_publish_decision(decision: dict) -> Path:
    """Risk officer publishes decisions to the trader."""
    decision["type"] = "risk_decision"
    return publish("from_risk_officer", decision)


def trader_consume_decisions(n: int = 1) -> list[dict]:
    """Trader reads approved decisions."""
    return consume("from_risk_officer", n)


def trader_publish_result(result: dict) -> Path:
    """Trader publishes execution results."""
    result["type"] = "trade_result"
    return publish("from_trader", result)


def pm_publish_plan(plan: dict) -> Path:
    """Portfolio manager publishes daily plan."""
    plan["type"] = "portfolio_plan"
    return publish("portfolio_plan", plan)


def send_alert(message: str, level: str = "INFO") -> Path:
    """Send an alert message (INFO, WARN, CRITICAL)."""
    return publish("alerts", {
        "type": "alert",
        "level": level,
        "message": message,
    })
