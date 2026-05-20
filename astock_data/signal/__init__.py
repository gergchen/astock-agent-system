"""Signal layer — 同花顺 hotspots + Northbound capital flow."""

from .ths_hotspot import get_hot_stocks, get_hot_sectors
from .northbound import get_northbound_realtime, get_northbound_history

__all__ = [
    "get_hot_stocks",
    "get_hot_sectors",
    "get_northbound_realtime",
    "get_northbound_history",
]
