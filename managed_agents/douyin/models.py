"""抖音监控数据模型."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class DouyinVideo:
    """抖音视频基础信息."""
    video_id: str
    aweme_id: str = ""
    desc: str = ""
    create_time: int = 0
    cover_url: str = ""
    author_sec_uid: str = ""
    author_nickname: str = ""
    play_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    share_count: int = 0
    video_url: str = ""
    duration: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProductInfo:
    """LLM 分析出的带货商品信息."""
    has_product: bool = False
    brand: str = ""
    product_name: str = ""
    category: str = ""
    price: str = ""
    confidence: float = 0.0
    raw_text: str = ""


@dataclass
class AnalysisResult:
    """单条视频的完整分析结果."""
    video: DouyinVideo
    product: ProductInfo | None = None
    analyzed_at: str = ""


@dataclass
class UserState:
    """已持久化的用户监控状态."""
    sec_user_id: str
    nickname: str = ""
    last_video_id: str = ""
    last_check_time: str = ""
    checked_video_ids: list[str] = field(default_factory=list)
    last_alert_time: str = ""
    enabled: bool = True


@dataclass
class DouyinConfig:
    """抖音监控配置."""
    api_base_url: str = "http://localhost:8000"
    poll_interval_seconds: int = 600
    max_videos_per_scan: int = 20
    enable_vision: bool = False
    vision_model: str = "claude-sonnet-4-6"
    monitored_users: list[dict] = field(default_factory=list)
    # 并发控制
    max_concurrent_analysis: int = 3
    rate_limit_per_minute: int = 30
    # 静默时段（不推送，只记录）
    quiet_hours_start: str = "23:00"
    quiet_hours_end: str = "08:00"
