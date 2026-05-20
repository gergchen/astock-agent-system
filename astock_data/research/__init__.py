"""Research layer — Eastmoney reports + THS consensus + iwencai NL search."""

from .eastmoney_report import get_reports, download_report_pdf
from .ths_expectation import get_consensus_eps
from .iwencai import semantic_search, IWencaiClient

__all__ = [
    "get_reports",
    "download_report_pdf",
    "get_consensus_eps",
    "semantic_search",
    "IWencaiClient",
]
