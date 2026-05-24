"""抖音视频内容分析器.

两条路径:
1. 文本分析 — 分析视频描述文案 (DeepSeek 文本模型)
2. 视觉分析 — 下载封面图 + Vision API (Claude API, 需配置)

保护机制:
- asyncio.Semaphore 控制并发
- 令牌桶限频
- OOM 防护: max_tokens + 响应长度截断
"""

import json
import logging
import os
import re
import time
import threading
from datetime import datetime
from typing import Any

from ..api.client import get_client
from ..config import get_config
from .models import DouyinVideo, ProductInfo, AnalysisResult

logger = logging.getLogger(__name__)

# ─── 并发控制 ────────────────────────────────────────────────────

_analysis_semaphore: threading.Semaphore | None = None
_rate_limit_lock = threading.Lock()
_last_request_times: list[float] = []


def _get_semaphore() -> threading.Semaphore:
    global _analysis_semaphore
    if _analysis_semaphore is None:
        cfg = get_config()
        _analysis_semaphore = threading.Semaphore(cfg.douyin_max_concurrent)
    return _analysis_semaphore


def _check_rate_limit():
    """令牌桶: 每分钟最多 douyin_rate_limit 次."""
    cfg = get_config()
    max_per_minute = cfg.douyin_rate_limit
    with _rate_limit_lock:
        now = time.time()
        # 清除 60 秒前的记录
        cutoff = now - 60
        global _last_request_times
        _last_request_times = [t for t in _last_request_times if t > cutoff]

        if len(_last_request_times) >= max_per_minute:
            sleep_time = _last_request_times[0] + 60 - now
            if sleep_time > 0:
                logger.info(f"限频: 等待 {sleep_time:.1f}s")
                time.sleep(sleep_time)
            # 重试清理
            _last_request_times = [t for t in _last_request_times if t > time.time() - 60]

        _last_request_times.append(now)


# ─── Prompt 模板 ─────────────────────────────────────────────────

TEXT_ANALYSIS_PROMPT = """你是一个抖音带货商品识别专家。分析以下视频信息，判断是否涉及带货或商品推广。

视频文案:
{desc}

互动数据:
- 点赞: {like_count}
- 评论: {comment_count}
- 分享: {share_count}

请判断该视频是否在推广/带货商品。如果是，提取结构化信息并以 JSON 格式返回:

{{
    "has_product": true/false,
    "brand": "品牌名称(若无则为空)",
    "product_name": "产品名称(若无则为空)",
    "category": "美妆/食品/3C/服饰/家居/汽车/母婴/其他/无",
    "price": "价格(原文,若无则为空)",
    "confidence": 0.0-1.0,
    "reasoning": "判断依据简述(20字内)"
}}

判断标准:
- 文案含"链接""小黄车""橱窗""下单""购买""优惠"等词 → 带货
- 含具体品牌名+产品名 → 带货或推广
- "好物推荐""开箱""测评""实测" → 带货可能性高
- 纯娱乐/知识分享不算法带货
- 没有明确商品信息则 has_product=false

只返回 JSON，不要其他文字。"""


def _build_analysis_text(video: DouyinVideo) -> str:
    return TEXT_ANALYSIS_PROMPT.format(
        desc=(video.desc or "")[:500],
        like_count=video.like_count,
        comment_count=video.comment_count,
        share_count=video.share_count,
    )


def _parse_product_json(llm_response: str) -> ProductInfo | None:
    """从 LLM 响应中解析结构化 JSON."""
    # 提取 ```json ... ``` 块
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', llm_response, re.DOTALL)
    json_str = json_match.group(1) if json_match else llm_response.strip()

    # 找第一个 { 和最后一个 }
    start = json_str.find("{")
    end = json_str.rfind("}")
    if start >= 0 and end > start:
        json_str = json_str[start:end + 1]

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        logger.warning(f"LLM 返回无法解析: {llm_response[:200]}")
        return None

    if not data.get("has_product"):
        return None

    confidence = float(data.get("confidence", 0))
    if confidence < 0.3:
        return None

    return ProductInfo(
        has_product=True,
        brand=str(data.get("brand", "")),
        product_name=str(data.get("product_name", "")),
        category=str(data.get("category", "")),
        price=str(data.get("price", "")),
        confidence=confidence,
        raw_text=str(data.get("reasoning", "")),
    )


def analyze_video_text(video: DouyinVideo) -> AnalysisResult:
    """使用 DeepSeek 文本模型分析视频文案，识别带货商品.

    线程安全: 使用信号量控制并发 + 令牌桶限频.
    """
    sem = _get_semaphore()
    acquired = sem.acquire(blocking=True, timeout=120)
    if not acquired:
        logger.warning(f"分析并发排队超时: {video.video_id}")
        return AnalysisResult(video=video, analyzed_at=datetime.now().isoformat())

    try:
        _check_rate_limit()
        prompt = _build_analysis_text(video)

        try:
            client = get_client()
            # max_tokens 控制在合理范围，防止 OOM
            response = client.call(
                [{"role": "user", "content": prompt}],
                max_tokens=1024,
            )
        except Exception as e:
            logger.error(f"LLM 调用失败 {video.video_id}: {e}")
            return AnalysisResult(video=video, analyzed_at=datetime.now().isoformat())

        # 响应长度保护
        if len(response) > 10000:
            logger.warning(f"LLM 响应过长 ({len(response)} chars), 截断")
            response = response[:10000]

        product = _parse_product_json(response)
        return AnalysisResult(
            video=video,
            product=product,
            analyzed_at=datetime.now().isoformat(),
        )

    finally:
        sem.release()


def analyze_video_with_vision(video: DouyinVideo, image_url: str | None = None) -> AnalysisResult:
    """使用 Vision API 分析视频封面图 + 文案.

    使用独立的 Claude API 客户端 (非 DeepSeek).
    需要配置 CLAUDE_API_KEY 和 CLAUDE_API_BASE_URL.
    """
    cfg = get_config()
    if not cfg.douyin_enable_vision:
        logger.info("视觉分析未启用, 回退到文本分析")
        return analyze_video_text(video)

    image_url = image_url or video.cover_url
    if not image_url:
        logger.info("无封面图, 回退到文本分析")
        return analyze_video_text(video)

    claude_api_key = cfg.douyin_vision_api_key or os.environ.get("CLAUDE_API_KEY", "")
    if not claude_api_key:
        logger.warning("未配置 CLAUDE_API_KEY, 回退到文本分析")
        return analyze_video_text(video)

    # ─── Vision prompt ───
    prompt = (
        "分析这张图片中的商品信息。请识别:\n"
        "1. 是否有商品/产品出镜\n"
        "2. 品牌名称\n"
        "3. 产品名称\n"
        "4. 品类(美妆/食品/3C/服饰/家居/汽车/母婴/其他)\n"
        "5. 价格(如果图片中有显示)\n"
        "6. 是否有带货意图(展示商品细节/使用效果/促销)\n\n"
        f"额外参考 - 视频文案: {video.desc[:300]}\n\n"
        "以 JSON 格式返回:\n"
        '{"has_product": bool, "brand": "", "product_name": "", '
        '"category": "", "price": "", "confidence": 0.0, "reasoning": ""}'
    )

    sem = _get_semaphore()
    acquired = sem.acquire(blocking=True, timeout=120)
    if not acquired:
        return AnalysisResult(video=video, analyzed_at=datetime.now().isoformat())

    try:
        _check_rate_limit()
        # 调用 Claude API
        from anthropic import Anthropic
        client = Anthropic(api_key=claude_api_key)

        msg = client.messages.create(
            model=cfg.douyin_vision_model or "claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image", "source": {"type": "url", "url": image_url}},
                ],
            }],
        )

        response = msg.content[0].text if msg.content else ""
        product = _parse_product_json(response)
        return AnalysisResult(
            video=video,
            product=product,
            analyzed_at=datetime.now().isoformat(),
        )

    except Exception as e:
        logger.error(f"Vision 分析失败 {video.video_id}: {e}")
        return AnalysisResult(video=video, analyzed_at=datetime.now().isoformat())
    finally:
        sem.release()
