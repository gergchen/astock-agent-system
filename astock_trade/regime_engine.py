"""Regime Engine — market state detection for strategy selection.

Identifies current market regime from index data and adjusts strategy
selection and risk parameters accordingly.

Regimes:
  - BULL      : Trending up, high momentum, low volatility
  - BEAR      : Trending down, negative momentum
  - OSCILLATION : Range-bound, low trend strength
  - STRUCTURAL  : Divergence between large/small caps, sector rotation

Design: Pure deterministic calculation from index K-line data.
No LLM, no external API calls at inference time.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


class RegimeType(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    OSCILLATION = "OSCILLATION"
    STRUCTURAL = "STRUCTURAL"


# Strategy suitability scores by regime (0=avoid, 10=ideal)
REGIME_STRATEGY_MAP = {
    "ma_crossover":       {RegimeType.BULL: 8, RegimeType.BEAR: 2, RegimeType.OSCILLATION: 4, RegimeType.STRUCTURAL: 5},
    "price_breakout":     {RegimeType.BULL: 9, RegimeType.BEAR: 3, RegimeType.OSCILLATION: 7, RegimeType.STRUCTURAL: 6},
    "ma_crossover_volume": {RegimeType.BULL: 8, RegimeType.BEAR: 2, RegimeType.OSCILLATION: 5, RegimeType.STRUCTURAL: 6},
    "ma_crossover_trend": {RegimeType.BULL: 9, RegimeType.BEAR: 1, RegimeType.OSCILLATION: 3, RegimeType.STRUCTURAL: 4},
    "triple_filter":      {RegimeType.BULL: 8, RegimeType.BEAR: 4, RegimeType.OSCILLATION: 6, RegimeType.STRUCTURAL: 7},
    "buy_and_hold":       {RegimeType.BULL: 10, RegimeType.BEAR: 0, RegimeType.OSCILLATION: 2, RegimeType.STRUCTURAL: 3},
}

# Risk multiplier by regime
REGIME_RISK_MULTIPLIER = {
    RegimeType.BULL: 1.0,          # normal risk
    RegimeType.BEAR: 0.3,          # reduce risk heavily
    RegimeType.OSCILLATION: 0.7,   # slightly reduce
    RegimeType.STRUCTURAL: 0.5,    # reduce — market is confused
}


@dataclass
class RegimeSignal:
    """Current regime detection result."""
    regime: RegimeType
    confidence: float  # 0.0 ~ 1.0
    score: float       # composite regime score
    details: dict = field(default_factory=dict)
    detected_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    # Recommended adjustments
    suggested_strategies: list[tuple[str, float]] = field(default_factory=list)
    risk_multiplier: float = 1.0
    max_position_pct: float = 0.20
    signal_threshold: float = 0.0

    def to_dict(self) -> dict:
        return {
            "regime": self.regime.value,
            "confidence": self.confidence,
            "score": self.score,
            "detected_at": self.detected_at,
            "suggested_strategies": [
                {"name": name, "score": s} for name, s in self.suggested_strategies
            ],
            "risk_multiplier": self.risk_multiplier,
            "max_position_pct": self.max_position_pct,
            "signal_threshold": self.signal_threshold,
            "details": self.details,
        }


class RegimeEngine:
    """Detect market regime from index price/volume/volatility data.

    Usage:
        engine = RegimeEngine()
        signal = engine.detect(index_df)
        if signal.regime == RegimeType.BEAR:
            # reduce position size, use defensive strategies
            pass
    """

    def __init__(self, lookback_days: int = 60):
        self.lookback_days = lookback_days
        self._last_signal: Optional[RegimeSignal] = None

    @property
    def last_signal(self) -> Optional[RegimeSignal]:
        return self._last_signal

    def detect(self, df: 'pd.DataFrame') -> RegimeSignal:
        """Detect market regime from index K-line data.

        Args:
            df: DataFrame with columns [date, close, high, low, vol]
                (at least 60 trading days recommended).

        Returns:
            RegimeSignal with regime classification and recommendations.
        """
        import pandas as pd

        if df is None or df.empty:
            logger.warning("Empty data — defaulting to OSCILLATION regime")
            return self._default_regime("No data available")

        data = df.copy()
        close = data["close"].values
        high = data["high"].values if "high" in data else close
        low = data["low"].values if "low" in data else close
        vol = data["vol"].values if "vol" in data else np.ones_like(close)

        n = len(close)
        if n < 20:
            return self._default_regime("Insufficient data (< 20 bars)")

        # ── Feature computation ──────────────────────────────

        # 1. Trend strength: ADX-like using SMA directional movement
        sma20 = np.mean(close[-20:])
        sma60 = np.mean(close[-min(60, n):]) if n >= 60 else sma20
        trend_score = (sma20 / sma60 - 1) * 100  # positive = uptrend

        # 2. Momentum: rate of change
        roc_5d = (close[-1] / close[-min(5, n)] - 1) * 100 if n >= 5 else 0
        roc_10d = (close[-1] / close[-min(10, n)] - 1) * 100 if n >= 10 else 0
        roc_20d = (close[-1] / close[-min(20, n)] - 1) * 100 if n >= 20 else 0
        momentum_score = roc_5d * 0.5 + roc_10d * 0.3 + roc_20d * 0.2

        # 3. Volatility regime
        daily_returns = np.diff(close) / close[:-1]
        recent_vol = np.std(daily_returns[-min(20, len(daily_returns)):]) * 100
        hist_vol = np.std(daily_returns) * 100
        vol_ratio = recent_vol / hist_vol if hist_vol > 0 else 1.0

        # 4. Volume trend
        vol_sma20 = np.mean(vol[-min(20, n):])
        vol_sma60 = np.mean(vol[-min(60, n):]) if n >= 60 else vol_sma20
        vol_trend = vol_sma20 / vol_sma60 if vol_sma60 > 0 else 1.0

        # 5. Price position in range
        recent_high = np.max(close[-min(20, n):])
        recent_low = np.min(close[-min(20, n):])
        range_pos = (close[-1] - recent_low) / (recent_high - recent_low) \
            if (recent_high - recent_low) > 0 else 0.5

        # ── Regime classification ────────────────────────────

        features = {
            "trend_score": round(trend_score, 2),
            "momentum_score": round(momentum_score, 2),
            "roc_5d": round(roc_5d, 2),
            "roc_10d": round(roc_10d, 2),
            "roc_20d": round(roc_20d, 2),
            "recent_vol_pct": round(recent_vol, 2),
            "vol_ratio": round(vol_ratio, 2),
            "vol_trend": round(vol_trend, 2),
            "range_position": round(range_pos, 2),
        }

        # Decision tree
        trend_strong = abs(trend_score) > 1.5
        momentum_strong = abs(momentum_score) > 3.0
        vol_elevated = vol_ratio > 1.3
        range_mid = 0.3 < range_pos < 0.7

        if momentum_strong and trend_score > 0 and roc_5d > 0:
            # Strong positive momentum + uptrend
            regime = RegimeType.BULL
            confidence = min(1.0, abs(momentum_score) / 10)
            score = momentum_score
        elif momentum_strong and trend_score < 0 and roc_5d < 0:
            # Strong negative momentum + downtrend
            regime = RegimeType.BEAR
            confidence = min(1.0, abs(momentum_score) / 10)
            score = momentum_score
        elif vol_elevated and not trend_strong:
            # High volatility with no clear trend → structural
            regime = RegimeType.STRUCTURAL
            # Check sector divergence if data available
            features["divergence_note"] = "High vol, no clear trend direction"
            confidence = min(0.8, vol_ratio / 2)
            score = 0
        else:
            # Default: range-bound
            regime = RegimeType.OSCILLATION
            confidence = 0.6 if range_mid else 0.4
            score = momentum_score

        # ── Build output ─────────────────────────────────────

        risk_mult = REGIME_RISK_MULTIPLIER[regime]
        max_pos = 0.20 * risk_mult

        # Score strategies for this regime
        strategy_scores = []
        for sname, s_map in REGIME_STRATEGY_MAP.items():
            base = s_map.get(regime, 5)
            strategy_scores.append((sname, base))
        strategy_scores.sort(key=lambda x: -x[1])

        signal = RegimeSignal(
            regime=regime,
            confidence=round(confidence, 2),
            score=round(score, 2),
            details=features,
            suggested_strategies=strategy_scores[:3],
            risk_multiplier=round(risk_mult, 2),
            max_position_pct=round(max_pos, 2),
            signal_threshold=round(0.3 * risk_mult, 2),
        )

        self._last_signal = signal
        logger.info("Regime detected: %s (confidence=%.2f, score=%.2f, risk_mult=%.2f)",
                    regime.value, confidence, score, risk_mult)
        return signal

    def _default_regime(self, reason: str) -> RegimeSignal:
        """Return safe default regime when data is unavailable."""
        return RegimeSignal(
            regime=RegimeType.OSCILLATION,
            confidence=0.0,
            score=0.0,
            details={"error": reason},
            suggested_strategies=[("triple_filter", 6), ("price_breakout", 6)],
            risk_multiplier=0.5,
            max_position_pct=0.10,
            signal_threshold=0.5,
        )

    def detect_from_api(self, index_code: str = "000300",
                        lookback_days: int = None) -> RegimeSignal:
        """Detect regime by fetching index K-line data from data API.

        Convenience method for CLI / agent use.
        """
        lb = lookback_days or self.lookback_days
        try:
            from astock_data.market.mootdx_quote import get_kline
            df = get_kline(index_code, category="day", offset=lb)
            if df is not None and not df.empty:
                return self.detect(df)
        except Exception as e:
            logger.warning("Failed to fetch index %s data: %s", index_code, e)

        return self._default_regime(f"Failed to fetch {index_code}")
