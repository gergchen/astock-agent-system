"""CLI entry point — astock-trade command via Typer.

Usage:
    astock-trade journal record 600519 BUY 1850.00 100
    astock-trade journal query --start 2026-05-01 --end 2026-05-15
    astock-trade strategy save my_algo '{"ma_short":5,"ma_long":20}'
    astock-trade watchlist save default 600519 000001
    astock-trade vault store eastmoney
"""

import json
import sys
from datetime import date, datetime
from typing import Optional

import typer

from . import __version__
from .config import get_config
from .utils.cli_ui import console

app = typer.Typer(
    name="astock-trade",
    help="A-Stock Trade — personal & multi-agent trading system.",
    add_completion=False,
)

journal_app = typer.Typer(help="Trade journal — record and query trades")
strategy_app = typer.Typer(help="Strategy store — versioned strategy configs")
watchlist_app = typer.Typer(help="Watchlist management")
vault_app = typer.Typer(help="Credential vault — encrypted API key storage")
broker_app = typer.Typer(help="Broker — place orders and check positions")

app.add_typer(journal_app, name="journal")
app.add_typer(strategy_app, name="strategy")
app.add_typer(watchlist_app, name="watchlist")
app.add_typer(vault_app, name="vault")
backtest_app = typer.Typer(help="Backtest — replay history through strategies")
app.add_typer(broker_app, name="broker")
app.add_typer(backtest_app, name="backtest")


def _emit(data, fmt: str = "json"):
    if fmt == "json":
        envelope = {
            "_meta": {
                "source": "astock-trade-cli",
                "timestamp": date.today().isoformat(),
                "version": __version__,
            },
            "data": data,
        }
        console.print_json(json.dumps(envelope, ensure_ascii=False, default=str))
    else:
        console.print(data)


# ── Journal Commands ────────────────────────────────────────────

@journal_app.command(name="record")
def journal_record(
    symbol: str = typer.Argument(..., help="6-digit stock code"),
    direction: str = typer.Argument(..., help="BUY or SELL"),
    price: float = typer.Argument(..., help="Trade price"),
    volume: int = typer.Argument(..., help="Trade volume (shares, multiples of 100)"),
    strategy: Optional[str] = typer.Option(None, "-s", help="Strategy name"),
    notes: Optional[str] = typer.Option(None, "-n", help="Trade notes"),
):
    """Record a trade in the journal."""
    from .trade_journal import record_trade
    trade = record_trade(symbol, direction, price, volume, strategy, notes)
    _emit(trade)


@journal_app.command(name="query")
def journal_query(
    start_date: Optional[str] = typer.Option(None, "--start", help="Start date YYYY-MM-DD"),
    end_date: Optional[str] = typer.Option(None, "--end", help="End date YYYY-MM-DD"),
    symbol: Optional[str] = typer.Option(None, "--symbol", help="Filter by symbol"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON output (machine-readable)"),
):
    """Query trade records in date range."""
    from .trade_journal import query_trades
    sd = date.fromisoformat(start_date) if start_date else date.today()
    ed = date.fromisoformat(end_date) if end_date else date.today()
    records = query_trades(sd, ed, symbol)
    if json_out:
        _emit(records)
    else:
        from .utils.cli_ui import trade_journal_table
        console.print(trade_journal_table(records))


@journal_app.command(name="pnl")
def journal_pnl(
    d: Optional[str] = typer.Option(None, "--date", "-d", help="Date YYYY-MM-DD"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON output (machine-readable)"),
):
    """Compute daily P&L."""
    from .trade_journal import daily_pnl
    dt = date.fromisoformat(d) if d else date.today()
    result = daily_pnl(dt)
    if json_out:
        _emit(result)
    else:
        from .utils.cli_ui import pnl_summary_table
        console.print(pnl_summary_table(result))


@journal_app.command(name="summary")
def journal_summary(
    start_date: str = typer.Option(..., "--start", help="Start date YYYY-MM-DD"),
    end_date: str = typer.Option(..., "--end", help="End date YYYY-MM-DD"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON output (machine-readable)"),
):
    """Aggregated trade summary over a date range."""
    from .trade_journal import trade_summary
    result = trade_summary(date.fromisoformat(start_date), date.fromisoformat(end_date))
    if json_out:
        _emit(result)
    else:
        from .utils.cli_ui import pnl_summary_table
        console.print(pnl_summary_table(result))


# ── Strategy Commands ───────────────────────────────────────────

@strategy_app.command(name="save")
def strategy_save(
    name: str = typer.Argument(..., help="Strategy name"),
    params_json: str = typer.Argument(..., help="Strategy params as JSON string"),
):
    """Save a strategy (appends a new version)."""
    from .strategy_store import save_strategy
    params = json.loads(params_json)
    p = save_strategy(name, params)
    _emit({"saved": str(p), "name": name})


@strategy_app.command(name="load")
def strategy_load(
    name: str = typer.Argument(..., help="Strategy name"),
    version: Optional[int] = typer.Option(None, "-v", help="Specific version"),
):
    """Load a strategy (latest version by default)."""
    from .strategy_store import load_strategy
    params = load_strategy(name, version)
    _emit({"name": name, "version": version, "params": params})


@strategy_app.command(name="list")
def strategy_list():
    """List all saved strategies."""
    from .strategy_store import list_strategies
    _emit(list_strategies())


@strategy_app.command(name="history")
def strategy_history(
    name: str = typer.Argument(..., help="Strategy name"),
):
    """Get all versions of a strategy."""
    from .strategy_store import get_strategy_history
    _emit(get_strategy_history(name))


# ── Watchlist Commands ──────────────────────────────────────────

@watchlist_app.command(name="save")
def watchlist_save(
    user_id: str = typer.Option("default", "--user", "-u", help="User ID"),
    name: str = typer.Argument(..., help="Watchlist name"),
    symbols: list[str] = typer.Argument(..., help="Stock symbols"),
):
    """Save a named watchlist."""
    from .user_store import save_watchlist
    p = save_watchlist(user_id, name, symbols)
    _emit({"saved": str(p), "name": name, "count": len(symbols)})


@watchlist_app.command(name="get")
def watchlist_get(
    user_id: str = typer.Option("default", "--user", "-u", help="User ID"),
    name: str = typer.Argument(..., help="Watchlist name"),
):
    """Get a watchlist by name."""
    from .user_store import get_watchlist
    wl = get_watchlist(user_id, name)
    _emit(wl or {"error": "not found"})


@watchlist_app.command(name="list")
def watchlist_list(
    user_id: str = typer.Option("default", "--user", "-u", help="User ID"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON output (machine-readable)"),
):
    """List all watchlists for a user."""
    from .user_store import list_watchlists
    data = list_watchlists(user_id)
    if json_out:
        _emit(data)
    else:
        from .utils.cli_ui import watchlist_table
        console.print(watchlist_table(data))


@watchlist_app.command(name="delete")
def watchlist_delete(
    user_id: str = typer.Option("default", "--user", "-u", help="User ID"),
    name: str = typer.Argument(..., help="Watchlist name"),
):
    """Delete a watchlist."""
    from .user_store import delete_watchlist
    ok = delete_watchlist(user_id, name)
    _emit({"deleted": ok})


# ── Vault Commands ──────────────────────────────────────────────

@vault_app.command(name="store")
def vault_store(
    service: str = typer.Argument(..., help="Service name (e.g. eastmoney, xt)"),
):
    """Store credentials interactively."""
    from .keyvault import store_credential
    import getpass
    print(f"Enter credentials for {service}:")
    api_key = getpass.getpass("  API Key: ")
    api_secret = getpass.getpass("  API Secret (optional): ")
    creds = {"api_key": api_key}
    if api_secret:
        creds["api_secret"] = api_secret
    store_credential(service, creds)
    _emit({"stored": service})


@vault_app.command(name="load")
def vault_load(
    service: str = typer.Argument(..., help="Service name"),
):
    """Load stored credentials (shows keys only, not values)."""
    from .keyvault import load_credential
    creds = load_credential(service)
    _emit({k: "***" for k in creds})


@vault_app.command(name="delete")
def vault_delete(
    service: str = typer.Argument(..., help="Service name"),
):
    """Delete stored credentials."""
    from .keyvault import delete_credential
    ok = delete_credential(service)
    _emit({"deleted": ok})


@vault_app.command(name="list")
def vault_list():
    """List all services with stored credentials."""
    from .keyvault import list_services
    _emit(list_services())


@app.command(name="version")
def show_version():
    """Show version."""
    from .utils.cli_ui import console
    console.print(f"[bold cyan]astock-trade[/bold cyan] [green]v{__version__}[/green]")


@app.command(name="status")
def status(
    health: bool = typer.Option(False, "--health", "-H", help="Full health check across subsystems"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON output (machine-readable)"),
):
    """Show system status — config, directories, vault info. Use -H for health check."""
    from .keyvault import list_services
    from .user_store import list_watchlists
    from .strategy_store import list_strategies
    cfg = get_config()

    data = {
        "version": __version__,
        "data_dir": str(cfg.data_dir),
        "vault_services": list_services(),
        "strategies": list_strategies(),
        "watchlists": list_watchlists("default"),
        "trading_hours": {
            "morning": f"{cfg.morning_open}-{cfg.morning_close}",
            "afternoon": f"{cfg.afternoon_open}-{cfg.afternoon_close}",
        },
    }

    if health:
        from .monitor import check_all
        h = check_all()
        data["health"] = {
            "overall": h.overall,
            "uptime_h": round(h.uptime_sec / 3600, 2),
            "memory_mb": round(h.memory_mb, 1),
            "ok": h.ok_count,
            "degraded": h.degraded_count,
            "down": h.down_count,
            "checked_at": h.checked_at,
            "subsystems": [
                {
                    "name": s.name,
                    "status": s.status,
                    "detail": s.detail,
                    "metrics": s.metrics,
                }
                for s in h.subsystems
            ],
        }
        try:
            from .utils.alerting import FileAlertChannel
            ch = FileAlertChannel()
            data["recent_alerts"] = ch.history(10)
        except Exception:
            pass

    if json_out:
        _emit(data)
    else:
        from .utils.cli_ui import status_dashboard
        console.print(status_dashboard(data))


# ── Broker Commands ──────────────────────────────────────────────

@broker_app.command(name="account")
def broker_account(
    ths: bool = typer.Option(False, "--ths", help="Use THS broker (virtual account)"),
):
    """Show current account status."""
    if ths:
        from .broker.ths_broker import THSBroker
        b = THSBroker()
    else:
        from .broker.mock_broker import MockBroker
        b = MockBroker()
    b.connect()
    acct = b.get_account()
    _emit({
        "cash": acct.cash,
        "frozen": acct.frozen,
        "total_assets": acct.total_assets,
        "positions": [
            {"symbol": p.symbol, "volume": p.volume, "avg_cost": p.avg_cost,
             "market_value": p.market_value, "pnl": p.pnl, "pnl_pct": p.pnl_pct}
            for p in (acct.positions or [])
        ],
    })


@broker_app.command(name="buy")
def broker_buy(
    symbol: str = typer.Argument(..., help="6-digit stock code"),
    price: float = typer.Argument(..., help="Trade price"),
    volume: int = typer.Argument(..., help="Trade volume"),
    ths: bool = typer.Option(False, "--ths", help="Use THS broker"),
):
    """Place a buy order."""
    if ths:
        from .broker.ths_broker import THSBroker
        b = THSBroker()
    else:
        from .broker.mock_broker import MockBroker
        b = MockBroker()
    from .broker.base import OrderSide
    b.connect()
    order = b.place_order(symbol, OrderSide.BUY, price, volume)
    _emit({
        "order_id": order.order_id,
        "symbol": order.symbol,
        "side": "BUY",
        "price": order.price,
        "volume": order.volume,
        "status": order.status.value,
    })


@broker_app.command(name="sell")
def broker_sell(
    symbol: str = typer.Argument(..., help="6-digit stock code"),
    price: float = typer.Argument(..., help="Trade price"),
    volume: int = typer.Argument(..., help="Trade volume"),
    ths: bool = typer.Option(False, "--ths", help="Use THS broker"),
):
    """Place a sell order."""
    if ths:
        from .broker.ths_broker import THSBroker
        b = THSBroker()
    else:
        from .broker.mock_broker import MockBroker
        b = MockBroker()
    from .broker.base import OrderSide
    b.connect()
    order = b.place_order(symbol, OrderSide.SELL, price, volume)
    _emit({
        "order_id": order.order_id,
        "symbol": order.symbol,
        "side": "SELL",
        "price": order.price,
        "volume": order.volume,
        "status": order.status.value,
    })


@broker_app.command(name="orders")
def broker_orders(
    symbol: Optional[str] = typer.Option(None, "--symbol", help="Filter by symbol"),
    ths: bool = typer.Option(False, "--ths", help="Use THS broker"),
):
    """List all orders."""
    if ths:
        from .broker.ths_broker import THSBroker
        b = THSBroker()
    else:
        from .broker.mock_broker import MockBroker
        b = MockBroker()
    b.connect()
    orders = b.get_orders(symbol)
    _emit([
        {"order_id": o.order_id, "symbol": o.symbol, "side": o.side.value,
         "price": o.price, "volume": o.volume, "status": o.status.value}
        for o in orders
    ])


# ── Backtest Commands ─────────────────────────────────────────────

@backtest_app.command(name="run")
def backtest_run(
    symbol: str = typer.Argument(..., help="6-digit stock code"),
    strategy: str = typer.Option("ma_crossover", "--strategy", "-s", help="Strategy name"),
    fast: int = typer.Option(5, "--fast", help="MA fast period (for ma_crossover)"),
    slow: int = typer.Option(20, "--slow", help="MA slow period (for ma_crossover)"),
    lookback: int = typer.Option(20, "--lookback", help="Lookback period (for breakout)"),
    threshold: float = typer.Option(3.0, "--threshold", help="Breakout threshold pct"),
    start_date: str = typer.Option("2024-01-01", "--start", help="Start date YYYY-MM-DD"),
    end_date: str = typer.Option("2024-12-31", "--end", help="End date YYYY-MM-DD"),
    cash: float = typer.Option(100_000, "--cash", help="Initial cash"),
    commission: str = typer.Option("ashare", "--commission", "-c", help="Commission model: ashare, fixed"),
    slippage: str = typer.Option("tick", "--slippage", help="Slippage model: tick, fixed, volume"),
    benchmark: Optional[str] = typer.Option(None, "--benchmark", "-b", help="Benchmark codes: 000300,000905"),
    save: Optional[str] = typer.Option(None, "--save", help="Save result to JSON file"),
    data_file: Optional[str] = typer.Option(None, "--data", help="CSV file with OHLCV data"),
):
    """Run a backtest for a single stock."""
    from .backtest.engine import BacktestEngine
    from .backtest.models import get_commission_model, get_slippage_model
    from .backtest.strategy_registry import get as get_strategy, list_names

    strat_fn = get_strategy(strategy)
    if strat_fn is None:
        print(f"Unknown strategy: {strategy}. Available: {', '.join(list_names())}")
        raise typer.Exit(1)

    # Build params from CLI flags — merge with strategy defaults
    cli_overrides = {"fast": fast, "slow": slow, "lookback": lookback, "threshold_pct": threshold}
    from .backtest.strategy_registry import get_info
    info = get_info(strategy)
    params = {**info["defaults"]} if info else {}
    for k, v in cli_overrides.items():
        if k in params:
            params[k] = v

    bm_codes = benchmark.split(",") if benchmark else None

    engine = BacktestEngine(
        initial_cash=cash,
        commission_model=get_commission_model(commission),
        slippage_model=get_slippage_model(slippage),
        benchmark=bm_codes,
    )

    df = None
    if data_file:
        import pandas as pd
        df = pd.read_csv(data_file)

    try:
        result = engine.run(
            symbol=symbol,
            strategy=strat_fn,
            strategy_params=params,
            start_date=start_date,
            end_date=end_date,
            df=df,
        )
    except Exception as e:
        console.print(f"[red]回测失败: {e}[/red]")
        raise typer.Exit(1)

    if json_out:
        _emit(result.to_dict())
    else:
        from .utils.cli_ui import backtest_report_panel
        metrics = result.to_dict()
        benchmarks = {}
        for k, v in metrics.items():
            if k.startswith("bm_"):
                parts = k.split("_", 2)
                if len(parts) >= 3:
                    bm_name = parts[1]
                    field = parts[2]
                    benchmarks.setdefault(bm_name, {})[field] = v
        console.print(backtest_report_panel(
            symbol, strategy, f"{start_date} → {end_date}", metrics, benchmarks or None,
        ))

    if save:
        result.save(save)
        console.print(f"\n[green]结果已保存: {save}[/green]")


@backtest_app.command(name="compare")
def backtest_compare(
    symbol: str = typer.Argument(..., help="6-digit stock code"),
    start_date: str = typer.Option("2024-01-01", "--start", help="Start date"),
    end_date: str = typer.Option("2024-12-31", "--end", help="End date"),
    cash: float = typer.Option(100_000, "--cash", help="Initial cash"),
    commission: str = typer.Option("ashare", "--commission", "-c", help="Commission model: ashare, fixed"),
    slippage: str = typer.Option("tick", "--slippage", help="Slippage model: tick, fixed, volume"),
    benchmark: Optional[str] = typer.Option(None, "--benchmark", "-b", help="Benchmark codes: 000300,000905"),
    data_file: Optional[str] = typer.Option(None, "--data", help="CSV file with OHLCV data"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON output (machine-readable)"),
):
    """Compare multiple strategies on the same stock."""
    from .backtest.engine import BacktestEngine
    from .backtest.models import get_commission_model, get_slippage_model
    from .backtest.strategy_registry import list_all

    all_strategies = list_all()
    strategies = [
        (info["description"], info["fn"], info["defaults"])
        for info in all_strategies.values()
    ]

    bm_codes = benchmark.split(",") if benchmark else None

    engine = BacktestEngine(
        initial_cash=cash,
        commission_model=get_commission_model(commission),
        slippage_model=get_slippage_model(slippage),
        benchmark=bm_codes,
    )

    df = None
    if data_file:
        import pandas as pd
        df = pd.read_csv(data_file)

    results = []
    for name, fn, params in strategies:
        try:
            r = engine.run(
                symbol=symbol,
                strategy=fn,
                strategy_params=params,
                start_date=start_date,
                end_date=end_date,
                df=df,
            )
            results.append((name, r))
        except Exception as e:
            print(f"  {name}: 跳过 ({e})")

    if not results:
        print("所有策略都无法运行")
        raise typer.Exit(1)

    # Build rows for table display
    rows = []
    bm_names = set()
    for name, r in results:
        m = r.metrics
        row = {
            "name": name,
            "total_return_pct": m.total_return_pct,
            "annual_return_pct": m.annual_return_pct,
            "sharpe_ratio": m.sharpe_ratio,
            "max_drawdown_pct": m.max_drawdown_pct,
            "win_rate_pct": m.win_rate_pct,
            "total_trades": m.total_trades,
        }
        for bm_name, bm in m.benchmarks.items():
            row[f"alpha"] = bm.alpha
            row[f"beta"] = bm.beta
            bm_names.add(bm_name)
        rows.append(row)

    if json_out:
        _emit(rows)
    else:
        from .utils.cli_ui import backtest_result_table
        console.print(backtest_result_table(rows, f"多策略对比 — {symbol}", show_benchmark=bool(bm_names)))

    # Show benchmark comparison if enabled
    if benchmark and results and not json_out:
        bm_name = {"000300": "CSI300", "000905": "CSI500"}.get(bm_codes[0] if bm_codes else "", "")
        if bm_name and any(bm_name in r.metrics.benchmarks for _, r in results):
            from rich.table import Table
            bt = Table(title=f"{bm_name} 基准对比", border_style="cyan")
            bt.add_column("策略", style="cyan")
            bt.add_column("Alpha", justify="right")
            bt.add_column("Beta", justify="right")
            bt.add_column("信息比", justify="right")
            bt.add_column("超额", justify="right")
            bt.add_column("跟踪误差", justify="right")
            for name, r in results:
                bm = r.metrics.benchmarks.get(bm_name)
                if bm:
                    bt.add_row(
                        name,
                        f"{bm.alpha:+.2f}%",
                        f"{bm.beta:.3f}",
                        f"{bm.information_ratio:.2f}",
                        f"{bm.excess_return_pct:+.2f}%",
                        f"{bm.tracking_error_pct:.2f}%",
                    )
            console.print(bt)


@backtest_app.command(name="batch")
def backtest_batch(
    symbols: list[str] = typer.Argument(..., help="Stock codes to backtest"),
    strategy: str = typer.Option("ma_crossover", "--strategy", "-s", help="Strategy name"),
    start_date: str = typer.Option("2024-01-01", "--start", help="Start date"),
    end_date: str = typer.Option("2024-12-31", "--end", help="End date"),
    cash: float = typer.Option(100_000, "--cash", help="Initial cash"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON output (machine-readable)"),
):
    """Run backtest on multiple stocks with the same strategy."""
    from .backtest.engine import BacktestEngine
    from .backtest.strategy_registry import get as get_strategy, get_info, list_names

    strat_fn = get_strategy(strategy)
    if strat_fn is None:
        print(f"Unknown strategy: {strategy}. Available: {', '.join(list_names())}")
        raise typer.Exit(1)

    info = get_info(strategy)
    params = info["defaults"] if info else {}

    engine = BacktestEngine(initial_cash=cash)

    rows = []
    for sym in symbols:
        try:
            r = engine.run(
                symbol=sym,
                strategy=strat_fn,
                strategy_params=params,
                start_date=start_date,
                end_date=end_date,
            )
            m = r.metrics
            rows.append({
                "symbol": sym,
                "total_return_pct": m.total_return_pct,
                "annual_return_pct": m.annual_return_pct,
                "sharpe_ratio": m.sharpe_ratio,
                "max_drawdown_pct": m.max_drawdown_pct,
                "win_rate_pct": m.win_rate_pct,
                "total_trades": m.total_trades,
            })
        except Exception as e:
            rows.append({"symbol": sym, "error": str(e)})

    if json_out:
        _emit(rows)
    else:
        from .utils.cli_ui import backtest_result_table
        valid = [r for r in rows if "error" not in r]
        if valid:
            console.print(backtest_result_table(valid, f"批量回测 — {strategy}"))
        failed = [r for r in rows if "error" in r]
        if failed:
            for f in failed:
                console.print(f"[red]✗[/red] {f['symbol']}: {f['error']}")


if __name__ == "__main__":
    app()
