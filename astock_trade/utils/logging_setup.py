"""Unified logging setup with console + rotating file handlers.

Call setup_logging() once at entry-point. Subsequent calls are no-ops.
File output uses JSON Lines for machine-readability; console is human-friendly.
"""

import json
import logging
import logging.config
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

_SETUP_DONE = False


@dataclass
class LogConfig:
    level: str = "INFO"
    log_dir: Path = field(default_factory=lambda: Path("data/logs"))
    console: bool = True
    file: bool = True
    file_max_mb: int = 10
    file_backups: int = 5

    def __post_init__(self):
        level = os.environ.get("ATRADE_LOG_LEVEL")
        if level:
            self.level = level.upper()
        if os.environ.get("ATRADE_LOG_FILE"):
            self.log_dir = Path(os.environ["ATRADE_LOG_FILE"]).parent
        if os.environ.get("ATRADE_LOG_CONSOLE") in ("0", "false", "no"):
            self.console = False


class _JsonFormatter(logging.Formatter):
    """JSON Lines formatter: one JSON object per log event."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()
        entry = {
            "ts": ts,
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            entry["exc"] = str(record.exc_info[1])
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(cfg: LogConfig | None = None) -> None:
    """Configure root logger with console + rotating file handlers. Idempotent."""
    global _SETUP_DONE
    if _SETUP_DONE:
        return

    if cfg is None:
        cfg = LogConfig()

    cfg.log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, cfg.level.upper(), logging.INFO))

    # Clear any pre-existing handlers from basicConfig
    root.handlers.clear()

    # Console handler — human-readable
    if cfg.console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setLevel(root.level)
        ch.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
            datefmt="%m-%d %H:%M:%S",
        ))
        root.addHandler(ch)

    # Rotating file handler — JSON Lines
    if cfg.file:
        log_file = cfg.log_dir / "system.log"
        fh = RotatingFileHandler(
            str(log_file),
            maxBytes=cfg.file_max_mb * 1024 * 1024,
            backupCount=cfg.file_backups,
            encoding="utf-8",
        )
        fh.setLevel(root.level)
        fh.setFormatter(_JsonFormatter())
        root.addHandler(fh)

    _SETUP_DONE = True


def get_logger(name: str) -> logging.Logger:
    """Convenience wrapper — ensures setup_logging has been called."""
    if not _SETUP_DONE:
        setup_logging()
    return logging.getLogger(name)
