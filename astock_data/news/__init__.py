"""News layer — Eastmoney stock/global news + 财联社 flash news + International geopolitics."""

from .eastmoney_news import get_stock_news, get_global_news
from .cls_news import get_flash_news
from .global_news import search_geopolitical_news, get_top_headlines, GEOPOLITICAL_PRESETS

__all__ = [
    "get_stock_news",
    "get_global_news",
    "get_flash_news",
    "search_geopolitical_news",
    "get_top_headlines",
    "GEOPOLITICAL_PRESETS",
]
