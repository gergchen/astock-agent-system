"""抖音监控状态持久化 — JSON 文件存储，线程安全. """

import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import get_config

logger = logging.getLogger(__name__)


class StateStore:
    """基于 JSON 文件的持久化状态存储 (线程安全)."""

    def __init__(self, path: Path | None = None):
        self._lock = threading.Lock()
        self._path = path or (get_config().data_dir / "douyin" / "state.json")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {}
        self._load()

    def _load(self):
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning(f"状态文件损坏, 重置: {e}")
                self._data = {}
        self._data.setdefault("version", 1)
        self._data.setdefault("users", {})
        self._data.setdefault("global_stats", {
            "total_analyzed": 0,
            "total_alerts": 0,
            "last_run_time": "",
        })

    def _save(self):
        try:
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.error(f"状态持久化失败: {e}")

    # ─── 用户状态 ─────────────────────────────────────────

    def get_user_state(self, sec_user_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._data["users"].get(sec_user_id, {
                "nickname": "",
                "last_video_id": "",
                "last_check_time": "",
                "checked_video_ids": [],
                "last_alert_time": "",
                "enabled": True,
            }))

    def update_user_state(self, sec_user_id: str, **kwargs):
        with self._lock:
            user = self._data["users"].setdefault(sec_user_id, {})
            user.setdefault("checked_video_ids", [])
            for k in ("nickname", "last_video_id", "last_check_time",
                       "last_alert_time", "enabled"):
                if k in kwargs:
                    user[k] = kwargs[k]
            self._save()

    def is_video_checked(self, sec_user_id: str, video_id: str) -> bool:
        with self._lock:
            checked = self._data["users"].get(sec_user_id, {}).get("checked_video_ids", [])
            return video_id in checked

    def mark_video_checked(self, sec_user_id: str, video_id: str):
        with self._lock:
            user = self._data["users"].setdefault(sec_user_id, {})
            checked = user.setdefault("checked_video_ids", [])
            if video_id not in checked:
                checked.append(video_id)
                if len(checked) > 500:
                    user["checked_video_ids"] = checked[-500:]
            self._save()

    def get_new_videos(self, sec_user_id: str, video_ids: list[str]) -> list[str]:
        """从 video_ids 中过滤出未处理的新视频."""
        with self._lock:
            checked = set(self._data["users"].get(sec_user_id, {}).get("checked_video_ids", []))
            return [vid for vid in video_ids if vid not in checked]

    # ─── 全局统计 ─────────────────────────────────────────

    def increment_analyzed(self):
        with self._lock:
            self._data["global_stats"]["total_analyzed"] = \
                self._data["global_stats"].get("total_analyzed", 0) + 1
            self._save()

    def increment_alerts(self):
        with self._lock:
            self._data["global_stats"]["total_alerts"] = \
                self._data["global_stats"].get("total_alerts", 0) + 1
            self._save()

    def set_last_run(self, timestamp: str | None = None):
        with self._lock:
            self._data["global_stats"]["last_run_time"] = \
                timestamp or datetime.now().isoformat()
            self._save()

    def all_users(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return dict(self._data.get("users", {}))

    def enabled_users(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {
                uid: s for uid, s in self._data.get("users", {}).items()
                if s.get("enabled", True)
            }

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._data.get("global_stats", {}))
