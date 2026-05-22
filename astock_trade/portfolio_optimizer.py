"""Portfolio Optimization — risk budgeting, sector exposure constraints.

Replaces purely LLM-based allocation decisions with quantitative optimization.

Two modes:
1. RiskBudget — allocate based on risk parity / volatility weighting
2. SectorConstrained — optimize with sector exposure limits

All calculations are deterministic. No LLM dependency.
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class PortfolioAllocation:
    """Optimized portfolio allocation result."""
    cash_pct: float                  # recommended cash ratio
    positions: dict[str, float]      # symbol → target_pct of total assets
    sector_exposure: dict[str, float] = field(default_factory=dict)
    expected_vol_pct: float = 0.0
    risk_contribution: dict[str, float] = field(default_factory=dict)
    constraints_satisfied: bool = True
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "cash_pct": self.cash_pct,
            "positions": self.positions,
            "sector_exposure": self.sector_exposure,
            "expected_vol_pct": self.expected_vol_pct,
            "risk_contribution": self.risk_contribution,
            "constraints_satisfied": self.constraints_satisfied,
            "warnings": self.warnings,
        }


@dataclass
class StockInfo:
    """Basic stock characteristics for optimization."""
    symbol: str
    sector: str = ""
    volatility_pct: float = 0.30   # annualized volatility estimate
    momentum: float = 0.0          # recent return
    market_cap: float = 0.0        # for liquidity filter
    price: float = 0.0


class PortfolioOptimizer:
    """Quantitative portfolio optimizer with risk budgeting and sector constraints.

    Usage:
        optimizer = PortfolioOptimizer(
            max_single_pct=0.20,
            max_sector_pct=0.30,
            max_total_pct=0.70,
        )
        candidates = [
            StockInfo("600519", sector="食品饮料", volatility_pct=0.25),
            StockInfo("000858", sector="食品饮料", volatility_pct=0.28),
            StockInfo("002230", sector="人工智能", volatility_pct=0.40),
        ]
        allocation = optimizer.optimize(candidates, total_assets=1_000_000)
    """

    def __init__(
        self,
        max_single_pct: float = 0.20,
        max_sector_pct: float = 0.30,
        max_total_pct: float = 0.70,
        min_cash_pct: float = 0.30,
        max_count: int = 8,
        risk_free_rate: float = 0.02,
    ):
        self.max_single_pct = max_single_pct
        self.max_sector_pct = max_sector_pct
        self.max_total_pct = max_total_pct
        self.min_cash_pct = min_cash_pct
        self.max_count = max_count
        self.risk_free_rate = risk_free_rate

    def optimize(
        self,
        candidates: list[StockInfo],
        total_assets: float,
        regime_risk_mult: float = 1.0,
    ) -> PortfolioAllocation:
        """Run portfolio optimization on candidate stocks.

        Args:
            candidates: List of candidate stocks with characteristics.
            total_assets: Total portfolio value for position sizing.
            regime_risk_mult: Risk multiplier from RegimeEngine (0.0~1.0).

        Returns:
            PortfolioAllocation with target percentages and positions.
        """
        if not candidates:
            return PortfolioAllocation(
                cash_pct=1.0, positions={},
                constraints_satisfied=True,
                warnings=["No candidates provided — 100% cash"],
            )

        n = len(candidates)
        warnings: list[str] = []

        # ── Step 1: Score candidates ────────────────────────
        scores = self._score_candidates(candidates)
        ranked = sorted(zip(candidates, scores), key=lambda x: -x[1])

        # ── Step 2: Apply diversification cap ───────────────
        max_stocks = min(self.max_count, n)
        selected = ranked[:max_stocks]

        # ── Step 3: Risk-budget weight allocation ───────────
        raw_alloc = self._risk_budget_allocation(selected, regime_risk_mult)

        # ── Step 4: Sector exposure constraints ─────────────
        constrained_alloc = self._apply_sector_constraints(selected, raw_alloc, warnings)

        # ── Step 5: Cap single positions ────────────────────
        capped_alloc = self._cap_single_positions(selected, constrained_alloc, warnings)

        # ── Step 6: Scale to total exposure limit ───────────
        total_pct = sum(capped_alloc.values())
        max_allowed = self.max_total_pct * regime_risk_mult

        if total_pct > max_allowed:
            scale = max_allowed / total_pct
            capped_alloc = {k: v * scale for k, v in capped_alloc.items()}
            warnings.append(f"Scaled positions by {scale:.2f} to meet total exposure limit ({max_allowed:.0%})")
            total_pct = max_allowed

        cash_pct = round(1.0 - total_pct, 4)
        if cash_pct < self.min_cash_pct * regime_risk_mult:
            # Force more cash
            excess = self.min_cash_pct * regime_risk_mult - cash_pct
            scale = (total_pct - excess) / total_pct if total_pct > 0 else 0
            capped_alloc = {k: v * scale for k, v in capped_alloc.items()}
            cash_pct = 1.0 - sum(capped_alloc.values())
            warnings.append(f"Forced cash to {cash_pct:.1%} (minimum {self.min_cash_pct:.0%})")

        # ── Build allocation dict ───────────────────────────
        positions = {}
        risk_contrib: dict[str, float] = {}
        sector_exp: dict[str, float] = {}

        for (stock, _), pct in zip(selected, [capped_alloc.get(i, 0) for i in range(len(selected))]):
            if pct > 0.001:  # ignore dust
                sym = stock.symbol
                positions[sym] = round(pct, 4)
                # Risk contribution = weight * volatility
                risk_contrib[sym] = round(pct * stock.volatility_pct, 6)
                sector_exp[stock.sector] = sector_exp.get(stock.sector, 0) + pct

        # Expected portfolio volatility (simplified: weighted avg vol)
        total_weight = sum(pct for _, pct in zip(selected, [capped_alloc.get(i, 0) for i in range(len(selected))]))
        exp_vol = 0.0
        if total_weight > 0 and selected:
            weights = [capped_alloc.get(i, 0) / total_weight for i in range(len(selected))]
            vols = [s[0].volatility_pct for s in selected]
            exp_vol = np.sqrt(np.dot(weights, np.dot(np.eye(len(weights)), weights)) * np.mean(vols) ** 2) * 100

        return PortfolioAllocation(
            cash_pct=round(cash_pct, 4),
            positions=positions,
            sector_exposure=sector_exp,
            expected_vol_pct=round(exp_vol, 2),
            risk_contribution=risk_contrib,
            constraints_satisfied=len(warnings) == 0,
            warnings=warnings,
        )

    def _score_candidates(self, candidates: list[StockInfo]) -> np.ndarray:
        """Score candidates by momentum, volatility-adjusted return."""
        scores = []
        for s in candidates:
            # Higher momentum = better, but penalize excessive volatility
            vol_penalty = s.volatility_pct / 0.30  # normalized to 30% vol baseline
            score = s.momentum / max(vol_penalty, 0.5) if vol_penalty > 0 else s.momentum
            scores.append(max(score, -1.0))  # floor at -1
        return np.array(scores)

    def _risk_budget_allocation(
        self,
        selected: list[tuple[StockInfo, float]],
        risk_mult: float,
    ) -> dict[int, float]:
        """Allocate weights using inverse-volatility (risk parity style)."""
        n = len(selected)
        if n == 0:
            return {}

        vols = np.array([max(s[0].volatility_pct, 0.05) for s in selected])

        # Inverse volatility weighting
        inv_vol = 1.0 / vols
        weights = inv_vol / inv_vol.sum()

        return {i: float(w) for i, w in enumerate(weights)}

    def _apply_sector_constraints(
        self,
        selected: list[tuple[StockInfo, float]],
        alloc: dict[int, float],
        warnings: list[str],
    ) -> dict[int, float]:
        """Cap sector exposure and redistribute excess."""
        sector_limit = self.max_sector_pct

        # Compute sector exposures
        sector_alloc: dict[str, list[int]] = {}
        for i, (stock, _) in enumerate(selected):
            sec = stock.sector or "_unknown"
            sector_alloc.setdefault(sec, []).append(i)

        # Check each sector
        for sec, indices in sector_alloc.items():
            total = sum(alloc.get(i, 0) for i in indices)
            if total > sector_limit:
                scale = sector_limit / total if total > 0 else 1.0
                for i in indices:
                    alloc[i] = alloc.get(i, 0) * scale
                warnings.append(
                    f"Sector '{sec}' exposure capped: {total:.1%} → {total * scale:.1%}"
                )

        return alloc

    def _cap_single_positions(
        self,
        selected: list[tuple[StockInfo, float]],
        alloc: dict[int, float],
        warnings: list[str],
    ) -> dict[int, float]:
        """Cap individual position sizes and redistribute."""
        capped = dict(alloc)
        excess_total = 0.0
        n_capped = 0

        for i in capped:
            if capped[i] > self.max_single_pct:
                excess_total += capped[i] - self.max_single_pct
                capped[i] = self.max_single_pct
                n_capped += 1

        if excess_total > 0 and len(capped) > n_capped:
            # Redistribute to uncapped positions proportionally
            uncapped = {i: capped[i] for i in capped if capped[i] < self.max_single_pct}
            total_uncapped = sum(uncapped.values())
            if total_uncapped > 0 and total_uncapped + excess_total <= 1.0:
                for i in uncapped:
                    capped[i] += excess_total * (uncapped[i] / total_uncapped)
                warnings.append(f"Redistributed {excess_total:.1%} excess from capped positions")

        return capped
