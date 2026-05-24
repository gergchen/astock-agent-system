"""Douyin_TikTok_Download_API 的 REST 客户端 (httpx).

依赖: httpx (需在 requirements.txt 中添加)
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from ..config import get_config

logger = logging.getLogger(__name__)

_API_TIMEOUT = 15
_MAX_RETRIES = 3


class DouyinAPIClientError(Exception):
    """Douyin API 调用异常基类."""


class DouyinAPIRateLimit(DouyinAPIClientError):
    """触发频率限制."""


class DouyinAPI:
    """抖音 API 客户端.

    使用 httpx 实现异步 HTTP 请求，支持指数退避重试。
    """

    def __init__(self, base_url: str | None = None):
        cfg = get_config()
        self.base_url = (base_url or cfg.douyin_api_base_url).rstrip("/")
        self._client = httpx.Client(timeout=_API_TIMEOUT, follow_redirects=True)

    def _request(self, method: str, path: str, params: dict | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            try:
                resp = self._client.request(method, url, params=params)
                resp.raise_for_status()
                data = resp.json()

                # API 层错误码检查
                if isinstance(data, dict):
                    code = data.get("code", 0)
                    if code != 0 and code != 200:
                        msg = data.get("message", data.get("msg", "unknown"))
                        raise DouyinAPIClientError(f"API error {code}: {msg}")

                return data

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    wait = 2 ** attempt * 5
                    logger.warning(f"Douyin API 限流, 等待 {wait}s")
                    time.sleep(wait)
                    last_error = DouyinAPIRateLimit(f"Rate limited: {e}")
                    continue
                raise DouyinAPIClientError(f"HTTP {e.response.status_code}") from e

            except (httpx.ConnectError, httpx.TimeoutException) as e:
                if attempt < _MAX_RETRIES - 1:
                    wait = 2 ** attempt
                    logger.warning(f"Douyin API 连接失败, 重试 {attempt+1}/{_MAX_RETRIES}: {e}")
                    time.sleep(wait)
                    last_error = e
                    continue
                raise DouyinAPIClientError(f"连接失败 (重试{_MAX_RETRIES}次): {e}") from e

        raise DouyinAPIClientError(f"请求失败: {last_error}") from last_error

    def _get(self, path: str, params: dict | None = None) -> dict[str, Any]:
        return self._request("GET", path, params)

    # ─── 核心业务方法 ────────────────────────────────────────

    def get_user_info(self, sec_user_id: str) -> dict[str, Any]:
        """获取用户主页信息."""
        return self._get("/api/douyin/web/handler_user_profile", {
            "sec_user_id": sec_user_id,
        })

    def get_user_videos(
        self, sec_user_id: str, cursor: int = 0, max_count: int = 20
    ) -> dict[str, Any]:
        """获取用户主页作品列表."""
        return self._get("/api/douyin/web/fetch_user_post_videos", {
            "sec_user_id": sec_user_id,
            "max_cursor": str(cursor),
            "count": str(min(max_count, 35)),
        })

    def get_video_data(self, video_id: str) -> dict[str, Any]:
        """获取单个视频的详细信息."""
        return self._get("/api/douyin/web/fetch_one_video", {
            "aweme_id": video_id,
        })

    def hybrid_parse(self, url: str, minimal: bool = False) -> dict[str, Any]:
        """混合解析: 自动识别平台."""
        return self._get("/api/hybrid/video_data", {
            "url": url,
            "minimal": str(minimal).lower(),
        })

    def get_video_comments(self, aweme_id: str, cursor: int = 0) -> dict[str, Any]:
        """获取视频评论列表."""
        return self._get("/api/douyin/web/fetch_video_comments", {
            "aweme_id": aweme_id,
            "cursor": str(cursor),
            "count": "20",
        })

    def extract_sec_user_id(self, url: str) -> dict[str, Any]:
        """从分享链接提取用户 sec_user_id."""
        return self._get("/api/douyin/web/get_sec_user_id", {"url": url})

    def get_aweme_id(self, url: str) -> dict[str, Any]:
        """从分享链接提取作品 aweme_id (通过 API)."""
        return self._get("/api/douyin/web/get_aweme_id", {"url": url})

    @staticmethod
    def resolve_short_url(url: str) -> str | None:
        """解析抖音短链接, 返回重定向后的完整 URL."""
        import re
        try:
            resp = httpx.get(url, follow_redirects=True, timeout=10)
            resolved = str(resp.url)
            # 从 URL 中提取 aweme_id: /video/123 或 /note/123
            m = re.search(r'/(?:video|note)/(\d+)', resolved)
            if m:
                return m.group(1)
        except Exception:
            pass
        return None

    def health_check(self) -> bool:
        """检查 API 是否在线."""
        try:
            resp = self._client.get(f"{self.base_url}/docs", timeout=5)
            return resp.status_code == 200
        except Exception:
            return False

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    # ─── 工具: 从 API 原始响应提取标准字段 ─────────────────

    @staticmethod
    def extract_video_list(raw: dict[str, Any]) -> list[dict[str, Any]]:
        """从 fetch_user_post_videos 原始响应中提取作品列表."""
        # 尝试常见的嵌套路径
        data = raw.get("data", raw)
        if isinstance(data, dict):
            return data.get("aweme_list") or data.get("list") or []
        return []

    @staticmethod
    def extract_aweme_id(item: dict[str, Any]) -> str:
        """从作品 item 中提取 aweme_id."""
        aweme_id = item.get("aweme_id", "")
        if aweme_id:
            return str(aweme_id)
        video = item.get("video", {}) or {}
        return str(video.get("vid", ""))

    @staticmethod
    def extract_has_more(raw: dict[str, Any]) -> bool:
        """判断是否还有更多数据."""
        data = raw.get("data", raw)
        if isinstance(data, dict):
            return bool(data.get("has_more", False))
        return False

    @staticmethod
    def extract_max_cursor(raw: dict[str, Any]) -> int:
        """获取下一页游标."""
        data = raw.get("data", raw)
        if isinstance(data, dict):
            return int(data.get("max_cursor", 0))
        return 0
