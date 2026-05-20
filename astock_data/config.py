"""Centralized configuration management.

Merges defaults, config file (~/.astock_data/config.yaml), and environment variables.
"""

import os
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Config:
    """Singleton configuration for astock_data."""

    # Cache
    cache_dir: Path = field(default_factory=lambda: Path.home() / ".astock_data" / "cache")
    cache_default_ttl: int = 300  # seconds

    # Cache TTLs per data type (seconds)
    cache_ttls: dict = field(default_factory=lambda: {
        "quote": 3,
        "kline_intraday": 60,
        "kline_daily": 3600,
        "valuation": 300,
        "hotspot": 600,
        "northbound_realtime": 60,
        "northbound_history": 3600,
        "research_report": 21600,
        "consensus_eps": 86400,
        "stock_news": 300,
        "flash_news": 60,
        "global_news": 300,
        "finance": 86400,
        "f10": 86400,
        "stock_basics": 86400,
        "announcement": 3600,
        "geopolitical_news": 600,
        "world_headlines": 300,
    })

    # Rate limits (requests per second per source)
    rate_limits: dict = field(default_factory=lambda: {
        "mootdx": 3.0,
        "tencent": 5.0,
        "akshare": 2.0,
        "ths": 2.0,
        "cls": 2.0,
        "iwencai": 1.0,
        "newsapi": 3.0,
    })

    # mootdx servers (round-robin)
    tdx_servers: list = field(default_factory=lambda: [
        {"ip": "119.147.212.81", "port": 7709},
        {"ip": "120.76.152.2", "port": 7709},
        {"ip": "47.92.127.178", "port": 7709},
        {"ip": "106.14.255.129", "port": 7709},
    ])

    # Retry settings
    retry_max_attempts: int = 3
    retry_backoff_base: float = 1.0
    retry_jitter: bool = True

    # iwencai settings
    iwencai_api_key: str = ""
    iwencai_base_url: str = "https://openapi.iwencai.com"

    # NewsAPI settings
    newsapi_api_key: str = ""

    # HTTP settings
    http_timeout: int = 30
    http_user_agent: str = "astock-data/2.0.0"

    # Skill mode
    skill_mode: bool = False

    def __post_init__(self):
        # Load from environment
        self.iwencai_api_key = os.environ.get("IWENCAI_API_KEY", self.iwencai_api_key)
        self.iwencai_base_url = os.environ.get("IWENCAI_BASE_URL", self.iwencai_base_url)
        self.newsapi_api_key = os.environ.get("NEWSAPI_API_KEY", self.newsapi_api_key)
        self.skill_mode = os.environ.get("CLAUDE_CODE_SKILL", "0") == "1"


_config: Config | None = None


def get_config() -> Config:
    """Return the global Config singleton, initializing on first call."""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reset_config() -> None:
    """Reset config singleton (useful for testing)."""
    global _config
    _config = None
