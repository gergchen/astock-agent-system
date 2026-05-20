"""Core valuation framework — Forward PE, PEG, PE digestion years, 30x anchor.

Workflow A: Single-stock full valuation (~30 seconds).
"""

import math

from ..market.tencent_finance import get_valuation
from ..research.ths_expectation import get_consensus_eps


def _forward_pe(price: float, eps_forecast: float) -> float:
    """Forward PE = current price / consensus EPS."""
    if eps_forecast <= 0:
        return float("inf")
    return price / eps_forecast


def _calc_peg(pe: float, cagr: float) -> float:
    """PEG = Forward PE / (CAGR * 100).

    PEG < 1   = cheap, 1-1.5 = fair, > 1.5 = expensive.
    """
    if cagr <= 0:
        return float("inf")
    return pe / (cagr * 100)


def _pe_digestion(pe: float, cagr: float, target_pe: float = 30) -> float:
    """Years to digest current PE down to target_pe at given CAGR.

    30x = A-stock growth stock gravity anchor.
    """
    if pe <= target_pe:
        return 0.0
    if cagr <= 0:
        return float("inf")
    return math.log(pe / target_pe) / math.log(1 + cagr)


def full_valuation(code: str) -> dict:
    """Complete single-stock valuation analysis.

    Flow: Live price -> Consensus EPS -> Forward PE / PEG / PE digestion years.

    Args:
        code: 6-digit stock code.

    Returns:
        Dict with price, mcap, pe_ttm, pb, eps_cur, eps_next,
        pe_fwd, cagr_pct, peg, digest_years, analyst_count.
    """
    code = str(code).zfill(6)

    # 1. Tencent real-time valuation
    quotes = get_valuation([code])
    q = quotes.get(code, {})
    price = q.get("price", 0)
    mcap = q.get("mcap_yi", 0)
    pe_ttm = q.get("pe_ttm", 0)
    pb = q.get("pb", 0)
    name = q.get("name", code)

    # 2. Consensus EPS
    consensus = get_consensus_eps(code)
    forecasts = consensus.get("forecasts", [])
    eps_cur = None
    eps_next = None
    analyst_count = 0

    if len(forecasts) >= 1:
        eps_cur = forecasts[0].get("mean_eps")
        analyst_count = forecasts[0].get("analyst_count", 0)
    if len(forecasts) >= 2:
        eps_next = forecasts[1].get("mean_eps")

    # 3. Compute valuation metrics
    pe_fwd = round(_forward_pe(price, eps_cur), 1) if eps_cur else None
    cagr = (eps_next / eps_cur - 1) if (eps_cur and eps_next and eps_cur > 0) else 0
    cagr_pct = round(cagr * 100, 0) if cagr else None

    peg = round(_calc_peg(pe_fwd or float("inf"), cagr), 2) if (pe_fwd and cagr > 0) else None
    digest = round(_pe_digestion(pe_fwd or float("inf"), cagr), 1) if (pe_fwd and cagr > 0) else None

    return {
        "code": code,
        "name": name,
        "price": price,
        "mcap_yi": mcap,
        "pe_ttm": pe_ttm,
        "pb": pb,
        "eps_current": eps_cur,
        "eps_next": eps_next,
        "pe_forward": pe_fwd,
        "cagr_pct": cagr_pct,
        "peg": peg,
        "digest_years": digest,
        "analyst_count": analyst_count,
        "covered": consensus.get("covered", False),
    }
