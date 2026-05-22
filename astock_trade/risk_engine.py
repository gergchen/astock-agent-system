"""Programmatic risk engine — deterministic, LLM-proof, hardware-level safety.

Every trade MUST pass this engine before execution. LLM agents can suggest
but can NEVER override a REJECTED decision. The engine is pure Python code
with no AI/LLM dependency.

Design principles:
- Hard limits → immediate REJECT, no override possible
- Soft limits → WARN but allow (logged for audit)
- Circuit breaker → auto-halt, persists across calls
- Kill switch → manual emergency stop, persists across processes
- Loss accelerator → auto-halt on accelerating losses
- All decisions are immutable and auditable
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from .config import get_config

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════

class RiskDecisionType(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WARN = "WARN"  # approved with caveats


@dataclass(frozen=True)
class CheckResult:
    """Result of a single risk check. Frozen — immutable after creation."""
    rule: str
    passed: bool
    detail: str
    limit: str = ""
    current: str = ""


@dataclass(frozen=True)
class RiskDecision:
    """Final risk decision. Frozen — caller cannot modify after creation."""
    decision: RiskDecisionType
    signal_symbol: str
    signal_direction: str
    signal_price: float
    signal_volume: int
    adjusted_volume: int  # may be reduced by risk engine, never increased
    checks: list[CheckResult]
    reason: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def approved(self) -> bool:
        return self.decision != RiskDecisionType.REJECTED

    @property
    def rejected(self) -> bool:
        return self.decision == RiskDecisionType.REJECTED

    def to_dict(self) -> dict:
        return {
            "type": "risk_decision",
            "decision": self.decision.value,
            "signal_symbol": self.signal_symbol,
            "signal_direction": self.signal_direction,
            "signal_price": self.signal_price,
            "signal_volume": self.signal_volume,
            "adjusted_volume": self.adjusted_volume,
            "checks": {c.rule: c.passed for c in self.checks},
            "check_details": [
                {"rule": c.rule, "passed": c.passed, "detail": c.detail, "limit": c.limit, "current": c.current}
                for c in self.checks
            ],
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class TradeSignal:
    """Normalized trade signal input."""
    symbol: str
    direction: str  # "BUY" or "SELL"
    price: float
    volume: int  # shares
    strategy: str = ""
    confidence: float = 0.0

    @property
    def amount(self) -> float:
        return self.price * self.volume


@dataclass
class PortfolioSnapshot:
    """Point-in-time portfolio state for risk calculation."""
    total_assets: float
    cash: float
    positions: dict[str, float]  # symbol → market_value
    daily_pnl: float = 0.0
    daily_drawdown_pct: float = 0.0
    consecutive_losses: int = 0
    today_trade_count: int = 0


# ═══════════════════════════════════════════════════════════════════
# Hard Limits — NEVER bypass these
# ═══════════════════════════════════════════════════════════════════

HARD_LIMITS = {
    "max_single_position_pct": 0.20,    # 单只 ≤ 20%
    "max_total_position_pct": 0.70,     # 总仓 ≤ 70%
    "max_daily_drawdown_pct": 0.05,     # 日内回撤 ≤ 5%
    "max_consecutive_losses": 3,        # 连亏3次暂停
    "banned_prefixes": ("ST", "*ST"),   # 禁止交易
}

# Soft limits — warn but allow
SOFT_LIMITS = {
    "max_single_order_pct": 0.10,       # 单笔 ≤ 10% (软)
    "max_sector_exposure_pct": 0.30,    # 同板块 ≤ 30%
    "max_morning_new_positions": 3,     # 上午新开仓 ≤ 3笔
    "min_confidence": 0.3,              # 最低置信度
}

# Circuit breaker
CIRCUIT_BREAKER_HALT_MINUTES = 30  # 熔断暂停时间
CIRCUIT_BREAKER_STATE_FILE = "circuit_breaker.json"

# Kill switch
KILL_SWITCH_STATE_FILE = "kill_switch.json"
LOSS_ACCELERATION_WINDOW_MINUTES = 15   # 亏损加速检测窗口
LOSS_ACCELERATION_THRESHOLD = 3         # 窗口内连亏笔数触发加速熔断


# ═══════════════════════════════════════════════════════════════════
# Kill Switch — manual emergency stop, persists across processes
# ═══════════════════════════════════════════════════════════════════

class KillSwitch:
    """Emergency kill switch — manual stop that persists across processes.

    Once pulled, ALL trading is blocked until explicitly released.
    This is the LAST LINE OF DEFENSE — a human override.
    The switch can be pulled via CLI, Feishu bot, or signal bus.
    """

    MODES = frozenset({"graceful", "immediate", "hard"})

    def __init__(self, state_dir: Path | str | None = None):
        if state_dir is None:
            state_dir = get_config().data_dir
        self._state_path = Path(state_dir) / KILL_SWITCH_STATE_FILE
        self._state: dict = self._load()

    def _load(self) -> dict:
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {
            "killed": False,
            "mode": "",
            "reason": "",
            "killed_at": None,
            "killed_by": "",
            "allow_sell_only": False,  # in kill mode, only sell-to-close is allowed
        }

    def _save(self):
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._state_path)

    @property
    def killed(self) -> bool:
        return self._state.get("killed", False)

    @property
    def reason(self) -> str:
        return self._state.get("reason", "")

    @property
    def mode(self) -> str:
        return self._state.get("mode", "")

    @property
    def allow_sell_only(self) -> bool:
        return self._state.get("allow_sell_only", False)

    def pull(self, reason: str, mode: str = "graceful", by: str = "system") -> None:
        """Pull the kill switch.

        Args:
            reason: Why the switch was pulled.
            mode: graceful=finish current orders then halt,
                  immediate=halt now,
                  hard=halt now + cancel all pending orders
            by: Who pulled the switch (CLI / feishu / risk_engine / system).
        """
        if mode not in self.MODES:
            raise ValueError(f"Invalid kill mode: {mode}. Choose from {self.MODES}")

        # hard mode always blocks sells too (full lockdown)
        allow_sell = mode != "hard"

        self._state = {
            "killed": True,
            "mode": mode,
            "reason": reason,
            "killed_at": datetime.now().isoformat(timespec="seconds"),
            "killed_by": by,
            "allow_sell_only": allow_sell,
        }
        self._save()
        logger.critical("KILL SWITCH PULLED: [%s] %s by %s — allow_sell_only=%s",
                        mode, reason, by, allow_sell)

    def release(self, by: str = "system") -> None:
        """Release the kill switch — resume normal trading."""
        old = dict(self._state)
        self._state = {
            "killed": False, "mode": "", "reason": "",
            "killed_at": None, "killed_by": "", "allow_sell_only": False,
        }
        self._save()
        logger.warning("KILL SWITCH RELEASED by %s (was: %s)", by, old.get("reason", ""))

    def status(self) -> dict:
        """Return current kill switch status."""
        return dict(self._state)


# ═══════════════════════════════════════════════════════════════════
# Loss Accelerator — auto-halt on accelerating losses
# ═══════════════════════════════════════════════════════════════════

class LossAccelerator:
    """Detects accelerating loss patterns within a short window.

    If N consecutive losses occur within M minutes, triggers the kill switch.
    """

    def __init__(self, window_minutes: int = LOSS_ACCELERATION_WINDOW_MINUTES,
                 threshold: int = LOSS_ACCELERATION_THRESHOLD):
        self.window_minutes = window_minutes
        self.threshold = threshold
        self._losses: list[float] = []  # (timestamp, loss_pct)

    def record_trade(self, pnl_pct: float) -> None:
        """Record a completed trade's P&L. Returns True if acceleration detected."""
        now = time.time()
        cutoff = now - self.window_minutes * 60

        # Prune old entries
        self._losses = [ts for ts in self._losses if ts > cutoff]

        if pnl_pct < 0:
            self._losses.append(now)

    @property
    def accelerating(self) -> bool:
        """Check if loss acceleration threshold is hit."""
        now = time.time()
        cutoff = now - self.window_minutes * 60
        recent = sum(1 for ts in self._losses if ts > cutoff)
        return recent >= self.threshold

    @property
    def recent_loss_count(self) -> int:
        now = time.time()
        cutoff = now - self.window_minutes * 60
        return sum(1 for ts in self._losses if ts > cutoff)

    def reset(self) -> None:
        self._losses.clear()


# ═══════════════════════════════════════════════════════════════════
# Circuit Breaker
# ═══════════════════════════════════════════════════════════════════

class CircuitBreaker:
    """Stateful circuit breaker — persists halt state to disk.

    Once tripped, all trading is blocked until the halt period expires.
    """

    def __init__(self, state_dir: Path | None = None):
        if state_dir is None:
            state_dir = get_config().data_dir
        self._state_path = state_dir / CIRCUIT_BREAKER_STATE_FILE
        self._state: dict = self._load()

    def _load(self) -> dict:
        import json
        if self._state_path.exists():
            try:
                return json.loads(self._state_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {"tripped": False, "tripped_at": None, "reason": "", "halt_until": None}

    def _save(self):
        import json, os
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self._state_path)

    @property
    def tripped(self) -> bool:
        if not self._state["tripped"]:
            return False
        halt_until = self._state.get("halt_until")
        if halt_until and time.time() > halt_until:
            self.reset()
            return False
        return True

    @property
    def reason(self) -> str:
        return self._state.get("reason", "")

    @property
    def remaining_seconds(self) -> float:
        halt_until = self._state.get("halt_until", 0) or 0
        return max(0, halt_until - time.time())

    def trip(self, reason: str, halt_minutes: int = CIRCUIT_BREAKER_HALT_MINUTES):
        now = time.time()
        self._state = {
            "tripped": True,
            "tripped_at": datetime.fromtimestamp(now).isoformat(),
            "reason": reason,
            "halt_until": now + halt_minutes * 60,
        }
        self._save()
        logger.critical("CIRCUIT BREAKER TRIPPED: %s (halt for %d min)", reason, halt_minutes)

    def trip_for_day(self, reason: str):
        """Trip until end of trading day (15:00)."""
        import datetime as dt
        now = dt.datetime.now()
        market_close = now.replace(hour=15, minute=0, second=0, microsecond=0)
        if now > market_close:
            market_close = market_close.replace(hour=15, minute=0) + dt.timedelta(days=1)
        halt_seconds = (market_close - now).total_seconds()
        self._state = {
            "tripped": True,
            "tripped_at": datetime.fromtimestamp(time.time()).isoformat(),
            "reason": reason,
            "halt_until": time.time() + halt_seconds,
        }
        self._save()
        logger.critical("CIRCUIT BREAKER TRIPPED FOR DAY: %s", reason)

    def reset(self):
        self._state = {"tripped": False, "tripped_at": None, "reason": "", "halt_until": None}
        self._save()
        logger.info("Circuit breaker reset")


# ═══════════════════════════════════════════════════════════════════
# Risk Engine
# ═══════════════════════════════════════════════════════════════════

class RiskEngine:
    """Deterministic risk engine — the single source of truth for trade safety.

    Usage::

        engine = RiskEngine()
        signal = TradeSignal(symbol="600519", direction="BUY", price=1680, volume=100)
        portfolio = PortfolioSnapshot(total_assets=1_000_000, cash=500_000, positions={})
        decision = engine.check(signal, portfolio)

        if decision.approved:
            execute(decision.adjusted_volume)
        else:
            log_and_notify(decision.reason)
    """

    def __init__(self):
        self._breaker = CircuitBreaker()
        self._kill_switch = KillSwitch()
        self._loss_accelerator = LossAccelerator()

    # ── Public API ──────────────────────────────────────────

    @property
    def kill_switch(self) -> KillSwitch:
        return self._kill_switch

    @property
    def loss_accelerator(self) -> LossAccelerator:
        return self._loss_accelerator

    def check(self, signal: TradeSignal, portfolio: PortfolioSnapshot) -> RiskDecision:
        """Run all risk checks and return an immutable decision.

        This is THE method that gates every trade. No LLM involvement.
        """
        checks: list[CheckResult] = []

        # 0. Kill switch — absolute last line of defense, check FIRST
        ks_check = self._check_kill_switch(signal)
        checks.append(ks_check)
        if not ks_check.passed:
            return self._reject(signal, checks, ks_check.detail)

        # 0b. Loss accelerator
        la_check = self._check_loss_accelerator()
        checks.append(la_check)
        if not la_check.passed:
            self._breaker.trip(la_check.detail)
            return self._reject(signal, checks, la_check.detail)

        # 1. Circuit breaker — must check first
        cb_check = self._check_circuit_breaker()
        checks.append(cb_check)
        if not cb_check.passed:
            return self._reject(signal, checks, cb_check.detail)

        # 2. ST ban
        st_check = self._check_st_ban(signal)
        checks.append(st_check)
        if not st_check.passed:
            return self._reject(signal, checks, st_check.detail)

        # 3. Single stock position limit
        pos_check = self._check_single_position(signal, portfolio)
        checks.append(pos_check)
        if not pos_check.passed:
            return self._reject(signal, checks, pos_check.detail)

        # 4. Total exposure limit
        exposure_check = self._check_total_exposure(signal, portfolio)
        checks.append(exposure_check)
        if not exposure_check.passed:
            return self._reject(signal, checks, exposure_check.detail)

        # 5. Daily drawdown
        dd_check = self._check_daily_drawdown(portfolio)
        checks.append(dd_check)
        if not dd_check.passed:
            self._breaker.trip_for_day(dd_check.detail)
            return self._reject(signal, checks, dd_check.detail)

        # 6. Consecutive losses
        cl_check = self._check_consecutive_losses(portfolio)
        checks.append(cl_check)
        if not cl_check.passed:
            self._breaker.trip(cl_check.detail)
            return self._reject(signal, checks, cl_check.detail)

        # All hard checks passed. Now soft checks (warn but allow).
        reason_parts = []

        # Soft: single order size
        order_check = self._check_order_size(signal, portfolio)
        checks.append(order_check)
        if not order_check.passed:
            reason_parts.append(order_check.detail)

        # Soft: confidence
        conf_check = self._check_confidence(signal)
        checks.append(conf_check)
        if not conf_check.passed:
            reason_parts.append(conf_check.detail)

        # Determine adjusted volume (can reduce, never increase)
        adjusted_volume = self._adjust_volume(signal, portfolio)

        if reason_parts:
            return RiskDecision(
                decision=RiskDecisionType.WARN,
                signal_symbol=signal.symbol,
                signal_direction=signal.direction,
                signal_price=signal.price,
                signal_volume=signal.volume,
                adjusted_volume=adjusted_volume,
                checks=checks,
                reason="; ".join(reason_parts),
            )

        return RiskDecision(
            decision=RiskDecisionType.APPROVED,
            signal_symbol=signal.symbol,
            signal_direction=signal.direction,
            signal_price=signal.price,
            signal_volume=signal.volume,
            adjusted_volume=adjusted_volume,
            checks=checks,
            reason="所有风控检查通过",
        )

    def check_batch(self, signals: list[TradeSignal], portfolio: PortfolioSnapshot) -> list[RiskDecision]:
        """Run risk checks on a batch of signals against the same portfolio snapshot."""
        decisions = []
        remaining_cash = portfolio.cash
        for signal in signals:
            # Update portfolio with prior approved decisions' impact
            decision = self.check(signal, portfolio)
            decisions.append(decision)
            if decision.approved:
                amount = decision.signal_price * decision.adjusted_volume
                if decision.signal_direction == "BUY":
                    amount = -amount
                remaining_cash += amount
                # For batch, propagate position changes to next checks
                positions = dict(portfolio.positions)
                key = decision.signal_symbol
                current = positions.get(key, 0)
                positions[key] = current + (decision.signal_price * decision.adjusted_volume)
                portfolio = PortfolioSnapshot(
                    total_assets=portfolio.total_assets,
                    cash=remaining_cash,
                    positions=positions,
                    daily_pnl=portfolio.daily_pnl,
                    daily_drawdown_pct=portfolio.daily_drawdown_pct,
                    consecutive_losses=portfolio.consecutive_losses,
                    today_trade_count=portfolio.today_trade_count + 1,
                )
        return decisions

    def circuit_breaker_status(self) -> dict:
        return {
            "tripped": self._breaker.tripped,
            "reason": self._breaker.reason,
            "remaining_seconds": self._breaker.remaining_seconds,
        }

    def reset_circuit_breaker(self):
        self._breaker.reset()

    # ── Individual Checks ───────────────────────────────────

    def _check_kill_switch(self, signal: TradeSignal) -> CheckResult:
        """Kill switch check — blocks BUY, allows SELL in kill mode."""
        if not self._kill_switch.killed:
            return CheckResult(rule="kill_switch", passed=True, detail="急停未触发",
                               limit="无急停", current="正常")

        if self._kill_switch.allow_sell_only and signal.direction == "SELL":
            return CheckResult(rule="kill_switch", passed=True,
                               detail=f"急停中但允许卖出: {self._kill_switch.reason}")

        return CheckResult(
            rule="kill_switch", passed=False,
            detail=f"急停中: [{self._kill_switch.mode}] {self._kill_switch.reason}",
            limit="无急停", current=self._kill_switch.mode,
        )

    def _check_loss_accelerator(self) -> CheckResult:
        """Check if losses are accelerating within the detection window."""
        if not self._loss_accelerator.accelerating:
            return CheckResult(
                rule="loss_accelerator", passed=True,
                detail=f"连亏 {self._loss_accelerator.recent_loss_count} 笔 / 阈值 {self._loss_accelerator.threshold}",
                limit=str(self._loss_accelerator.threshold),
                current=str(self._loss_accelerator.recent_loss_count),
            )
        return CheckResult(
            rule="loss_accelerator", passed=False,
            detail=f"亏损加速: {self._loss_accelerator.recent_loss_count} 笔连亏在 "
                   f"{LOSS_ACCELERATION_WINDOW_MINUTES}分钟内",
            limit=str(self._loss_accelerator.threshold),
            current=str(self._loss_accelerator.recent_loss_count),
        )

    def record_trade_result(self, pnl_pct: float) -> None:
        """Feed back a completed trade P&L for loss acceleration detection."""
        if pnl_pct < 0:
            self._loss_accelerator.record_trade(pnl_pct)
            if self._loss_accelerator.accelerating:
                self._kill_switch.pull(
                    reason=f"亏损加速: {self._loss_accelerator.recent_loss_count}笔连亏在"
                           f"{LOSS_ACCELERATION_WINDOW_MINUTES}分钟内",
                    mode="graceful", by="loss_accelerator",
                )

    def _check_circuit_breaker(self) -> CheckResult:
        if self._breaker.tripped:
            remaining = int(self._breaker.remaining_seconds)
            return CheckResult(
                rule="circuit_breaker",
                passed=False,
                detail=f"熔断中: {self._breaker.reason}，剩余 {remaining} 秒",
                limit="无熔断",
                current=f"已熔断 ({self._breaker.reason})",
            )
        return CheckResult(rule="circuit_breaker", passed=True, detail="熔断未触发", limit="无熔断", current="正常")

    def _check_st_ban(self, signal: TradeSignal) -> CheckResult:
        symbol_upper = signal.symbol.upper()
        is_st = any(prefix in symbol_upper for prefix in HARD_LIMITS["banned_prefixes"])
        return CheckResult(
            rule="st_ban",
            passed=not is_st,
            detail="ST/*ST 禁止交易" if is_st else "正常标的",
            limit="禁止 ST/*ST",
            current="ST" if is_st else signal.symbol,
        )

    def _check_single_position(self, signal: TradeSignal, portfolio: PortfolioSnapshot) -> CheckResult:
        limit = HARD_LIMITS["max_single_position_pct"]
        current_value = portfolio.positions.get(signal.symbol, 0)
        new_amount = signal.price * signal.volume
        if signal.direction == "SELL":
            new_amount = 0  # selling reduces position, always allowed
        projected_value = current_value + new_amount
        pct = projected_value / portfolio.total_assets if portfolio.total_assets > 0 else 1.0
        return CheckResult(
            rule="single_position_limit",
            passed=pct <= limit,
            detail=f"持仓占比 {pct:.1%} / 限制 {limit:.0%}" if pct > limit else f"持仓占比 {pct:.1%}",
            limit=f"{limit:.0%}",
            current=f"{pct:.1%}",
        )

    def _check_order_size(self, signal: TradeSignal, portfolio: PortfolioSnapshot) -> CheckResult:
        limit = SOFT_LIMITS["max_single_order_pct"]
        amount = signal.price * signal.volume
        pct = amount / portfolio.total_assets if portfolio.total_assets > 0 else 1.0
        return CheckResult(
            rule="single_order_limit",
            passed=pct <= limit,
            detail=f"单笔占比 {pct:.1%} / 建议 {limit:.0%}" if pct > limit else f"单笔占比 {pct:.1%}",
            limit=f"{limit:.0%} (软)",
            current=f"{pct:.1%}",
        )

    def _check_total_exposure(self, signal: TradeSignal, portfolio: PortfolioSnapshot) -> CheckResult:
        limit = HARD_LIMITS["max_total_position_pct"]
        current_exposure = sum(v for v in portfolio.positions.values() if v > 0)
        new_amount = signal.price * signal.volume
        if signal.direction == "BUY":
            projected = current_exposure + new_amount
        else:
            projected = current_exposure - new_amount
        pct = projected / portfolio.total_assets if portfolio.total_assets > 0 else 1.0
        return CheckResult(
            rule="total_exposure",
            passed=pct <= limit,
            detail=f"总仓位 {pct:.1%} / 限制 {limit:.0%}" if pct > limit else f"总仓位 {pct:.1%}",
            limit=f"{limit:.0%}",
            current=f"{pct:.1%}",
        )

    def _check_daily_drawdown(self, portfolio: PortfolioSnapshot) -> CheckResult:
        limit = HARD_LIMITS["max_daily_drawdown_pct"]
        dd = portfolio.daily_drawdown_pct
        return CheckResult(
            rule="daily_drawdown",
            passed=dd < limit,
            detail=f"日内回撤 {dd:.2%} / 限制 {limit:.1%}" if dd >= limit else f"日内回撤 {dd:.2%}",
            limit=f"{limit:.1%}",
            current=f"{dd:.2%}",
        )

    def _check_consecutive_losses(self, portfolio: PortfolioSnapshot) -> CheckResult:
        limit = HARD_LIMITS["max_consecutive_losses"]
        cl = portfolio.consecutive_losses
        return CheckResult(
            rule="consecutive_losses",
            passed=cl < limit,
            detail=f"连续亏损 {cl} 笔 / 限制 {limit}" if cl >= limit else f"连续亏损 {cl} 笔",
            limit=str(limit),
            current=str(cl),
        )

    def _check_confidence(self, signal: TradeSignal) -> CheckResult:
        limit = SOFT_LIMITS["min_confidence"]
        return CheckResult(
            rule="confidence",
            passed=signal.confidence >= limit,
            detail=f"信号置信度 {signal.confidence:.2f} / 最低 {limit:.2f}",
            limit=str(limit),
            current=f"{signal.confidence:.2f}",
        )

    # ── Volume Adjustment ───────────────────────────────────

    def _adjust_volume(self, signal: TradeSignal, portfolio: PortfolioSnapshot) -> int:
        """Reduce volume if needed to stay within limits. Never increases."""
        adjusted = signal.volume

        # Cap by single order limit (soft)
        max_order_amount = portfolio.total_assets * SOFT_LIMITS["max_single_order_pct"]
        max_order_volume = int(max_order_amount / signal.price) if signal.price > 0 else 0
        adjusted = min(adjusted, max_order_volume)

        # Cap by single position limit
        limit = HARD_LIMITS["max_single_position_pct"]
        current_value = portfolio.positions.get(signal.symbol, 0)
        max_position = portfolio.total_assets * limit
        remaining = max_position - current_value
        if signal.direction == "BUY" and remaining > 0:
            max_pos_volume = int(remaining / signal.price)
            adjusted = min(adjusted, max_pos_volume)

        # Cap by available cash
        if signal.direction == "BUY" and signal.price > 0:
            max_cash_volume = int(portfolio.cash / signal.price)
            adjusted = min(adjusted, max_cash_volume)

        return max(0, adjusted)

    # ── Helpers ─────────────────────────────────────────────

    @staticmethod
    def _reject(signal: TradeSignal, checks: list[CheckResult], reason: str) -> RiskDecision:
        return RiskDecision(
            decision=RiskDecisionType.REJECTED,
            signal_symbol=signal.symbol,
            signal_direction=signal.direction,
            signal_price=signal.price,
            signal_volume=signal.volume,
            adjusted_volume=0,
            checks=checks,
            reason=reason,
        )

    @staticmethod
    def portfolio_from_broker(account, daily_pnl: float = 0.0,
                              consecutive_losses: int = 0,
                              today_trade_count: int = 0) -> PortfolioSnapshot:
        """Build PortfolioSnapshot from a broker Account object."""
        positions = {}
        for p in (account.positions or []):
            positions[p.symbol] = p.market_value
        return PortfolioSnapshot(
            total_assets=account.total_assets,
            cash=account.cash,
            positions=positions,
            daily_pnl=daily_pnl,
            consecutive_losses=consecutive_losses,
            today_trade_count=today_trade_count,
        )

    @staticmethod
    def signal_from_dict(d: dict) -> TradeSignal:
        """Build TradeSignal from a dict (e.g. from message bus)."""
        raw_symbol = str(d.get("symbol", ""))
        symbol = raw_symbol.zfill(6) if raw_symbol.isdigit() else raw_symbol.upper()
        return TradeSignal(
            symbol=symbol,
            direction=d.get("direction", "BUY").upper(),
            price=float(d.get("price", 0) or 0),
            volume=int(d.get("volume", 0) or 0),
            strategy=d.get("strategy", ""),
            confidence=float(d.get("confidence", 0) or 0),
        )
