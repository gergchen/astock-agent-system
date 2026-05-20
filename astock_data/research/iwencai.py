"""iwencai NL semantic search for research reports.

Requires API key (apply at https://www.iwencai.com/skillhub).
SkillHub 2.0 requires X-Claw-* headers.

Uniquely capable of cross-topic NL search across all A-stock research.
"""

import json
import os
import secrets

import requests

from ..config import get_config
from ..utils.rate_limiter import rate_limit
from ..utils.retry import retry
from ..exceptions import IWencaiError, ConfigError


class IWencaiClient:
    """Client for iwencai OpenAPI (SkillHub 2.0)."""

    def __init__(self, api_key: str | None = None, base_url: str | None = None):
        config = get_config()
        self.api_key = api_key or config.iwencai_api_key
        self.base_url = base_url or config.iwencai_base_url

    def _check_key(self):
        if not self.api_key:
            raise ConfigError(
                "iwencai API key not configured. "
                "Set IWENCAI_API_KEY environment variable or apply at "
                "https://www.iwencai.com/skillhub"
            )

    def _claw_headers(self, call_type: str = "normal") -> dict:
        return {
            "X-Claw-Call-Type": call_type,
            "X-Claw-Skill-Id": "report-search",
            "X-Claw-Skill-Version": "2.0.0",
            "X-Claw-Plugin-Id": "none",
            "X-Claw-Plugin-Version": "none",
            "X-Claw-Trace-Id": secrets.token_hex(32),
        }

    @retry()
    @rate_limit("iwencai")
    def search(
        self,
        query: str,
        channel: str = "report",
        size: int = 50,
    ) -> list[dict]:
        """Semantic search across channels.

        Args:
            query: Natural language query.
            channel: "report", "announcement", or "news".
            size: Results per query (max ~50).

        Returns:
            List of article dicts.
        """
        self._check_key()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self._claw_headers(),
        }
        payload = {
            "channels": [channel],
            "app_id": "AIME_SKILL",
            "query": query,
            "size": size,
        }
        try:
            r = requests.post(
                f"{self.base_url}/v1/comprehensive/search",
                json=payload,
                headers=headers,
                timeout=get_config().http_timeout,
            )
        except requests.RequestException as e:
            raise IWencaiError(f"iwencai search failed: {e}") from e

        if r.status_code != 200:
            raise IWencaiError(f"iwencai HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        if data.get("status_code", 0) != 0:
            raise IWencaiError(f"iwencai error: {data.get('status_msg', '')}")
        return data.get("data") or []

    @retry()
    @rate_limit("iwencai")
    def query_data(self, query: str, page: int = 1, limit: int = 50) -> list[dict]:
        """Structured NL data query.

        Example: "贵州茅台 ROE" -> DataFrame-like result rows.
        """
        self._check_key()
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self._claw_headers(),
        }
        payload = {
            "query": query,
            "page": str(page),
            "limit": str(limit),
            "is_cache": "1",
            "expand_index": "true",
        }
        try:
            r = requests.post(
                f"{self.base_url}/v1/query2data",
                json=payload,
                headers=headers,
                timeout=get_config().http_timeout,
            )
        except requests.RequestException as e:
            raise IWencaiError(f"iwencai query failed: {e}") from e

        if r.status_code != 200:
            raise IWencaiError(f"iwencai HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
        if data.get("status_code", 0) != 0:
            raise IWencaiError(f"iwencai error: {data.get('status_msg', '')}")
        return data.get("datas") or []


def semantic_search(
    query: str,
    channel: str = "report",
    size: int = 50,
    deduplicate: bool = True,
) -> list[dict]:
    """Convenience function: NL search + optional dedup (by uid, keep highest score)."""
    client = IWencaiClient()
    articles = client.search(query=query, channel=channel, size=size)

    if not deduplicate or not articles:
        return articles

    best = {}
    for a in articles:
        uid = a.get("uid", "") or f"{a.get('title','')}|{a.get('publish_date','')}"
        score = float(a.get("score", 0))
        if uid not in best or score > float(best[uid].get("score", 0)):
            best[uid] = a

    return sorted(
        best.values(),
        key=lambda x: x.get("publish_date", ""),
        reverse=True,
    )
