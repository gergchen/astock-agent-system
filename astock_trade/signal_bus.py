"""SQLite WAL-based message bus — reliable inter-agent communication.

Replaces the file-based JSON bus with:
- Atomic message claiming (no double-consumption)
- Consumer groups with ACK/NACK
- Automatic stale-message requeue (crash recovery)
- Message persistence and replay
- Thread-safe + multi-process safe via WAL + BEGIN IMMEDIATE
"""

import json
import logging
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Optional

from .config import get_config
from .exceptions import BusError

logger = logging.getLogger(__name__)

MESSAGE_TYPES = frozenset({
    "trade_signal",
    "risk_decision",
    "trade_result",
    "portfolio_plan",
    "alert",
    "status_update",
})

VALID_CHANNELS = frozenset({
    "from_researcher",
    "from_risk_officer",
    "from_trader",
    "portfolio_plan",
    "alerts",
    "status",
})

# Messages stuck in 'processing' longer than this are auto-requeued
STALE_PROCESSING_SECONDS = 300

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL,
    type TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    consumer_group TEXT DEFAULT NULL,
    created_at REAL NOT NULL,
    processed_at REAL DEFAULT NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT DEFAULT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_channel_status
    ON messages(channel, status, created_at);

CREATE INDEX IF NOT EXISTS idx_messages_status_created
    ON messages(status, created_at);

CREATE INDEX IF NOT EXISTS idx_messages_consumer
    ON messages(consumer_group, status);
"""


class SignalBus:
    """SQLite-backed message bus with consumer groups and ACK/NACK."""

    def __init__(self, db_path: str | Path | None = None):
        cfg = get_config()
        self._db_path = str(db_path or cfg.bus_dir / "signal_bus.db")
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
        self._init_db()

    def _init_db(self):
        with self._get_conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.executescript(SCHEMA)

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = sqlite3.Row
        return conn

    # ── Publish ──────────────────────────────────────────────

    def publish(self, channel: str, message: dict) -> str:
        """Publish a message to a channel. Returns the message ID."""
        if channel not in VALID_CHANNELS:
            raise BusError(f"Unknown channel: {channel}")
        if "type" not in message:
            raise BusError("Message must have a 'type' field")
        if message["type"] not in MESSAGE_TYPES:
            raise BusError(f"Unknown message type: {message['type']}")

        msg_id = str(uuid.uuid4())
        message.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        payload = json.dumps(message, ensure_ascii=False)

        with self._lock, self._get_conn() as conn:
            conn.execute(
                """INSERT INTO messages (id, channel, type, payload, status, created_at)
                   VALUES (?, ?, ?, ?, 'pending', ?)""",
                (msg_id, channel, message["type"], payload, time.time()),
            )

        # Enforce max messages per channel (keep latest 1000)
        self._trim_channel(channel, max_messages=1000)
        return msg_id

    def _trim_channel(self, channel: str, max_messages: int = 1000):
        """Remove oldest messages beyond max_messages for a channel."""
        with self._lock, self._get_conn() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE channel = ?", (channel,)
            ).fetchone()[0]
            if count > max_messages:
                excess = count - max_messages
                conn.execute(
                    """DELETE FROM messages WHERE id IN (
                           SELECT id FROM messages WHERE channel = ?
                           ORDER BY created_at ASC LIMIT ?
                       )""",
                    (channel, excess),
                )

    # ── Consume ─────────────────────────────────────────────

    def consume(
        self,
        channel: str,
        n: int = 1,
        consumer_group: str = "default",
    ) -> list[dict]:
        """Claim and return the oldest n pending messages from a channel.

        Messages are atomically marked 'processing' so no other consumer
        can claim them. Call ack() after successful processing or nack()
        on failure to return them to the queue.
        """
        if channel not in VALID_CHANNELS:
            raise BusError(f"Unknown channel: {channel}")

        with self._lock, self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                rows = conn.execute(
                    """SELECT id, type, payload, created_at FROM messages
                       WHERE channel = ? AND status = 'pending'
                       ORDER BY created_at ASC
                       LIMIT ?""",
                    (channel, n),
                ).fetchall()

                if not rows:
                    conn.execute("COMMIT")
                    return []

                msg_ids = [row["id"] for row in rows]
                now = time.time()
                conn.execute(
                    f"""UPDATE messages SET status = 'processing',
                           consumer_group = ?, processed_at = ?
                         WHERE id IN ({','.join('?' * len(msg_ids))})""",
                    [consumer_group, now] + msg_ids,
                )
                conn.execute("COMMIT")

                messages = []
                for row in rows:
                    msg = json.loads(row["payload"])
                    msg["_id"] = row["id"]
                    msg["_channel"] = channel
                    messages.append(msg)
                return messages
            except Exception:
                conn.execute("ROLLBACK")
                raise

    # ── ACK / NACK ──────────────────────────────────────────

    def ack(self, message_id: str) -> bool:
        """Mark a message as successfully processed."""
        with self._lock, self._get_conn() as conn:
            cur = conn.execute(
                "UPDATE messages SET status = 'processed' WHERE id = ? AND status = 'processing'",
                (message_id,),
            )
            return cur.rowcount > 0

    def nack(self, message_id: str, error: str = "", requeue: bool = True) -> bool:
        """Mark a message as failed. If requeue=True, reset to 'pending' for retry."""
        with self._lock, self._get_conn() as conn:
            if requeue:
                cur = conn.execute(
                    """UPDATE messages
                       SET status = 'pending',
                           consumer_group = NULL,
                           processed_at = NULL,
                           retry_count = retry_count + 1,
                           error_message = ?
                       WHERE id = ?""",
                    (error, message_id),
                )
            else:
                cur = conn.execute(
                    """UPDATE messages
                       SET status = 'failed', error_message = ?
                       WHERE id = ?""",
                    (error, message_id),
                )
            return cur.rowcount > 0

    def ack_all(self, channel: str, consumer_group: str = "default") -> int:
        """Ack all 'processing' messages for a consumer group on a channel."""
        with self._lock, self._get_conn() as conn:
            cur = conn.execute(
                """UPDATE messages SET status = 'processed'
                   WHERE channel = ? AND consumer_group = ? AND status = 'processing'""",
                (channel, consumer_group),
            )
            return cur.rowcount

    # ── Requeue stale ───────────────────────────────────────

    def requeue_stale(self, max_stale_seconds: int = STALE_PROCESSING_SECONDS) -> int:
        """Reset stuck 'processing' messages back to 'pending'.

        Handles crash recovery: if a consumer died without ack/nack,
        its claimed messages are returned to the queue.
        """
        cutoff = time.time() - max_stale_seconds
        with self._lock, self._get_conn() as conn:
            cur = conn.execute(
                """UPDATE messages
                   SET status = 'pending',
                       consumer_group = NULL,
                       processed_at = NULL,
                       retry_count = retry_count + 1
                   WHERE status = 'processing' AND processed_at < ?""",
                (cutoff,),
            )
            count = cur.rowcount
            if count > 0:
                logger.warning("Requeued %d stale messages", count)
            return count

    # ── Peek ────────────────────────────────────────────────

    def peek(self, channel: str, limit: int = 10) -> list[dict]:
        """Read messages without claiming them."""
        if channel not in VALID_CHANNELS:
            raise BusError(f"Unknown channel: {channel}")

        with self._lock, self._get_conn() as conn:
            rows = conn.execute(
                """SELECT id, type, payload, status, created_at FROM messages
                   WHERE channel = ?
                   ORDER BY created_at DESC
                   LIMIT ?""",
                (channel, limit),
            ).fetchall()

        messages = []
        for row in reversed(rows):
            msg = json.loads(row["payload"])
            msg["_id"] = row["id"]
            msg["_status"] = row["status"]
            messages.append(msg)
        return messages

    # ── Management ──────────────────────────────────────────

    def clear_channel(self, channel: str) -> int:
        """Delete all messages from a channel."""
        with self._lock, self._get_conn() as conn:
            cur = conn.execute("DELETE FROM messages WHERE channel = ?", (channel,))
            return cur.rowcount

    def list_channels(self) -> list[str]:
        """List channels that have messages."""
        with self._lock, self._get_conn() as conn:
            rows = conn.execute(
                "SELECT DISTINCT channel FROM messages"
            ).fetchall()
            return sorted(r["channel"] for r in rows)

    def stats(self) -> dict:
        """Return message counts by status."""
        with self._lock, self._get_conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) as cnt FROM messages GROUP BY status"
            ).fetchall()
            total = sum(r["cnt"] for r in rows)
            by_status = {r["status"]: r["cnt"] for r in rows}
            return {"total": total, "by_status": by_status}

    def get_message(self, message_id: str) -> dict | None:
        """Retrieve a single message by ID."""
        with self._lock, self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
            if row is None:
                return None
            msg = json.loads(row["payload"])
            msg["_id"] = row["id"]
            msg["_status"] = row["status"]
            msg["_retry_count"] = row["retry_count"]
            return msg

    def vacuum(self):
        """Reclaim disk space after large deletions."""
        with self._lock, self._get_conn() as conn:
            conn.execute("VACUUM")


# Module-level singleton
_bus: SignalBus | None = None


def get_bus() -> SignalBus:
    global _bus
    if _bus is None:
        _bus = SignalBus()
    return _bus


def reset_bus():
    global _bus
    _bus = None
