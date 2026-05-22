"""Alpha Evaluation Pipeline — quantitative signal quality assessment.

Evaluates trading signals against forward returns to measure:

- IC (Information Coefficient): rank correlation between signal and forward return
- Rank IC: Spearman rank correlation (more robust)
- IC Decay: how fast predictive power decays over time
- Exposure: % of time the signal has a position
- Turnover: how frequently the signal changes positions
- Sharpe ratio of signal-driven returns

All metrics are computed deterministically from historical data.
No LLM dependency.

Usage:
    evaluator = AlphaEvaluator()
    report = evaluator.evaluate(signals_df, forward_returns_df)
    report.summary()
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def _safe_num(x, default=0.0):
    """Return default if x is NaN or Inf (handles both scalar and array)."""
    if isinstance(x, np.ndarray):
        x = float(x.item()) if x.ndim == 0 else x
    if np.isscalar(x) or isinstance(x, (int, float)):
        return default if (np.isnan(x) or np.isinf(x)) else x
    return x


@dataclass
class AlphaReport:
    """Complete alpha evaluation report for a signal."""
    signal_name: str
    ic_mean: float               # Mean IC
    ic_std: float                # IC standard deviation
    ic_sharpe: float             # IC / IC_std (signal consistency)
    rank_ic_mean: float          # Spearman rank IC
    rank_ic_sharpe: float        # Rank IC / Rank IC_std
    ic_positive_pct: float       # % of periods with positive IC
    ic_decay_1d: float           # IC after 1 day
    ic_decay_5d: float           # IC after 5 days
    ic_decay_10d: float          # IC after 10 days
    ic_half_life_days: float     # How fast IC decays by 50%
    exposure_pct: float          # % of time in the market
    turnover_pct: float          # Daily portfolio turnover
    sharpe_ratio: float          # Signal-driven strategy Sharpe
    total_periods: int
    significant: bool            # IC statistically significant?
    details: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "signal_name": self.signal_name,
            "ic_mean": self.ic_mean,
            "ic_std": self.ic_std,
            "ic_sharpe": self.ic_sharpe,
            "rank_ic_mean": self.rank_ic_mean,
            "rank_ic_sharpe": self.rank_ic_sharpe,
            "ic_positive_pct": self.ic_positive_pct,
            "ic_decay_1d": self.ic_decay_1d,
            "ic_decay_5d": self.ic_decay_5d,
            "ic_decay_10d": self.ic_decay_10d,
            "ic_half_life_days": self.ic_half_life_days,
            "exposure_pct": self.exposure_pct,
            "turnover_pct": self.turnover_pct,
            "sharpe_ratio": self.sharpe_ratio,
            "total_periods": self.total_periods,
            "significant": self.significant,
            "warnings": self.warnings,
        }

    def summary(self) -> str:
        lines = [
            f"Alpha Report: {self.signal_name}",
            f"  IC Mean:       {self.ic_mean:.4f}  (std={self.ic_std:.4f}, sharpe={self.ic_sharpe:.2f})",
            f"  Rank IC Mean:  {self.rank_ic_mean:.4f}  (sharpe={self.rank_ic_sharpe:.2f})",
            f"  IC>0:          {self.ic_positive_pct:.1%}",
            f"  IC Decay:      1d={self.ic_decay_1d:.4f}  5d={self.ic_decay_5d:.4f}  10d={self.ic_decay_10d:.4f}",
            f"  IC Half-life:  {self.ic_half_life_days:.1f} days",
            f"  Exposure:      {self.exposure_pct:.1%}",
            f"  Turnover:      {self.turnover_pct:.1%}",
            f"  Signal Sharpe: {self.sharpe_ratio:.2f}",
            f"  Significant:   {self.significant}",
        ]
        if self.warnings:
            lines.append(f"  Warnings:      {'; '.join(self.warnings)}")
        return "\n".join(lines)


@dataclass
class RankedSignal:
    """A single signal with its rank for IC computation."""
    symbol: str
    date: str
    signal_value: float  # The raw signal (predicted return, score, etc.)
    forward_return_1d: float = 0.0
    forward_return_5d: float = 0.0
    forward_return_10d: float = 0.0
    actual_return: float = 0.0
    hit: bool = False  # Did signal predict direction correctly?


@dataclass
class SignalEvaluationResult:
    """Per-signal evaluation with hit rate."""
    signal_name: str
    total_signals: int
    hit_rate: float       # directional accuracy
    avg_return: float     # average forward return when signal active
    avg_return_when_wrong: float
    best_signal: Optional[dict] = None
    worst_signal: Optional[dict] = None


class AlphaEvaluator:
    """Evaluate signal quality through IC, decay, and turnover analysis.

    Usage:
        evaluator = AlphaEvaluator()
        report = evaluator.evaluate(signals, forward_returns)
        print(report.summary())

    Where:
        signals: list[RankedSignal] or DataFrame with [date, symbol, signal_value]
        forward_returns: DataFrame or dict with forward returns keyed by (date, symbol)
    """

    def __init__(self, min_periods: int = 30):
        self.min_periods = min_periods

    def evaluate(
        self,
        signals: list[RankedSignal],
        signal_name: str = "signal",
    ) -> AlphaReport:
        """Run full alpha evaluation on a list of ranked signals.

        The signals must already have forward_return fields populated.
        """
        if len(signals) < self.min_periods:
            return AlphaReport(
                signal_name=signal_name,
                ic_mean=0.0, ic_std=0.0, ic_sharpe=0.0,
                rank_ic_mean=0.0, rank_ic_sharpe=0.0,
                ic_positive_pct=0.0,
                ic_decay_1d=0.0, ic_decay_5d=0.0, ic_decay_10d=0.0,
                ic_half_life_days=0.0,
                exposure_pct=0.0, turnover_pct=0.0,
                sharpe_ratio=0.0, total_periods=len(signals),
                significant=False,
                warnings=[f"Insufficient signals: {len(signals)} < {self.min_periods}"],
            )

        warnings: list[str] = []

        # Extract arrays
        sig_vals = np.array([s.signal_value for s in signals])
        fwd_1d = np.array([s.forward_return_1d for s in signals])
        fwd_5d = np.array([s.forward_return_5d for s in signals])
        fwd_10d = np.array([s.forward_return_10d for s in signals])

        # Filter NaN/Inf
        valid = np.isfinite(sig_vals) & np.isfinite(fwd_1d)
        if valid.sum() < self.min_periods:
            return AlphaReport(
                signal_name=signal_name,
                ic_mean=0.0, ic_std=0.0, ic_sharpe=0.0,
                rank_ic_mean=0.0, rank_ic_sharpe=0.0,
                ic_positive_pct=0.0,
                ic_decay_1d=0.0, ic_decay_5d=0.0, ic_decay_10d=0.0,
                ic_half_life_days=0.0,
                exposure_pct=0.0, turnover_pct=0.0,
                sharpe_ratio=0.0, total_periods=len(signals),
                significant=False,
                warnings=[f"Only {valid.sum()} valid observations (need {self.min_periods})"],
            )

        sig_vals = sig_vals[valid]
        fwd_1d = fwd_1d[valid]
        fwd_5d = fwd_5d[valid]
        fwd_10d = fwd_10d[valid]

        n = len(sig_vals)

        # ── IC (Pearson correlation) ─────────────────────────
        ic_val = np.corrcoef(sig_vals, fwd_1d)[0, 1] if n > 2 else 0.0
        ic = ic_val if not (np.isnan(ic_val) or np.isinf(ic_val)) else 0.0

        # IC standard error and sharpe
        ic_std = np.sqrt((1 - ic ** 2) / (n - 2)) if n > 2 and abs(ic) < 1 else 0.0
        ic_sharpe = ic / ic_std if ic_std > 0 else 0.0

        # ── Rank IC (Spearman) ──────────────────────────────
        rank_ic_val = 0.0
        p_value = 1.0
        try:
            from scipy.stats import spearmanr
            rank_ic_val, p_value = spearmanr(sig_vals, fwd_1d) if n > 2 else (0.0, 1.0)
        except ImportError:
            pass
        rank_ic = rank_ic_val if not (np.isnan(rank_ic_val) or np.isinf(rank_ic_val)) else 0.0
        rank_ic_std = np.sqrt((1 - rank_ic ** 2) / (n - 2)) if n > 2 and abs(rank_ic) < 1 else 0.0
        rank_ic_sharpe = rank_ic / rank_ic_std if rank_ic_std > 0 else 0.0

        # ── IC positivity rate ──────────────────────────────
        # Use rolling windows of 20 periods
        ic_positive_pct = 0.0
        if n >= 20:
            window_ics = []
            for i in range(n - 19):
                w_sig = sig_vals[i:i + 20]
                w_fwd = fwd_1d[i:i + 20]
                w_ic = np.corrcoef(w_sig, w_fwd)[0, 1] if len(w_sig) > 2 else 0
                window_ics.append(_safe_num(w_ic, 0))
            ic_positive_pct = sum(1 for x in window_ics if x > 0) / len(window_ics) if window_ics else 0

        # ── IC Decay ─────────────────────────────────────────
        ic_1d = ic
        ic_5d_val = np.corrcoef(sig_vals, fwd_5d)[0, 1] if n > 2 else 0.0
        ic_5d = ic_5d_val if not (np.isnan(ic_5d_val) or np.isinf(ic_5d_val)) else 0.0
        ic_10d_val = np.corrcoef(sig_vals, fwd_10d)[0, 1] if n > 2 else 0.0
        ic_10d = ic_10d_val if not (np.isnan(ic_10d_val) or np.isinf(ic_10d_val)) else 0.0

        # Half-life: how many days until IC drops to 50% of 1d IC?
        ic_half_life = 0.0
        if abs(ic_1d) > 0.01:
            # Simple linear interpolation between decay points
            days = np.array([1, 5, 10])
            ics = np.array([abs(ic_1d), abs(ic_5d), abs(ic_10d)])
            half_target = abs(ic_1d) * 0.5
            # Find where IC crosses half
            for i in range(len(days) - 1):
                if ics[i] >= half_target >= ics[i + 1]:
                    if ics[i] - ics[i + 1] > 0:
                        frac = (ics[i] - half_target) / (ics[i] - ics[i + 1])
                        ic_half_life = days[i] + frac * (days[i + 1] - days[i])
                    break
            if ic_half_life == 0 and ics[-1] >= half_target:
                ic_half_life = 10.0  # still above half at 10 days
            elif ic_half_life == 0 and ics[0] < half_target:
                ic_half_life = 0.5  # decays very fast

        # ── Exposure ─────────────────────────────────────────
        # Fraction of signals that are non-zero (active)
        nonzero = np.count_nonzero(np.abs(sig_vals) > 1e-6)
        exposure = nonzero / n if n > 0 else 0.0

        # ── Turnover ─────────────────────────────────────────
        # Approximate: fraction of signals that change sign between periods
        turnover = 0.0
        if n > 1:
            sign_changes = np.sum(
                (sig_vals[1:] * sig_vals[:-1]) < 0
            )
            turnover = sign_changes / (n - 1) if n > 1 else 0.0

        # ── Signal-driven Sharpe ─────────────────────────────
        # Long signals when sig > 0, short when sig < 0
        signal_returns = np.where(sig_vals > 0, fwd_1d, -fwd_1d)
        sharpe = 0.0
        if len(signal_returns) > 1:
            mean_ret = np.mean(signal_returns)
            std_ret = np.std(signal_returns)
            sharpe = mean_ret / std_ret * np.sqrt(252) if std_ret > 0 else 0.0

        # ── Statistical significance ─────────────────────────
        significant = (p_value < 0.05) if n > 2 else False

        return AlphaReport(
            signal_name=signal_name,
            ic_mean=round(float(ic), 4),
            ic_std=round(float(ic_std), 4),
            ic_sharpe=round(float(ic_sharpe), 2),
            rank_ic_mean=round(float(rank_ic), 4),
            rank_ic_sharpe=round(float(rank_ic_sharpe), 2),
            ic_positive_pct=round(float(ic_positive_pct), 4),
            ic_decay_1d=round(float(ic_1d), 4),
            ic_decay_5d=round(float(ic_5d), 4),
            ic_decay_10d=round(float(ic_10d), 4),
            ic_half_life_days=round(float(ic_half_life), 1),
            exposure_pct=round(float(exposure), 4),
            turnover_pct=round(float(turnover), 4),
            sharpe_ratio=round(float(sharpe), 2),
            total_periods=n,
            significant=bool(significant),
            details={
                "p_value": round(float(p_value), 6),
                "valid_observations": n,
                "total_raw_signals": len(signals),
            },
            warnings=warnings,
        )

    def evaluate_signal_list(
        self,
        signals: list[RankedSignal],
        signal_name: str = "signal_group",
    ) -> SignalEvaluationResult:
        """Simpler evaluation: hit rate and average return."""
        if not signals:
            return SignalEvaluationResult(signal_name=signal_name, total_signals=0,
                                          hit_rate=0.0, avg_return=0.0,
                                          avg_return_when_wrong=0.0)

        hits = sum(1 for s in signals if s.hit)
        total = len(signals)
        hit_rate = hits / total if total > 0 else 0

        returns = np.array([s.forward_return_1d for s in signals])
        returns = returns[np.isfinite(returns)]

        if len(returns) == 0:
            return SignalEvaluationResult(signal_name=signal_name, total_signals=total,
                                          hit_rate=hit_rate, avg_return=0.0,
                                          avg_return_when_wrong=0.0)

        # Top/bottom decile
        sorted_returns = np.sort(returns)
        top_idx = max(1, len(sorted_returns) // 10)
        best = sorted_returns[-top_idx:].mean() if top_idx > 0 else 0
        worst = sorted_returns[:top_idx].mean() if top_idx > 0 else 0

        return SignalEvaluationResult(
            signal_name=signal_name,
            total_signals=total,
            hit_rate=round(float(hit_rate), 4),
            avg_return=round(float(np.mean(returns)), 4),
            avg_return_when_wrong=round(float(worst), 4),
            best_signal={"avg_top_decile_return": round(float(best), 4)},
            worst_signal={"avg_bottom_decile_return": round(float(worst), 4)},
        )
