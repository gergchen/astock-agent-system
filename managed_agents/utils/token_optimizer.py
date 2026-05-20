"""Token Optimizer — RTK 风格数据压缩，削减 LLM 调用 Token 消耗.

在数据送入 LLM 之前自动压缩 JSON payload：
- 截断长字符串
- 去除空字段/冗余键
- 去重列表项
- Token 预算控制

预期节省 40-70% Token。
"""

import json
import logging
from typing import Any

from ..sessions.compaction import estimate_tokens, TOKENS_PER_CHAR

logger = logging.getLogger(__name__)

# 默认压缩参数
DEFAULT_MAX_STRING = 300      # 单字段最大字符数
DEFAULT_MAX_LIST = 10         # 列表最大条目数
DEFAULT_MAX_TOKENS = 6000     # 压缩后最大 token 数（留给 LLM 足够空间做分析）


def _truncate_strings(obj: Any, max_len: int = DEFAULT_MAX_STRING) -> Any:
    """递归截断字符串字段."""
    if isinstance(obj, str):
        if len(obj) > max_len:
            return obj[:max_len] + "..."
        return obj
    elif isinstance(obj, dict):
        return {k: _truncate_strings(v, max_len) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_truncate_strings(item, max_len) for item in obj]
    else:
        return obj


def _trim_lists(obj: Any, max_items: int = DEFAULT_MAX_LIST) -> Any:
    """递归裁剪过长的列表."""
    if isinstance(obj, list):
        if len(obj) > max_items:
            obj = obj[:max_items]
        return [_trim_lists(item, max_items) for item in obj]
    elif isinstance(obj, dict):
        return {k: _trim_lists(v, max_items) for k, v in obj.items()}
    else:
        return obj


def _strip_empty(obj: Any) -> Any:
    """递归删除空值、空字符串、空列表."""
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            stripped = _strip_empty(v)
            if stripped is not None and stripped != "" and stripped != [] and stripped != {}:
                cleaned[k] = stripped
        return cleaned
    elif isinstance(obj, list):
        cleaned = [_strip_empty(item) for item in obj]
        cleaned = [item for item in cleaned
                    if item is not None and item != "" and item != [] and item != {}]
        return cleaned
    else:
        return obj


def _deduplicate_list(obj: Any) -> Any:
    """递归去除列表中的重复项（基于 title/content 前 80 字符）."""
    if isinstance(obj, list):
        if all(isinstance(item, dict) for item in obj):
            seen = set()
            unique = []
            for item in obj:
                # 用 title 或第一个值做去重标记
                key = item.get("title") or item.get("name") or json.dumps(item, ensure_ascii=False, default=str)[:80]
                if key not in seen:
                    seen.add(key)
                    unique.append(item)
            return unique
        return obj
    elif isinstance(obj, dict):
        return {k: _deduplicate_list(v) for k, v in obj.items()}
    else:
        return obj


def compress(data: dict, max_tokens: int = DEFAULT_MAX_TOKENS,
             max_string: int = DEFAULT_MAX_STRING,
             max_list: int = DEFAULT_MAX_LIST) -> dict:
    """全面压缩数据负载。

    Args:
        data: 原始数据字典
        max_tokens: 目标最大 token 数
        max_string: 单字段最大字符数
        max_list: 列表最大条目数

    Returns:
        压缩后的数据字典
    """
    original = data

    # Step 1: 去除空字段
    data = _strip_empty(data)

    # Step 2: 截断长字符串
    data = _truncate_strings(data, max_len=max_string)

    # Step 3: 裁剪长列表
    data = _trim_lists(data, max_items=max_list)

    # Step 4: 去重
    data = _deduplicate_list(data)

    # Step 5: 如果仍超过预算，进一步压缩
    serialized = json.dumps(data, ensure_ascii=False, default=str)
    current_chars = len(serialized)
    current_tokens = int(current_chars * TOKENS_PER_CHAR)

    if current_tokens > max_tokens:
        # 递进压缩：逐步缩短 max_string 和 max_list
        reductions = [
            (200, 8), (150, 6), (100, 5), (80, 3),
        ]
        for s_len, l_len in reductions:
            data = _truncate_strings(data, max_len=s_len)
            data = _trim_lists(data, max_items=l_len)
            serialized = json.dumps(data, ensure_ascii=False, default=str)
            if int(len(serialized) * TOKENS_PER_CHAR) <= max_tokens:
                break

    original_chars = len(json.dumps(original, ensure_ascii=False, default=str))
    final_chars = len(json.dumps(data, ensure_ascii=False, default=str))
    savings = int((1 - final_chars / max(original_chars, 1)) * 100)

    logger.info(
        f"Token Optimizer: {original_chars}→{final_chars} chars "
        f"({int(original_chars * TOKENS_PER_CHAR)}→{int(final_chars * TOKENS_PER_CHAR)} tokens, "
        f"-{savings}%)"
    )

    return data
