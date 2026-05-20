"""通知模块 — 飞书 webhook 推送."""

import json
import logging
from datetime import datetime
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

FEISHU_MAX_BODY = 8000


def notify(title: str, body: str = "", level: str = "info") -> None:
    """通过飞书 webhook 发送通知."""
    from ..config import get_config

    url = get_config().feishu_webhook_url
    if not url:
        return

    tag = {"info": "ℹ️", "warn": "⚠️", "alert": "🚨"}.get(level, "📢")
    now = datetime.now().strftime("%H:%M")
    text = f"{tag} [{now}] {title}"
    if body:
        text += f"\n{body}"
    text = text[:FEISHU_MAX_BODY]

    payload = json.dumps({"msg_type": "text", "content": {"text": text}}).encode()

    try:
        req = Request(url, data=payload, headers={"Content-Type": "application/json"})
        urlopen(req, timeout=5)
        logger.info(f"通知已发送: {title}")
    except Exception as e:
        logger.warning(f"通知失败: {e}")
