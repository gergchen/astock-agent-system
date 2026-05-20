"""DeepSeek API 客户端 — Anthropic-compatible Messages API.

支持:
- 自动重试 (指数退避)
- 限流检测与等待
- 连接池复用
"""

import json
import logging
import ssl
import time
import urllib.request
from typing import Any

from ..config import get_config
from ..exceptions import APIError, APIRateLimitError

logger = logging.getLogger(__name__)


class APIClient:
    """LLM API 客户端 (DeepSeek Anthropic-compatible)."""

    def __init__(self):
        self.config = get_config()
        self._ctx = ssl.create_default_context()
        self._ctx.check_hostname = False
        self._ctx.verify_mode = ssl.CERT_NONE

    def _build_request(self, messages: list[dict], max_tokens: int | None = None) -> urllib.request.Request:
        body = json.dumps({
            "model": self.config.llm_model,
            "max_tokens": max_tokens or self.config.llm_max_tokens,
            "messages": messages,
        }).encode("utf-8")

        return urllib.request.Request(
            f"{self.config.llm_base_url}/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.llm_api_key}",
            },
        )

    def call(
        self,
        messages: list[dict],
        max_tokens: int | None = None,
        retries: int | None = None,
    ) -> str:
        """调用 LLM API，返回文本响应.

        Args:
            messages: 消息列表 (user/assistant role)
            max_tokens: 最大 token 数
            retries: 重试次数, None=使用配置默认值

        Returns:
            模型文本响应

        Raises:
            APIError: 调用失败
            APIRateLimitError: 限流
        """
        retries = retries if retries is not None else self.config.agent_max_retries
        last_error = None

        for attempt in range(retries + 1):
            try:
                req = self._build_request(messages, max_tokens)
                resp = urllib.request.urlopen(req, timeout=self.config.agent_timeout, context=self._ctx)
                result = json.loads(resp.read().decode("utf-8"))

                for block in result.get("content", []):
                    if block.get("type") == "text":
                        return block["text"]
                return ""

            except urllib.error.HTTPError as e:
                status = e.code
                if status == 429:
                    retry_after = int(e.headers.get("Retry-After", "5"))
                    logger.warning(f"Rate limited, waiting {retry_after}s (attempt {attempt+1}/{retries+1})")
                    if attempt < retries:
                        time.sleep(retry_after)
                        continue
                    raise APIRateLimitError(f"Rate limit exceeded after {retries+1} attempts") from e
                elif status >= 500:
                    last_error = e
                    if attempt < retries:
                        wait = 2 ** attempt
                        logger.warning(f"Server error {status}, retrying in {wait}s (attempt {attempt+1}/{retries+1})")
                        time.sleep(wait)
                        continue
                    raise APIError(f"Server error {status}: {e.reason}") from e
                else:
                    raise APIError(f"HTTP {status}: {e.reason}") from e

            except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
                last_error = e
                if attempt < retries:
                    wait = 2 ** attempt
                    logger.warning(f"Network error, retrying in {wait}s (attempt {attempt+1}/{retries+1})")
                    time.sleep(wait)
                    continue
                raise APIError(f"Network error: {e}") from e

            except json.JSONDecodeError as e:
                raise APIError(f"Invalid JSON response: {e}") from e

        raise APIError(f"All {retries+1} attempts failed: {last_error}")

    def call_with_tools(
        self,
        messages: list[dict],
        tools: list[dict],
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """调用 LLM API 并支持 tool_use.

        Returns:
            完整响应 dict (含 content 和 tool_use blocks)
        """
        body = json.dumps({
            "model": self.config.llm_model,
            "max_tokens": max_tokens or self.config.llm_max_tokens,
            "messages": messages,
            "tools": tools,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.config.llm_base_url}/v1/messages",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.llm_api_key}",
            },
        )

        try:
            resp = urllib.request.urlopen(req, timeout=self.config.agent_timeout, context=self._ctx)
            return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise APIError(f"HTTP {e.code}: {e.reason}") from e


import socket

_client: APIClient | None = None


def get_client() -> APIClient:
    global _client
    if _client is None:
        _client = APIClient()
    return _client
