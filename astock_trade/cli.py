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
        print(json.dumps(envelope, indent=2, ensure_ascii=False, default=str))
    else:
        print(data)


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
):
    """Query trade records in date range."""
    from .trade_journal import query_trades
    sd = date.fromisoformat(start_date) if start_date else date.today()
    ed = date.fromisoformat(end_date) if end_date else date.today()
    records = query_trades(sd, ed, symbol)
    _emit(records)


@journal_app.command(name="pnl")
def journal_pnl(
    d: Optional[str] = typer.Option(None, "--date", "-d", help="Date YYYY-MM-DD"),
):
    """Compute daily P&L."""
    from .trade_journal import daily_pnl
    dt = date.fromisoformat(d) if d else date.today()
    _emit(daily_pnl(dt))


@journal_app.command(name="summary")
def journal_summary(
    start_date: str = typer.Option(..., "--start", help="Start date YYYY-MM-DD"),
    end_date: str = typer.Option(..., "--end", help="End date YYYY-MM-DD"),
):
    """Aggregated trade summary over a date range."""
    from .trade_journal import trade_summary
    _emit(trade_summary(date.fromisoformat(start_date), date.fromisoformat(end_date)))


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
):
    """List all watchlists for a user."""
    from .user_store import list_watchlists
    _emit(list_watchlists(user_id))


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
    print(f"astock-trade v{__version__}")


@app.command(name="status")
def status():
    """Show system status — config, directories, vault info."""
    from .keyvault import list_services
    from .user_store import list_watchlists
    from .strategy_store import list_strategies
    cfg = get_config()
    _emit({
        "version": __version__,
        "data_dir": str(cfg.data_dir),
        "vault_services": list_services(),
        "strategies": list_strategies(),
        "watchlists": list_watchlists("default"),
        "trading_hours": {
            "morning": f"{cfg.morning_open}-{cfg.morning_close}",
            "afternoon": f"{cfg.afternoon_open}-{cfg.afternoon_close}",
        },
    })


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
    save: Optional[str] = typer.Option(None, "--save", help="Save result to JSON file"),
    data_file: Optional[str] = typer.Option(None, "--data", help="CSV file with OHLCV data"),
):
    """Run a backtest for a single stock."""
    from .backtest.engine import BacktestEngine
    from .backtest.strategies import (
        ma_crossover, ma_crossover_volume, ma_crossover_trend,
        triple_filter, price_breakout, buy_and_hold,
    )

    strategy_map = {
        "ma_crossover": ma_crossover,
        "ma_crossover_volume": ma_crossover_volume,
        "ma_crossover_trend": ma_crossover_trend,
        "triple_filter": triple_filter,
        "price_breakout": price_breakout,
        "buy_and_hold": buy_and_hold,
    }

    strat_fn = strategy_map.get(strategy)
    if strat_fn is None:
        print(f"Unknown strategy: {strategy}. Available: {', '.join(strategy_map)}")
        raise typer.Exit(1)

    params = {}
    if strategy == "ma_crossover":
        params = {"fast": fast, "slow": slow}
    elif strategy == "ma_crossover_volume":
        params = {"fast": fast, "slow": slow, "vol_factor": 1.2}
    elif strategy == "ma_crossover_trend":
        params = {"fast": fast, "slow": slow, "trend": 60}
    elif strategy == "triple_filter":
        params = {"fast": fast, "slow": slow, "trend": 60, "rsi_period": 14, "rsi_buy_max": 70}
    elif strategy == "price_breakout":
        params = {"lookback": lookback, "threshold_pct": threshold}

    engine = BacktestEngine(initial_cash=cash)

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
        print(f"回测失败: {e}")
        raise typer.Exit(1)

    print(result.report())

    if save:
        result.save(save)
        print(f"\n结果已保存: {save}")


@backtest_app.command(name="compare")
def backtest_compare(
    symbol: str = typer.Argument(..., help="6-digit stock code"),
    start_date: str = typer.Option("2024-01-01", "--start", help="Start date"),
    end_date: str = typer.Option("2024-12-31", "--end", help="End date"),
    cash: float = typer.Option(100_000, "--cash", help="Initial cash"),
    data_file: Optional[str] = typer.Option(None, "--data", help="CSV file with OHLCV data"),
):
    """Compare multiple strategies on the same stock."""
    from .backtest.engine import BacktestEngine
    from .backtest.strategies import (
        ma_crossover, ma_crossover_volume, ma_crossover_trend,
        triple_filter, price_breakout, buy_and_hold,
    )

    strategies = [
        ("MA5/20交叉", ma_crossover, {"fast": 5, "slow": 20}),
        ("MA5/20+量确认", ma_crossover_volume, {"fast": 5, "slow": 20, "vol_factor": 1.2}),
        ("MA5/20+趋势", ma_crossover_trend, {"fast": 5, "slow": 20, "trend": 60}),
        ("三重过滤", triple_filter, {"fast": 5, "slow": 20, "trend": 60, "rsi_buy_max": 70}),
        ("突破20日高点", price_breakout, {"lookback": 20, "threshold_pct": 3.0}),
        ("买入持有(基准)", buy_and_hold, {}),
    ]

    engine = BacktestEngine(initial_cash=cash)

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

    print(f"{'策略':<18} {'总收益':>8} {'年化':>8} {'夏普':>6} {'回撤':>8} {'胜率':>7} {'交易':>5}")
    print("-" * 70)
    for name, r in results:
        m = r.metrics
        print(
            f"{name:<18} {m.total_return_pct:>+7.2f}% {m.annual_return_pct:>+7.2f}% "
            f"{m.sharpe_ratio:>6.2f} {m.max_drawdown_pct:>7.2f}% "
            f"{m.win_rate_pct:>6.1f}% {m.total_trades:>5}"
        )


@backtest_app.command(name="batch")
def backtest_batch(
    symbols: list[str] = typer.Argument(..., help="Stock codes to backtest"),
    strategy: str = typer.Option("ma_crossover", "--strategy", "-s", help="Strategy name"),
    start_date: str = typer.Option("2024-01-01", "--start", help="Start date"),
    end_date: str = typer.Option("2024-12-31", "--end", help="End date"),
    cash: float = typer.Option(100_000, "--cash", help="Initial cash"),
):
    """Run backtest on multiple stocks with the same strategy."""
    from .backtest.engine import BacktestEngine
    from .backtest.strategies import ma_crossover, price_breakout, buy_and_hold

    strategy_map = {
        "ma_crossover": ma_crossover,
        "price_breakout": price_breakout,
        "buy_and_hold": buy_and_hold,
    }
    strat_fn = strategy_map.get(strategy)
    if strat_fn is None:
        print(f"Unknown strategy: {strategy}")
        raise typer.Exit(1)

    engine = BacktestEngine(initial_cash=cash)

    print(f"{'代码':<8} {'总收益':>8} {'年化':>8} {'夏普':>6} {'回撤':>8} {'胜率':>7} {'交易':>5} {'盈亏比':>6}")
    print("-" * 70)

    for sym in symbols:
        try:
            r = engine.run(
                symbol=sym,
                strategy=strat_fn,
                strategy_params={"fast": 5, "slow": 20} if strategy == "ma_crossover" else {},
                start_date=start_date,
                end_date=end_date,
            )
            m = r.metrics
            print(
                f"{sym:<8} {m.total_return_pct:>+7.2f}% {m.annual_return_pct:>+7.2f}% "
                f"{m.sharpe_ratio:>6.2f} {m.max_drawdown_pct:>7.2f}% "
                f"{m.win_rate_pct:>6.1f}% {m.total_trades:>5} {m.profit_factor:>6.2f}"
            )
        except Exception as e:
            print(f"{sym:<8} 失败: {e}")


if __name__ == "__main__":
    app()
