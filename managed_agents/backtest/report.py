"""归因报告 — 结构化输出 Agent 决策链回测结果."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class ChainStepResult:
    step: str
    success: bool
    output: str
    data: dict = field(default_factory=dict)
    elapsed_ms: int = 0
    error: str = ""


@dataclass
class SignalAttribution:
    symbol: str
    signal: dict
    forward_returns: dict
    verdict: str  # STRONG_WIN | WIN | LOSS | STRONG_LOSS | UNKNOWN


@dataclass
class AttributionReport:
    target_date: str
    steps: dict[str, ChainStepResult] = field(default_factory=dict)
    attributions: list[SignalAttribution] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    elapsed_ms: int = 0
    generated_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    def set_step(self, name: str, result: ChainStepResult):
        self.steps[name] = result

    def add_attribution(self, attr: SignalAttribution):
        self.attributions.append(attr)

    def summarize(self):
        """计算汇总指标."""
        attrs = self.attributions
        if not attrs:
            self.summary = {"total_signals": 0, "message": "无信号生成"}
            return

        total = len(attrs)
        wins = sum(1 for a in attrs if a.verdict in ("WIN", "STRONG_WIN"))
        strong_wins = sum(1 for a in attrs if a.verdict == "STRONG_WIN")
        losses = sum(1 for a in attrs if a.verdict in ("LOSS", "STRONG_LOSS"))
        strong_losses = sum(1 for a in attrs if a.verdict == "STRONG_LOSS")

        avg_conf = sum(a.signal.get("confidence", 0) for a in attrs) / total if total else 0
        avg_ret5 = sum(a.forward_returns.get("ret_5d", 0) or 0 for a in attrs) / total if total else 0
        avg_ret10 = sum(a.forward_returns.get("ret_10d", 0) or 0 for a in attrs) / total if total else 0

        # 置信度-收益率相关性
        conf_ret_pairs = [(a.signal.get("confidence", 0), a.forward_returns.get("ret_5d") or 0)
                          for a in attrs]
        n = len(conf_ret_pairs)
        if n > 1:
            mean_c = sum(c for c, _ in conf_ret_pairs) / n
            mean_r = sum(r for _, r in conf_ret_pairs) / n
            cov = sum((c - mean_c) * (r - mean_r) for c, r in conf_ret_pairs)
            var_c = sum((c - mean_c) ** 2 for c, _ in conf_ret_pairs)
            var_r = sum((r - mean_r) ** 2 for _, r in conf_ret_pairs)
            corr = round(cov / ((var_c * var_r) ** 0.5), 3) if var_c > 0 and var_r > 0 else 0
        else:
            corr = 0

        self.summary = {
            "total_signals": total,
            "wins": wins,
            "strong_wins": strong_wins,
            "losses": losses,
            "strong_losses": strong_losses,
            "win_rate": round(wins / total, 3) if total else 0,
            "avg_confidence": round(avg_conf, 3),
            "avg_ret_5d": round(avg_ret5, 2),
            "avg_ret_10d": round(avg_ret10, 2),
            "confidence_return_correlation": corr,
            "verdict": self._overall_verdict(),
        }

    def _overall_verdict(self) -> str:
        s = self.summary
        n = s.get("total_signals", 0)
        wr = s.get("win_rate", 0)
        corr = s.get("confidence_return_correlation", 0)
        avg_ret5 = s.get("avg_ret_5d", 0)

        if n <= 1:
            if n == 1 and wr >= 0.5:
                return "PRELIMINARY — 样本量不足，单次决策正确，需更多交易日验证"
            return "PRELIMINARY — 样本量不足，无法评估决策链质量"

        if wr >= 0.6 and corr > 0.1:
            return "GOOD — 决策链有效，置信度能区分信号质量"
        elif wr >= 0.5:
            return "FAIR — 有一定预测力，但置信度校准需改进"
        elif wr >= 0.4:
            return "POOR — 决策链预测力弱，建议优化信号生成逻辑"
        return "BAD — 决策链不具备预测能力，需要根本性重构"

    def to_dict(self) -> dict:
        return {
            "target_date": self.target_date,
            "generated_at": self.generated_at,
            "elapsed_ms": self.elapsed_ms,
            "chain": {name: {
                "step": r.step, "success": r.success, "output": r.output,
                "data": r.data, "elapsed_ms": r.elapsed_ms,
            } for name, r in self.steps.items()},
            "attributions": [
                {"symbol": a.symbol, "signal": a.signal,
                 "forward_returns": a.forward_returns, "verdict": a.verdict}
                for a in self.attributions
            ],
            "summary": self.summary,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent, default=str)

    def save(self, path: Path | str):
        Path(path).write_text(self.to_json(), encoding="utf-8")

    def print(self):
        """终端友好的报告输出."""
        s = self.summary
        print(f"\n{'='*60}")
        print(f"  Agent 决策链回测报告")
        print(f"  日期: {self.target_date}  |  耗时: {self.elapsed_ms}ms")
        print(f"{'='*60}")

        print(f"\n-- 决策链步骤 --")
        for name, step in self.steps.items():
            status = "OK" if step.success else "FAIL"
            print(f"  [{status}] {step.step}: {step.output}")

        print(f"\n-- 信号归因 (共 {s.get('total_signals', 0)} 个) --")
        for a in self.attributions:
            icon = {"STRONG_WIN": "**", "WIN": "*", "LOSS": "x", "STRONG_LOSS": "xx"}.get(a.verdict, "?")
            conf = a.signal.get("confidence", 0)
            ret5 = a.forward_returns.get("ret_5d") or 0
            print(f"  [{icon}] {a.symbol}  conf={conf:.2f}  5日收益={ret5:+.1f}%  {a.verdict}")

        print(f"\n-- 汇总指标 --")
        print(f"  胜率: {s.get('win_rate', 0):.1%}")
        print(f"  平均置信度: {s.get('avg_confidence', 0):.2f}")
        print(f"  平均5日收益: {s.get('avg_ret_5d', 0):+.1f}%")
        print(f"  平均10日收益: {s.get('avg_ret_10d', 0):+.1f}%")
        print(f"  置信度-收益相关性: {s.get('confidence_return_correlation', 0):.3f}")
        print(f"\n  综合判断: {s.get('verdict', 'N/A')}")
        print()
