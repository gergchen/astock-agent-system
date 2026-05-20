"""CLI entry point — astock command via Typer.

Usage:
    astock market kline 600519 -c 4 -n 10
    astock market quote 600519 000001
    astock workflow valuate 688017
"""

import json
import sys
from datetime import date, datetime, timedelta
from typing import Optional

import typer

from . import __version__
from .config import get_config
from .utils.formatters import output as fmt_output

app = typer.Typer(
    name="astock",
    help="A-Stock Data Toolkit — 6-layer, 15-endpoint A-share market data.",
    add_completion=False,
)

# Subcommand groups
market_app = typer.Typer(help="Market data (mootdx + Tencent Finance)")
signal_app = typer.Typer(help="Signal layer (THS hotspots + Northbound flow)")
research_app = typer.Typer(help="Research reports (Eastmoney + iwencai)")
news_app = typer.Typer(help="News (Eastmoney + 财联社 + International geopolitics)")
fund_app = typer.Typer(help="Fundamental data (mootdx finance/F10 + akshare)")
ann_app = typer.Typer(help="Announcements (巨潮 cninfo + mootdx)")
workflow_app = typer.Typer(help="Research workflows (valuation, batch, thematic)")
config_app = typer.Typer(help="Configuration and cache management")

app.add_typer(market_app, name="market")
app.add_typer(signal_app, name="signal")
app.add_typer(research_app, name="research")
app.add_typer(news_app, name="news")
app.add_typer(fund_app, name="fund")
app.add_typer(ann_app, name="ann")
app.add_typer(workflow_app, name="workflow")
app.add_typer(config_app, name="config")

# Shared options decorator
def common_options(func):
    """Add --output, --verbose to a command."""
    for opt in [
        typer.Option("json", "--output", "-o", help="Output format: json, table, csv"),
        typer.Option(False, "--verbose", "-v", help="Verbose output"),
    ]:
        func = opt(func)
    return func


def _emit(data, fmt: str = "json"):
    """Print formatted output to stdout."""
    if fmt == "json":
        envelope = {
            "_meta": {
                "source": "astock-cli",
                "timestamp": datetime.now().isoformat(),
                "version": __version__,
            },
            "data": data,
        }
        print(json.dumps(envelope, indent=2, ensure_ascii=False, default=str))
    else:
        print(fmt_output(data, fmt))


# ── Market Commands ──────────────────────────────────────────────

@market_app.command(name="kline")
def market_kline(
    code: str = typer.Argument(..., help="6-digit stock code"),
    category: str = typer.Option("day", "-c", help="K-line period: day, week, month, 1m, 5m, 15m, 30m, 60m"),
    offset: int = typer.Option(100, "-n", help="Number of bars"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Fetch K-line (candlestick) data."""
    from .market.mootdx_quote import get_kline
    df = get_kline(code, category=category, offset=offset)
    _emit(df.to_dict(orient="records"), output)


@market_app.command(name="quote")
def market_quote(
    codes: list[str] = typer.Argument(..., help="Stock codes (space-separated)"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Fetch real-time quotes (46 fields) with 5-level order book."""
    from .market.mootdx_quote import get_quotes
    df = get_quotes(codes)
    _emit(df.to_dict(orient="records"), output)


@market_app.command(name="valuation")
def market_valuation(
    codes: list[str] = typer.Argument(..., help="Stock codes"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Fetch PE, PB, market cap, turnover from Tencent Finance."""
    from .market.tencent_finance import get_valuation
    result = get_valuation(codes)
    _emit(result, output)


# ── Signal Commands ──────────────────────────────────────────────

@signal_app.command(name="hotspot")
def signal_hotspot(
    date_str: Optional[str] = typer.Option(None, "--date", "-d", help="Date YYYY-MM-DD (default: today)"),
    sectors: bool = typer.Option(False, "--sectors", "-s", help="Show sector summary instead of stocks"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Fetch today's strong stocks with editorial reason tags."""
    from .signal.ths_hotspot import get_hot_stocks, get_hot_sectors
    if sectors:
        data = get_hot_sectors()
    else:
        df = get_hot_stocks(date_str)
        data = df.to_dict(orient="records")
    _emit(data, output)


@signal_app.command(name="northbound")
def signal_northbound(
    realtime: bool = typer.Option(True, "--realtime/--history", help="Realtime or historical"),
    mutual_type: str = typer.Option("001", "--type", "-t", help="001=沪股通, 003=深股通"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Fetch northbound capital flow (minute or daily)."""
    from .signal.northbound import get_northbound_realtime, get_northbound_history
    if realtime:
        df = get_northbound_realtime()
        data = df.to_dict(orient="records")
    else:
        data = get_northbound_history(mutual_type)
    _emit(data, output)


# ── Research Commands ────────────────────────────────────────────

@research_app.command(name="reports")
def research_reports(
    code: str = typer.Argument(..., help="6-digit stock code"),
    page: int = typer.Option(1, "--page", "-p", help="Pages to fetch"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Fetch Eastmoney research report list."""
    from .research.eastmoney_report import get_reports
    data = get_reports(code, max_pages=page)
    _emit(data, output)


@research_app.command(name="expectations")
def research_expectations(
    code: str = typer.Argument(..., help="6-digit stock code"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Fetch institutional consensus EPS forecasts."""
    from .research.ths_expectation import get_consensus_eps
    data = get_consensus_eps(code)
    _emit(data, output)


@research_app.command(name="search")
def research_search(
    query: str = typer.Argument(..., help="Natural language search query"),
    channel: str = typer.Option("report", "--channel", "-c", help="report, announcement, or news"),
    size: int = typer.Option(20, "--size", "-s", help="Results per query"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Semantic NL search via iwencai (requires API key)."""
    from .research.iwencai import semantic_search
    data = semantic_search(query, channel=channel, size=size)
    _emit(data, output)


# ── News Commands ────────────────────────────────────────────────

@news_app.command(name="stock")
def news_stock(
    code: str = typer.Argument(..., help="6-digit stock code"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Fetch individual stock news from Eastmoney."""
    from .news.eastmoney_news import get_stock_news
    data = get_stock_news(code)
    _emit(data, output)


@news_app.command(name="flash")
def news_flash(
    limit: int = typer.Option(20, "--limit", "-n", help="Max items"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Fetch 财联社 flash (telegram) news — minute-level updates."""
    from .news.cls_news import get_flash_news
    data = get_flash_news()
    _emit(data[:limit], output)


@news_app.command(name="global")
def news_global(
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Fetch global financial news from Eastmoney."""
    from .news.eastmoney_news import get_global_news
    data = get_global_news()
    _emit(data, output)


@news_app.command(name="geopolitics")
def news_geopolitics(
    query: str = typer.Argument(..., help="Search keywords, e.g. 'Middle East Iran'"),
    max_results: int = typer.Option(30, "--limit", "-n", help="Max articles"),
    from_days: int = typer.Option(3, "--days", "-d", help="Lookback days"),
    use_rss: bool = typer.Option(False, "--rss", help="Force RSS fallback (free, no key needed)"),
    preset: Optional[str] = typer.Option(
        None, "--preset", "-p",
        help="Keyword preset: middle-east, us-china, ukraine, energy, defense",
    ),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Search international geopolitical news. Needs NEWSAPI_API_KEY or use --rss."""
    from datetime import date, timedelta
    from .news.global_news import search_geopolitical_news, GEOPOLITICAL_PRESETS

    if preset and preset in GEOPOLITICAL_PRESETS:
        query = GEOPOLITICAL_PRESETS[preset]

    from_date = (date.today() - timedelta(days=from_days)).isoformat()

    data = search_geopolitical_news(
        query=query,
        max_results=max_results,
        from_date=from_date,
        use_rss=use_rss,
    )
    _emit(data, output)


@news_app.command(name="headlines")
def news_headlines(
    max_results: int = typer.Option(30, "--limit", "-n", help="Max headlines"),
    use_rss: bool = typer.Option(False, "--rss", help="Force RSS fallback"),
    category: str = typer.Option("world", "--category", "-c", help="Category: world, business, technology"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Get top world headlines from major international sources."""
    from .news.global_news import get_top_headlines

    data = get_top_headlines(
        category=category,
        max_results=max_results,
        use_rss=use_rss,
    )
    _emit(data, output)


# ── Fundamental Commands ─────────────────────────────────────────

@fund_app.command(name="finance")
def fund_finance(
    code: str = typer.Argument(..., help="6-digit stock code"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Fetch quarterly financial snapshot (37 fields)."""
    from .fundamental.mootdx_finance import get_finance
    data = get_finance(code)
    _emit(data, output)


@fund_app.command(name="f10")
def fund_f10(
    code: str = typer.Argument(..., help="6-digit stock code"),
    category: str = typer.Option("公司概况", "--category", "-c", help="F10 category"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Fetch F10 text company data (9 categories)."""
    from .fundamental.mootdx_f10 import get_f10
    text = get_f10(code, category)
    _emit({"category": category, "content": text}, output)


@fund_app.command(name="basics")
def fund_basics(
    code: str = typer.Argument(..., help="6-digit stock code"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Fetch stock basic info (market cap, shares, industry, listing date)."""
    from .fundamental.stock_basics import get_stock_basics
    data = get_stock_basics(code)
    _emit(data, output)


# ── Announcement Commands ────────────────────────────────────────

@ann_app.command(name="list")
def ann_list(
    code: str = typer.Argument(..., help="6-digit stock code"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Fetch full announcement list from 巨潮 cninfo."""
    from .announcement.cninfo import get_announcements
    data = get_announcements(code)
    _emit(data, output)


@ann_app.command(name="latest")
def ann_latest(
    code: str = typer.Argument(..., help="6-digit stock code"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Fetch latest announcement summary from mootdx F10."""
    from .announcement.mootdx_ann import get_latest_announcements
    text = get_latest_announcements(code)
    _emit({"code": code, "content": text}, output)


# ── Workflow Commands ────────────────────────────────────────────

@workflow_app.command(name="valuate")
def workflow_valuate(
    code: str = typer.Argument(..., help="6-digit stock code"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Complete single-stock valuation (PE/PEG/digestion years)."""
    from .workflow.valuation import full_valuation
    data = full_valuation(code)
    _emit(data, output)


@workflow_app.command(name="compare")
def workflow_compare(
    codes: list[str] = typer.Argument(..., help="Stock codes to compare"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Batch compare multiple stocks on valuation metrics."""
    from .workflow.batch_compare import batch_compare
    data = batch_compare(codes)
    _emit(data, output)


@workflow_app.command(name="thematic")
def workflow_thematic(
    queries: list[str] = typer.Argument(..., help="NL search queries"),
    channel: str = typer.Option("report", "--channel", "-c", help="Search channel"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Multi-keyword thematic research with cross-reference."""
    from .workflow.thematic_research import thematic_research
    data = thematic_research(queries, channel=channel)
    _emit(data, output)


@workflow_app.command(name="newstock")
def workflow_newstock(
    code: str = typer.Argument(..., help="6-digit stock code"),
    output: str = typer.Option("json", "-o", help="Output format"),
):
    """Quick new-stock research (coverage check + valuation)."""
    from .workflow.new_stock_research import new_stock_research
    data = new_stock_research(code)
    _emit(data, output)


# ── Config Commands ──────────────────────────────────────────────

@config_app.command(name="show")
def config_show():
    """Show current configuration."""
    cfg = get_config()
    print(json.dumps({
        "cache_dir": str(cfg.cache_dir),
        "cache_ttls": cfg.cache_ttls,
        "rate_limits": cfg.rate_limits,
        "tdx_servers": cfg.tdx_servers,
        "iwencai_configured": bool(cfg.iwencai_api_key),
        "skill_mode": cfg.skill_mode,
    }, indent=2, ensure_ascii=False))


@config_app.command(name="keys")
def config_keys(
    set_iwencai: Optional[str] = typer.Option(None, "--set-iwencai", help="Set iwencai API key"),
):
    """Manage API keys."""
    if set_iwencai:
        import os
        os.environ["IWENCAI_API_KEY"] = set_iwencai
        print(f"iwencai key set (session only). For permanent, run: export IWENCAI_API_KEY={set_iwencai}")


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", help="Show version"),
):
    if version:
        print(f"astock v{__version__}")
        raise typer.Exit()


if __name__ == "__main__":
    app()
