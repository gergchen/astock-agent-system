"""CLI UI components — rich tables, panels, colored metrics.

Centralises all terminal-output formatting so individual commands don't
sprinkle formatting logic everywhere.  Every public function returns a
Renderable (str or rich object) — caller decides whether to print.
"""

from dataclasses import dataclass
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout

console = Console()


# ── Colour helpers ──────────────────────────────────────────────────────


def _pct(v: float) -> Text:
    """Colour-coded percentage value."""
    t = Text(f"{v:+.2f}%")
    t.stylize("bold green" if v > 0 else "bold red" if v < 0 else "")
    return t


def _pct_raw(v: float, suffix: str = "%") -> Text:
    t = Text(f"{v:.2f}{suffix}")
    t.stylize("green" if v > 0 else "red" if v < 0 else "")
    return t


def _bool_tag(ok: bool, yes: str = "OK", no: str = "FAIL") -> Text:
    t = Text(yes if ok else no)
    t.stylize("bold green" if ok else "bold red")
    return t


# ── Reusable builders ───────────────────────────────────────────────────


_COL_MAP = {
    "name/symbol": "策略/代码 | Strategy",
    "total_return": "总收益 | Return",
    "annual_return": "年化 | Annual",
    "sharpe": "夏普 | Sharpe",
    "drawdown": "回撤 | DD",
    "win_rate": "胜率 | Win",
    "trades": "交易 | Trades",
    "alpha": "Alpha",
    "beta": "Beta",
}


def backtest_result_table(
    rows: list[dict[str, Any]],
    title: str = "回测结果 | Backtest Results",
    show_benchmark: bool = False,
) -> Table:
    """Build a table from backtest result dicts."""
    table = Table(title=title, title_style="bold", border_style="blue")
    table.add_column(_COL_MAP["name/symbol"], style="cyan", no_wrap=True)
    table.add_column(_COL_MAP["total_return"], justify="right")
    table.add_column(_COL_MAP["annual_return"], justify="right")
    table.add_column(_COL_MAP["sharpe"], justify="right")
    table.add_column(_COL_MAP["drawdown"], justify="right")
    table.add_column(_COL_MAP["win_rate"], justify="right")
    table.add_column(_COL_MAP["trades"], justify="right")

    if show_benchmark:
        table.add_column(_COL_MAP["alpha"], justify="right")
        table.add_column(_COL_MAP["beta"], justify="right")

    for row in rows:
        cols = [
            row.get("name", row.get("symbol", "")),
            _pct(row.get("total_return_pct", 0)),
            _pct(row.get("annual_return_pct", 0)),
            f'{row.get("sharpe_ratio", 0):.2f}',
            Text(f'{row.get("max_drawdown_pct", 0):.2f}%', style="yellow"),
            f'{row.get("win_rate_pct", 0):.1f}%',
            str(row.get("total_trades", 0)),
        ]
        if show_benchmark:
            cols.append(_pct_raw(row.get("alpha", 0)))
            cols.append(f'{row.get("beta", 0):.3f}')
        table.add_row(*cols)

    return table


def backtest_report_panel(
    symbol: str,
    strategy: str,
    period: str,
    metrics: dict[str, Any],
    benchmarks: Optional[dict[str, dict]] = None,
) -> Panel:
    """Rich Panel summarising a single backtest run."""
    lines = [
        f"初始资金 / Initial:  {metrics.get('start_value', 0):>12,.0f}     "
        f"最终净值 / Final:  {metrics.get('end_value', 0):>12,.0f}",
        "",
        f"  总收益率 / Return:   {_pct(metrics.get('total_return_pct', 0))}        "
        f"年化 / Annual:  {_pct(metrics.get('annual_return_pct', 0))}",
        f"  夏普 / Sharpe:  {metrics.get('sharpe_ratio', 0):>8.2f}            "
        f"最大回撤 / Max DD:  {Text(f'{metrics.get('max_drawdown_pct', 0):.2f}%', style='yellow')}",
        "",
        f"  交易次数 / Trades:  {metrics.get('total_trades', 0):>6}               "
        f"胜率 / Win Rate:  {metrics.get('win_rate_pct', 0):>6.1f}%",
        f"  盈利/亏损 / W/L: {metrics.get('winning_trades', 0)} / {metrics.get('losing_trades', 0)}        "
        f"盈亏比 / P/L Ratio:  {metrics.get('profit_factor', 0):>5.2f}",
        f"  平均盈利 / Avg Win:  {_pct(metrics.get('avg_win_pct', 0))}          "
        f"平均亏损 / Avg Loss:  {Text(f'{metrics.get('avg_loss_pct', 0):.2f}%', style='red')}",
    ]

    if benchmarks:
        lines.append("")
        for bm_name, bm in benchmarks.items():
            lines.append(
                f"  [{bm_name}]  收益/Return: {_pct(bm.get('benchmark_return_pct', 0))}  "
                f"超额/Excess: {_pct(bm.get('excess_return_pct', 0))}  "
                f"Alpha: {_pct_raw(bm.get('alpha', 0))}  "
                f"Beta: {bm.get('beta', 0):.3f}  "
                f"IR: {bm.get('information_ratio', 0):.2f}"
            )

    info_line = f"{symbol}  |  {strategy}  |  {period}"
    return Panel("\n".join(str(s) for s in lines), title=info_line, border_style="cyan")


def status_dashboard(data: dict[str, Any]) -> Layout:
    """System status dashboard layout."""
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
    )

    # Header
    version = data.get("version", "?")
    layout["header"].update(
        Panel(
            f"astock-trade v{version}    "
            f"数据目录 / Data: {data.get('data_dir', '?')}",
            style="bold white on blue",
        )
    )

    # Body — split into columns
    layout["body"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )

    # Left: services & config
    left_lines = [
        f"密钥 / Vault: {len(data.get('vault_services', []))} 个",
        f"策略 / Strategies: {len(data.get('strategies', []))}",
        f"自选股 / Watchlists: {sum(len(w.get('symbols', w.get('items', []))) for w in data.get('watchlists', []) if isinstance(w, dict))} 只",
    ]
    if "trading_hours" in data:
        th = data["trading_hours"]
        left_lines.append(f"交易时段 / Hours: {th.get('morning', '?')} | {th.get('afternoon', '?')}")

    layout["left"].update(Panel("\n".join(left_lines), title=f"系统概览 | Overview", border_style="green"))

    # Right: health (optional)
    right_parts = []
    health = data.get("health")
    if health:
        overall = health.get("overall", "unknown")
        style = "bold green" if overall == "ok" else "bold yellow" if overall == "degraded" else "bold red"
        right_parts.append(
            f"整体 / Status: {Text(overall.upper(), style=style)}"
        )
        right_parts.append(
            f"运行时间 / Uptime: {health.get('uptime_h', 0):.1f}h    "
            f"内存 / Memory: {health.get('memory_mb', 0):.0f}MB"
        )
        right_parts.append(
            f"子系统 / Subsystems: ok={health.get('ok', 0)}  "
            f"degraded={health.get('degraded', 0)}  "
            f"down={health.get('down', 0)}"
        )
        subs = health.get("subsystems", [])
        if subs:
            sub_table = Table(show_header=False, box=None, padding=(0, 1))
            sub_table.add_column("子系统 | Subsystem")
            sub_table.add_column("状态 | Status")
            sub_table.add_column("详情 | Detail")
            for s in subs:
                st = s.get("status", "?")
                tag = _bool_tag(st == "ok", "OK", st == "down" and "DOWN" or "WARN")
                sub_table.add_row(s.get("name", ""), tag, s.get("detail", ""))
            right_parts.append("")
            right_parts.append(sub_table)

        alerts = data.get("recent_alerts")
        if alerts:
            right_parts.append("")
            right_parts.append(Text(f"告警 / Alerts: {len(alerts)} 条", style="bold yellow"))
    else:
        right_parts.append("(使用 --health 查看详情 | Use --health for details)")

    layout["right"].update(
        Panel("\n".join(str(s) for s in right_parts), title=f"运行状态 | Status", border_style="blue")
    )

    return layout


def watchlist_table(watchlists: list[dict]) -> Table:
    """Format watchlists for display."""
    table = Table(title="自选股列表 | Watchlists", border_style="green")
    table.add_column("名称 | Name", style="cyan")
    table.add_column("代码 | Symbols", style="white")
    table.add_column("数量 | Count", justify="right")
    for wl in watchlists:
        symbols = wl.get("symbols", wl.get("items", []))
        table.add_row(
            wl.get("name", "?"),
            ", ".join(symbols[:10]) + ("..." if len(symbols) > 10 else ""),
            str(len(symbols)),
        )
    return table


def trade_journal_table(trades: list[dict]) -> Table:
    """Format trade journal entries."""
    table = Table(title=f"交易记录 | Trades ({len(trades)})", border_style="yellow")
    table.add_column("日期 | Date", style="cyan")
    table.add_column("代码 | Symbol", style="white")
    table.add_column("方向 | Side")
    table.add_column("价格 | Price", justify="right")
    table.add_column("数量 | Shares", justify="right")
    table.add_column("盈亏 | P&L", justify="right")
    table.add_column("策略/备注 | Strategy", style="dim")

    for t in trades:
        direction = t.get("direction", "")
        dir_text = Text(direction)
        dir_text.stylize("bold green" if direction == "BUY" else "bold red")

        pnl = t.get("pnl")
        pnl_text = Text(f"{pnl:+.2f}" if pnl is not None else "-")
        if pnl is not None:
            pnl_text.stylize("green" if pnl > 0 else "red" if pnl < 0 else "")

        table.add_row(
            str(t.get("date", "")),
            t.get("symbol", ""),
            dir_text,
            f'{t.get("price", 0):.2f}',
            str(t.get("volume", 0)),
            pnl_text,
            t.get("strategy", t.get("reason", "")),
        )
    return table


def pnl_summary_table(summary: dict) -> Panel:
    """Daily P&L summary panel."""
    lines = [
        f"  总盈亏 / Total P&L:  {_pct(summary.get('total_pnl', 0))}",
        f"  交易 / Trades:  {summary.get('total_trades', 0)} 笔",
        f"  盈利 / Wins:  {summary.get('winning_trades', 0)}",
        f"  亏损 / Losses:  {summary.get('losing_trades', 0)}",
        f"  胜率 / Win Rate:  {summary.get('win_rate', 0):.1f}%",
        f"  最大盈利 / Max Win:  {_pct_raw(summary.get('max_win', 0))}",
        f"  最大亏损 / Max Loss:  {Text(f'{summary.get('max_loss', 0):.2f}', style='red')}",
    ]
    return Panel("\n".join(lines), title="盈亏汇总 | P&L Summary", border_style="green")


def format_risk_decision(d: dict) -> Panel:
    """Visualise a risk-engine decision."""
    decision = d.get("decision", "?")
    dec_style = {
        "APPROVED": "bold green",
        "WARN": "bold yellow",
        "REJECTED": "bold red",
    }.get(decision, "bold white")

    lines = [
        f"  标的 / Symbol:  {d.get('signal_symbol', '')}  {d.get('signal_direction', '')}  "
        f"{d.get('signal_price', 0):.2f} × {d.get('signal_volume', 0)}",
        f"  调整后量 / Adj. Volume:  {d.get('adjusted_volume', 0)}",
        f"  原因 / Reason:  {d.get('reason', '')}",
        "",
        "  检查明细 / Checks:",
    ]
    for c in d.get("check_details", []):
        ok = c.get("passed", False)
        prefix = _bool_tag(ok, "  PASS", "  FAIL")
        lines.append(f"    {prefix}  {c.get('rule', '')}  —  {c.get('detail', '')}")

    return Panel(
        "\n".join(str(s) for s in lines),
        title=Text(f"风控决策 | Risk: {decision}", style=dec_style),
        border_style=dec_style.split()[-1] if " " in dec_style else dec_style,
    )
