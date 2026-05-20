"""Workflow D: New stock rapid research.

Checks: institutional coverage -> valuation -> moat assessment.
"""

from ..market.tencent_finance import get_valuation
from ..research.ths_expectation import get_consensus_eps
from .valuation import full_valuation


def new_stock_research(code: str) -> dict:
    """Quick new-stock diligence check.

    Args:
        code: 6-digit stock code.

    Returns:
        Dict with: covered (是否有机构覆盖), valuation, moat_indicators.
    """
    code = str(code).zfill(6)

    # 1. Check institutional coverage
    consensus = get_consensus_eps(code)
    covered = consensus.get("covered", False)

    # 2. Full valuation
    valuation = full_valuation(code)

    # 3. Basic quality checks
    quotes = get_valuation([code])
    q = quotes.get(code, {})

    return {
        "code": code,
        "name": q.get("name", code),
        "institutional_coverage": covered,
        "analyst_count": valuation.get("analyst_count", 0),
        "valuation": valuation,
        "quality_indicators": {
            "pe_ttm": q.get("pe_ttm", 0),
            "pb": q.get("pb", 0),
            "market_cap_yi": q.get("mcap_yi", 0),
            "has_coverage": covered,
            "coverage_quality": (
                "good" if valuation.get("analyst_count", 0) >= 5
                else "thin" if valuation.get("analyst_count", 0) >= 3
                else "none"
            ),
        },
    }
