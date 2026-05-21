"""通知模块 — 飞书 webhook 推送，盘后自动静默."""

import json
import logging
from datetime import datetime, timedelta, time as dt_time
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

FEISHU_MAX_BODY = 8000

# 通知窗口（北京时间）— 盘中仅 9:00-15:00，收盘后完全不发
NOTIFY_WINDOW_START = dt_time(9, 0)
NOTIFY_WINDOW_END = dt_time(15, 0)

# 系统活跃窗口 — 收盘即休眠
SYSTEM_ACTIVE_END = dt_time(15, 5)


def is_notify_time() -> bool:
    """判断当前是否允许推送通知（交易日 9:00-15:00）。"""
    now = datetime.now()
    if now.weekday() >= 5:
        return False
    return NOTIFY_WINDOW_START <= now.time() <= NOTIFY_WINDOW_END


def sleep_until_next_session() -> float:
    """计算到下一个交易时段（8:55）的休眠秒数。

    盘后直接深度休眠到次日盘前，避免空转消耗 API/Token。
    当前已在 9:00-15:05 活跃窗口内返回 0。
    """
    now = datetime.now()

    # 交易日 + 在活跃窗口内 → 不休眠
    if now.weekday() < 5 and dt_time(9, 0) <= now.time() <= SYSTEM_ACTIVE_END:
        return 0

    # 跳到下一天 9:00（对齐自动开机时间）
    target = now.replace(hour=9, minute=0, second=0, microsecond=0) + timedelta(days=1)
    # 跳过周末
    while target.weekday() >= 5:
        target += timedelta(days=1)

    return max(0, (target - now).total_seconds())


SOURCE_TAG = "[台式机]"

def notify(title: str, body: str = "", level: str = "info", force: bool = False) -> None:
    """通过飞书 webhook 发送通知，同时写入本地告警审计文件.

    Args:
        force: 为 True 时绕过交易时间限制，用于系统下线/异常等关键通知。
    """
    # Always log alert to local audit file
    _file_alert(title, body, level)

    if not force and not is_notify_time():
        return

    # info 级别的系统消息（上线/下线/健康检查）只写本地日志，不推飞书
    if not force and level == "info":
        return

    from ..config import get_config

    url = get_config().feishu_webhook_url
    if not url:
        return

    tag = {"info": "ℹ️", "warn": "⚠️", "alert": "🚨"}.get(level, "📢")
    now = datetime.now().strftime("%H:%M")
    text = f"{SOURCE_TAG} {tag} [{now}] {title}"
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


def _file_alert(title: str, body: str, level: str) -> None:
    """Append alert to local audit file (always, regardless of trading hours)."""
    try:
        import json as _json
        from pathlib import Path

        alert_file = Path("data/alerts/alert.log")
        alert_file.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.now().isoformat(),
            "level": level,
            "title": title,
            "body": body,
            "source": "managed_agents",
        }
        with open(alert_file, "a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass  # never let audit logging break the main flow
