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
    help="A股多Agent交易系统 | A-Stock Multi-Agent Trading System",
    add_completion=False,
)

journal_app = typer.Typer(help="交易日志 | Trade journal — record and query trades")
strategy_app = typer.Typer(help="策略存储 | Strategy store — versioned configs")
watchlist_app = typer.Typer(help="自选股 | Watchlist management")
vault_app = typer.Typer(help="凭证库 | Credential vault — encrypted API key storage")
broker_app = typer.Typer(help="交易 | Broker — place orders and check positions")

app.add_typer(journal_app, name="journal")
app.add_typer(strategy_app, name="strategy")
app.add_typer(watchlist_app, name="watchlist")
app.add_typer(vault_app, name="vault")
backtest_app = typer.Typer(help="回测 | Backtest — replay history through strategies")
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
    symbol: str = typer.Argument(..., help="股票代码, 6位 | 6-digit stock code"),
    direction: str = typer.Argument(..., help="买卖方向 | BUY or SELL"),
    price: float = typer.Argument(..., help="成交价 | Trade price"),
    volume: int = typer.Argument(..., help="数量(股) | Trade volume (shares, multiples of 100)"),
    strategy: Optional[str] = typer.Option(None, "-s", help="策略名称 | Strategy name"),
    notes: Optional[str] = typer.Option(None, "-n", help="备注 | Trade notes"),
):
    """记录一笔交易 | Record a trade in the journal."""
    from .trade_journal import record_trade
    trade = record_trade(symbol, direction, price, volume, strategy, notes)
    _emit(trade)


@journal_app.command(name="query")
def journal_query(
    start_date: Optional[str] = typer.Option(None, "--start", help="开始日期 | Start date YYYY-MM-DD"),
    end_date: Optional[str] = typer.Option(None, "--end", help="结束日期 | End date YYYY-MM-DD"),
    symbol: Optional[str] = typer.Option(None, "--symbol", help="筛选代码 | Filter by symbol"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON输出 | JSON output (machine-readable)"),
):
    """查询交易记录 | Query trade records in date range."""
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
    d: Optional[str] = typer.Option(None, "--date", "-d", help="日期 | Date YYYY-MM-DD"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON输出 | JSON output (machine-readable)"),
):
    """计算每日盈亏 | Compute daily P&L."""
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
    start_date: str = typer.Option(..., "--start", help="开始日期 | Start date YYYY-MM-DD"),
    end_date: str = typer.Option(..., "--end", help="结束日期 | End date YYYY-MM-DD"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON输出 | JSON output (machine-readable)"),
):
    """交易汇总 | Aggregated trade summary over a date range."""
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
    name: str = typer.Argument(..., help="策略名称 | Strategy name"),
    params_json: str = typer.Argument(..., help="策略参数JSON | Strategy params as JSON string"),
):
    """保存策略（追加新版本）| Save a strategy (appends a new version)."""
    from .strategy_store import save_strategy
    params = json.loads(params_json)
    p = save_strategy(name, params)
    _emit({"saved": str(p), "name": name})


@strategy_app.command(name="load")
def strategy_load(
    name: str = typer.Argument(..., help="策略名称 | Strategy name"),
    version: Optional[int] = typer.Option(None, "-v", help="指定版本 | Specific version"),
):
    """加载策略（默认最新版）| Load a strategy (latest version by default)."""
    from .strategy_store import load_strategy
    params = load_strategy(name, version)
    _emit({"name": name, "version": version, "params": params})


@strategy_app.command(name="list")
def strategy_list():
    """列出所有策略 | List all saved strategies."""
    from .strategy_store import list_strategies
    _emit(list_strategies())


@strategy_app.command(name="history")
def strategy_history(
    name: str = typer.Argument(..., help="策略名称 | Strategy name"),
):
    """查看所有版本 | Get all versions of a strategy."""
    from .strategy_store import get_strategy_history
    _emit(get_strategy_history(name))


# ── Watchlist Commands ──────────────────────────────────────────

@watchlist_app.command(name="save")
def watchlist_save(
    user_id: str = typer.Option("default", "--user", "-u", help="用户ID | User ID"),
    name: str = typer.Argument(..., help="自选股名称 | Watchlist name"),
    symbols: list[str] = typer.Argument(..., help="股票代码 | Stock symbols"),
):
    """保存自选股 | Save a named watchlist."""
    from .user_store import save_watchlist
    p = save_watchlist(user_id, name, symbols)
    _emit({"saved": str(p), "name": name, "count": len(symbols)})


@watchlist_app.command(name="get")
def watchlist_get(
    user_id: str = typer.Option("default", "--user", "-u", help="用户ID | User ID"),
    name: str = typer.Argument(..., help="自选股名称 | Watchlist name"),
):
    """获取自选股 | Get a watchlist by name."""
    from .user_store import get_watchlist
    wl = get_watchlist(user_id, name)
    _emit(wl or {"error": "not found"})


@watchlist_app.command(name="list")
def watchlist_list(
    user_id: str = typer.Option("default", "--user", "-u", help="用户ID | User ID"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON输出 | JSON output (machine-readable)"),
):
    """列出自选股 | List all watchlists for a user."""
    from .user_store import list_watchlists
    data = list_watchlists(user_id)
    if json_out:
        _emit(data)
    else:
        from .utils.cli_ui import watchlist_table
        console.print(watchlist_table(data))


@watchlist_app.command(name="delete")
def watchlist_delete(
    user_id: str = typer.Option("default", "--user", "-u", help="用户ID | User ID"),
    name: str = typer.Argument(..., help="自选股名称 | Watchlist name"),
):
    """删除自选股 | Delete a watchlist."""
    from .user_store import delete_watchlist
    ok = delete_watchlist(user_id, name)
    _emit({"deleted": ok})


# ── Vault Commands ──────────────────────────────────────────────

@vault_app.command(name="store")
def vault_store(
    service: str = typer.Argument(..., help="服务名称(如 eastmoney, xt) | Service name"),
):
    """交互式存储凭证 | Store credentials interactively."""
    from .keyvault import store_credential
    import getpass
    print(f"输入 {service} 凭证 | Enter credentials for {service}:")
    api_key = getpass.getpass("  API Key: ")
    api_secret = getpass.getpass("  API Secret (可选 | optional): ")
    creds = {"api_key": api_key}
    if api_secret:
        creds["api_secret"] = api_secret
    store_credential(service, creds)
    _emit({"stored": service})


@vault_app.command(name="load")
def vault_load(
    service: str = typer.Argument(..., help="服务名称 | Service name"),
):
    """加载凭证（仅显示键名）| Load stored credentials (shows keys only)."""
    from .keyvault import load_credential
    creds = load_credential(service)
    _emit({k: "***" for k in creds})


@vault_app.command(name="delete")
def vault_delete(
    service: str = typer.Argument(..., help="服务名称 | Service name"),
):
    """删除凭证 | Delete stored credentials."""
    from .keyvault import delete_credential
    ok = delete_credential(service)
    _emit({"deleted": ok})


@vault_app.command(name="list")
def vault_list():
    """列出所有凭证服务 | List all services with stored credentials."""
    from .keyvault import list_services
    _emit(list_services())


@app.command(name="version")
def show_version():
    """显示版本 | Show version."""
    from .utils.cli_ui import console
    console.print(f"[bold cyan]astock-trade[/bold cyan] [green]v{__version__}[/green]")


@app.command(name="status")
def status(
    health: bool = typer.Option(False, "--health", "-H", help="健康检查 | Full health check across subsystems"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON输出 | JSON output (machine-readable)"),
):
    """系统状态 — 配置/目录/凭证/策略/自选股 | Show system status."""
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
    ths: bool = typer.Option(False, "--ths", help="使用同花顺(虚拟) | Use THS broker"),
):
    """查看账户状态 | Show current account status."""
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
    symbol: str = typer.Argument(..., help="6位股票代码 | 6-digit stock code"),
    price: float = typer.Argument(..., help="买入价 | Trade price"),
    volume: int = typer.Argument(..., help="买入数量(股) | Trade volume"),
    ths: bool = typer.Option(False, "--ths", help="使用同花顺 | Use THS broker"),
):
    """买入 | Place a buy order."""
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
    symbol: str = typer.Argument(..., help="6位股票代码 | 6-digit stock code"),
    price: float = typer.Argument(..., help="卖出价 | Trade price"),
    volume: int = typer.Argument(..., help="卖出数量(股) | Trade volume"),
    ths: bool = typer.Option(False, "--ths", help="使用同花顺 | Use THS broker"),
):
    """卖出 | Place a sell order."""
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
    symbol: Optional[str] = typer.Option(None, "--symbol", help="筛选代码 | Filter by symbol"),
    ths: bool = typer.Option(False, "--ths", help="使用同花顺 | Use THS broker"),
):
    """查看所有委托 | List all orders."""
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
    symbol: str = typer.Argument(..., help="6位股票代码 | 6-digit stock code"),
    strategy: str = typer.Option("ma_crossover", "--strategy", "-s", help="策略名称 | Strategy name"),
    fast: int = typer.Option(5, "--fast", help="MA短周期 | MA fast period (ma_crossover)"),
    slow: int = typer.Option(20, "--slow", help="MA长周期 | MA slow period (ma_crossover)"),
    lookback: int = typer.Option(20, "--lookback", help="回看天数 | Lookback period (breakout)"),
    threshold: float = typer.Option(3.0, "--threshold", help="突破阈值(%) | Breakout threshold pct"),
    start_date: str = typer.Option("2024-01-01", "--start", help="开始日期 | Start date YYYY-MM-DD"),
    end_date: str = typer.Option("2024-12-31", "--end", help="结束日期 | End date YYYY-MM-DD"),
    cash: float = typer.Option(100_000, "--cash", help="初始资金 | Initial cash"),
    commission: str = typer.Option("ashare", "--commission", "-c", help="佣金模型(ashare/fixed) | Commission model"),
    slippage: str = typer.Option("tick", "--slippage", help="滑点模型(tick/fixed/volume) | Slippage model"),
    benchmark: Optional[str] = typer.Option(None, "--benchmark", "-b", help="基准代码(如000300,000905) | Benchmark codes"),
    save: Optional[str] = typer.Option(None, "--save", help="保存结果到JSON文件 | Save result to JSON"),
    data_file: Optional[str] = typer.Option(None, "--data", help="CSV数据文件 | CSV file with OHLCV data"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON输出 | JSON output (machine-readable)"),
    max_trade_pct: float = typer.Option(0.95, "--max-trade-pct", help="单笔交易上限 | Max trade pct of assets"),
):
    """回测单个标的 | Run a backtest for a single stock."""
    from .backtest.engine import BacktestEngine
    from .backtest.models import get_commission_model, get_slippage_model
    from .backtest.strategy_registry import get as get_strategy, list_names

    strat_fn = get_strategy(strategy)
    if strat_fn is None:
        console.print(f"[red]未知策略 / Unknown strategy: {strategy}[/red]")
        console.print(f"可用策略 / Available: [green]{', '.join(list_names())}[/green]")
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
        single_trade_pct=max_trade_pct,
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
    symbol: str = typer.Argument(..., help="6位股票代码 | 6-digit stock code"),
    start_date: str = typer.Option("2024-01-01", "--start", help="开始日期 | Start date"),
    end_date: str = typer.Option("2024-12-31", "--end", help="结束日期 | End date"),
    cash: float = typer.Option(100_000, "--cash", help="初始资金 | Initial cash"),
    commission: str = typer.Option("ashare", "--commission", "-c", help="佣金模型 | Commission model: ashare, fixed"),
    slippage: str = typer.Option("tick", "--slippage", help="滑点模型 | Slippage model: tick, fixed, volume"),
    benchmark: Optional[str] = typer.Option(None, "--benchmark", "-b", help="基准代码 | Benchmark codes: 000300,000905"),
    data_file: Optional[str] = typer.Option(None, "--data", help="CSV数据文件 | CSV file with OHLCV data"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON输出 | JSON output (machine-readable)"),
):
    """多策略对比 | Compare multiple strategies on the same stock."""
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
            console.print(f"  [yellow]{name}: 跳过 / Skipped ({e})[/yellow]")

    if not results:
        console.print("[red]所有策略都无法运行 | All strategies failed to run[/red]")
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
        console.print(backtest_result_table(rows, f"多策略对比 / Strategy Compare — {symbol}", show_benchmark=bool(bm_names)))

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
    symbols: list[str] = typer.Argument(..., help="股票代码列表 | Stock codes to backtest"),
    strategy: str = typer.Option("ma_crossover", "--strategy", "-s", help="策略名称 | Strategy name"),
    start_date: str = typer.Option("2024-01-01", "--start", help="开始日期 | Start date"),
    end_date: str = typer.Option("2024-12-31", "--end", help="结束日期 | End date"),
    cash: float = typer.Option(100_000, "--cash", help="初始资金 | Initial cash"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON输出 | JSON output (machine-readable)"),
):
    """批量回测 | Run backtest on multiple stocks with the same strategy."""
    from .backtest.engine import BacktestEngine
    from .backtest.strategy_registry import get as get_strategy, get_info, list_names

    strat_fn = get_strategy(strategy)
    if strat_fn is None:
        console.print(f"[red]未知策略 / Unknown strategy: {strategy}[/red]")
        console.print(f"可用策略 / Available: [green]{', '.join(list_names())}[/green]")
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
            console.print(backtest_result_table(valid, f"批量回测 / Batch — {strategy}"))
        failed = [r for r in rows if "error" in r]
        if failed:
            for f in failed:
                console.print(f"[red]✗[/red] {f['symbol']}: {f['error']}")


kill_app = typer.Typer(help="急停 | Kill Switch — emergency stop / release")
recover_app = typer.Typer(help="崩溃恢复 | Crash Recovery — position + order replay")
regime_app = typer.Typer(help="市场状态 | Regime Engine — market state detection")
portfolio_app = typer.Typer(help="组合优化 | Portfolio Optimization — risk budgeting")
alpha_app = typer.Typer(help="Alpha评估 | Alpha Evaluation — signal quality metrics")

app.add_typer(kill_app, name="kill")
app.add_typer(recover_app, name="recover")
app.add_typer(regime_app, name="regime")
app.add_typer(portfolio_app, name="portfolio")
app.add_typer(alpha_app, name="alpha")


# ── Kill Switch Commands ───────────────────────────────────────────

@kill_app.command(name="pull")
def kill_pull(
    reason: str = typer.Argument(..., help="急停原因 | Reason for kill"),
    mode: str = typer.Option("graceful", "--mode", "-m", help="模式: graceful/immediate/hard"),
    by: str = typer.Option("cli", "--by", help="触发者 | Who pulled the switch"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON输出"),
):
    """拉下急停开关 — 停止所有交易 | Pull the kill switch — halt all trading."""
    from .risk_engine import KillSwitch
    ks = KillSwitch()
    ks.pull(reason=reason, mode=mode, by=by)
    data = ks.status()
    if json_out:
        _emit(data)
    else:
        console.print(f"[bold red]🔴 急停已触发 / Kill Switch PULLED[/bold red]")
        console.print(f"  模式: {data['mode']}")
        console.print(f"  原因: {data['reason']}")
        console.print(f"  触发者: {data['killed_by']}")
        console.print(f"  仅允许卖出: {data['allow_sell_only']}")


@kill_app.command(name="release")
def kill_release(
    by: str = typer.Option("cli", "--by", help="释放者 | Who releases"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON输出"),
):
    """释放急停开关 — 恢复交易 | Release the kill switch — resume trading."""
    from .risk_engine import KillSwitch
    ks = KillSwitch()
    ks.release(by=by)
    if json_out:
        _emit({"status": "released", "by": by})
    else:
        console.print("[bold green]🟢 急停已释放 / Kill Switch RELEASED[/bold green]")


@kill_app.command(name="status")
def kill_status(
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON输出"),
):
    """查看急停状态 | Check kill switch status."""
    from .risk_engine import KillSwitch
    ks = KillSwitch()
    data = ks.status()
    if json_out:
        _emit(data)
    else:
        if data["killed"]:
            console.print("[bold red]🔴 急停中 / KILLED[/bold red]")
            console.print(f"  模式: {data['mode']}")
            console.print(f"  原因: {data['reason']}")
            console.print(f"  触发者: {data['killed_by']}")
            console.print(f"  触发时间: {data['killed_at']}")
            console.print(f"  仅允许卖出: {data['allow_sell_only']}")
        else:
            console.print("[bold green]🟢 正常 / KILL SWITCH NOT ACTIVE[/bold green]")


# ── Crash Recovery Commands ───────────────────────────────────────

@recover_app.command(name="run")
def recover_run(
    days_back: int = typer.Option(30, "--days", "-d", help="回看天数 | Days to look back"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON输出"),
):
    """运行崩溃恢复 — 重建持仓 + 重放订单 | Run crash recovery."""
    from .crash_recovery import run_crash_recovery
    from .broker.mock_broker import MockBroker
    from .signal_bus import SignalBus

    broker = MockBroker()
    bus = SignalBus()
    result = run_crash_recovery(broker, bus, days_back=days_back)

    if json_out:
        _emit(result.to_dict())
    else:
        report = result.report
        status_emoji = "✅" if report.status == "ok" else ("⚠️" if report.status == "warning" else "❌")
        console.print(f"[bold]Crash Recovery Report {status_emoji}[/bold]")
        console.print(f"  Broker positions loaded: {report.broker_positions_loaded}")
        console.print(f"  Journal positions rebuilt: {report.journal_positions_rebuilt}")
        console.print(f"  Stale orders requeued: {report.stale_orders_requeued}")
        console.print(f"  Pending orders replayed: {report.pending_orders_replayed}")
        if report.reconciliation_issues:
            for issue in report.reconciliation_issues:
                console.print(f"  [yellow]⚠ {issue}[/yellow]")
        if report.errors:
            for err in report.errors:
                console.print(f"  [red]✗ {err}[/red]")
        if result.account:
            console.print(f"  Account: 现金={result.account.cash:.2f}  资产={result.account.total_assets:.2f}")
        console.print(f"  Recovered: {result.recovered}")


# ── Regime Engine Commands ────────────────────────────────────────

@regime_app.command(name="detect")
def regime_detect(
    index_code: str = typer.Option("000300", "--index", "-i", help="指数代码 | Index code (000300=CSI300, 000905=CSI500)"),
    lookback: int = typer.Option(60, "--lookback", "-l", help="回看天数 | Lookback days"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON输出"),
):
    """检测当前市场状态 | Detect current market regime."""
    from .regime_engine import RegimeEngine, REGIME_STRATEGY_MAP

    engine = RegimeEngine(lookback_days=lookback)
    signal = engine.detect_from_api(index_code=index_code)

    if json_out:
        _emit(signal.to_dict())
    else:
        regime_colors = {
            "BULL": "green",
            "BEAR": "red",
            "OSCILLATION": "yellow",
            "STRUCTURAL": "cyan",
        }
        color = regime_colors.get(signal.regime.value, "white")
        console.print(f"[bold]市场状态 / Market Regime ({index_code})[/bold]")
        console.print(f"  状态: [{color}]{signal.regime.value}[/{color}]  置信度: {signal.confidence:.0%}")
        console.print(f"  风险乘数: {signal.risk_multiplier}  最大仓位: {signal.max_position_pct:.0%}")
        console.print(f"  信号阈值: {signal.signal_threshold}")
        console.print(f"  推荐策略: ", end="")
        for name, score in signal.suggested_strategies:
            console.print(f"[green]{name}({score})[/green] ", end="")
        console.print()
        console.print(f"[dim]详情: {signal.details}[/dim]")


# ── Portfolio Optimization Commands ───────────────────────────────

@portfolio_app.command(name="optimize")
def portfolio_optimize(
    symbols: str = typer.Argument(..., help="候选股票列表(逗号分隔) | Candidate stocks (comma-separated)"),
    total_assets: float = typer.Option(1_000_000, "--assets", "-a", help="总资产 | Total assets"),
    max_single: float = typer.Option(0.20, "--max-single", help="单只上限 | Max single position %"),
    max_sector: float = typer.Option(0.30, "--max-sector", help="板块上限 | Max sector exposure %"),
    max_total: float = typer.Option(0.70, "--max-total", help="总仓上限 | Max total position %"),
    risk_mult: float = typer.Option(1.0, "--risk-mult", "-r", help="风险乘数(来自RegimeEngine) | Risk multiplier"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON输出"),
):
    """运行组合优化 | Run portfolio optimization on candidate stocks."""
    from .portfolio_optimizer import PortfolioOptimizer, StockInfo

    symbols_list = [s.strip() for s in symbols.split(",")]
    candidates = []
    for sym in symbols_list:
        if not sym:
            continue
        # Try to get sector and price info
        sector = ""
        price = 0.0
        try:
            from astock_data.market.tencent_finance import get_realtime_quotes
            quotes = get_realtime_quotes([sym])
            if quotes and sym in quotes:
                q = quotes[sym]
                sector = q.get("sector", "")
                price = float(q.get("price", 0) or 0)
        except Exception:
            pass

        candidates.append(StockInfo(
            symbol=sym,
            sector=sector,
            volatility_pct=0.30,
            momentum=0.0,
            price=price,
        ))

    optimizer = PortfolioOptimizer(
        max_single_pct=max_single,
        max_sector_pct=max_sector,
        max_total_pct=max_total,
    )
    alloc = optimizer.optimize(candidates, total_assets=total_assets,
                               regime_risk_mult=risk_mult)

    if json_out:
        _emit(alloc.to_dict())
    else:
        console.print("[bold]组合优化结果 / Portfolio Allocation[/bold]")
        console.print(f"  现金比例: {alloc.cash_pct:.1%}")
        console.print(f"  预期波动: {alloc.expected_vol_pct:.2f}%")
        console.print(f"  约束满足: {'✅' if alloc.constraints_satisfied else '❌'}")
        console.print(f"  持仓明细:")
        for sym, pct in sorted(alloc.positions.items(), key=lambda x: -x[1]):
            rc = alloc.risk_contribution.get(sym, 0)
            console.print(f"    {sym}: {pct:.1%}  (风险贡献: {rc:.4f})")
        if alloc.sector_exposure:
            console.print(f"  板块暴露:")
            for sec, exp in sorted(alloc.sector_exposure.items(), key=lambda x: -x[1]):
                console.print(f"    {sec}: {exp:.1%}")
        if alloc.warnings:
            for w in alloc.warnings:
                console.print(f"  [yellow]⚠ {w}[/yellow]")


# ── Alpha Evaluation Commands ────────────────────────────────────

@alpha_app.command(name="evaluate")
def alpha_evaluate(
    signal_file: str = typer.Argument(..., help="信号CSV文件 | Signal CSV with columns: date,symbol,signal_value,forward_return_1d"),
    name: str = typer.Option("signal", "--name", "-n", help="信号名称 | Signal name"),
    json_out: bool = typer.Option(False, "--json", "-j", help="JSON输出"),
):
    """评估信号Alpha质量 | Evaluate signal alpha quality from CSV."""
    from .alpha_evaluator import AlphaEvaluator, RankedSignal

    import csv
    signals = []
    with open(signal_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            signals.append(RankedSignal(
                symbol=row.get("symbol", ""),
                date=row.get("date", ""),
                signal_value=float(row.get("signal_value", 0)),
                forward_return_1d=float(row.get("forward_return_1d", 0)),
                forward_return_5d=float(row.get("forward_return_5d", 0)),
                forward_return_10d=float(row.get("forward_return_10d", 0)),
            ))

    evaluator = AlphaEvaluator()
    report = evaluator.evaluate(signals, signal_name=name)

    if json_out:
        _emit(report.to_dict())
    else:
        console.print(f"[bold]Alpha评估报告 / Alpha Report: {name}[/bold]")
        console.print(f"  IC Mean:       {report.ic_mean:.4f}  (std={report.ic_std:.4f}, sharpe={report.ic_sharpe:.2f})")
        console.print(f"  Rank IC Mean:  {report.rank_ic_mean:.4f}  (sharpe={report.rank_ic_sharpe:.2f})")
        console.print(f"  IC>0:          {report.ic_positive_pct:.1%}")
        console.print(f"  IC Decay:      1d={report.ic_decay_1d:.4f}  5d={report.ic_decay_5d:.4f}  10d={report.ic_decay_10d:.4f}")
        console.print(f"  IC Half-life:  {report.ic_half_life_days:.1f} days")
        console.print(f"  Exposure:      {report.exposure_pct:.1%}")
        console.print(f"  Turnover:      {report.turnover_pct:.1%}")
        console.print(f"  Signal Sharpe: {report.sharpe_ratio:.2f}")
        console.print(f"  统计显著:      {'✅' if report.significant else '❌'}")
        if report.warnings:
            for w in report.warnings:
                console.print(f"  [yellow]⚠ {w}[/yellow]")


if __name__ == "__main__":
    app()
