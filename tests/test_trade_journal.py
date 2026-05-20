"""Tests for trade_journal module."""

import json
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from astock_trade.config import TradeConfig, get_config, _config
from astock_trade.trade_journal import (
    record_trade, query_trades, daily_pnl, trade_summary,
)


@pytest.fixture(autouse=True)
def temp_config(monkeypatch):
    """Use temp dirs for testing."""
    global _config
    _config = None
    d = Path(tempfile.mkdtemp())
    cfg = TradeConfig(
        data_dir=d,
        trade_journal_dir=d / "journal",
        strategies_dir=d / "strategies",
        watchlists_dir=d / "watchlists",
        alerts_dir=d / "alerts",
        bus_dir=d / "bus",
    )
    monkeypatch.setattr("astock_trade.trade_journal.get_config", lambda: cfg)
    monkeypatch.setattr("astock_trade.config._config", cfg)
    yield cfg
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    _config = None


class TestRecordTrade:
    def test_record_buy(self):
        trade = record_trade("600519", "BUY", 1850.0, 100, strategy="ma_cross")
        assert trade["symbol"] == "600519"
        assert trade["direction"] == "BUY"
        assert trade["price"] == 1850.0
        assert trade["volume"] == 100
        assert trade["amount"] == 185000.0
        assert trade["strategy"] == "ma_cross"

    def test_record_sell(self):
        trade = record_trade("000001", "SELL", 12.50, 500)
        assert trade["direction"] == "SELL"
        assert trade["amount"] == 6250.0

    def test_record_multiple(self):
        record_trade("600519", "BUY", 100.0, 100)
        record_trade("600519", "SELL", 110.0, 100)
        records = query_trades(date.today(), date.today())
        assert len(records) == 2

    def test_record_with_notes(self):
        trade = record_trade("000001", "BUY", 10.0, 200, notes="test trade")
        assert trade["notes"] == "test trade"

    def test_record_persisted_to_disk(self, temp_config):
        record_trade("600519", "BUY", 100.0, 100)
        p = temp_config.trade_journal_dir / f"{date.today().isoformat()}.json"
        assert p.exists()
        with open(p) as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["symbol"] == "600519"


class TestQueryTrades:
    def setup_method(self):
        dt1 = datetime(2026, 5, 10, 10, 0)
        dt2 = datetime(2026, 5, 11, 14, 0)
        dt3 = datetime(2026, 5, 12, 11, 0)
        self.d1 = date(2026, 5, 10)
        self.d2 = date(2026, 5, 11)
        self.d3 = date(2026, 5, 12)

        with patch("astock_trade.trade_journal.date") as mock_date:
            mock_date.today.return_value = self.d1
            record_trade("600519", "BUY", 100.0, 100, timestamp=dt1)
            mock_date.today.return_value = self.d2
            record_trade("000001", "SELL", 50.0, 200, timestamp=dt2)
            mock_date.today.return_value = self.d3
            record_trade("600519", "SELL", 110.0, 100, timestamp=dt3)

    def test_query_date_range(self):
        records = query_trades(self.d1, self.d3)
        assert len(records) == 3

    def test_query_single_day(self):
        records = query_trades(self.d1, self.d1)
        assert len(records) == 1
        assert records[0]["symbol"] == "600519"

    def test_query_by_symbol(self):
        records = query_trades(self.d1, self.d3, symbol="600519")
        assert len(records) == 2

    def test_query_empty(self):
        records = query_trades(date(2025, 1, 1), date(2025, 1, 1))
        assert records == []


class TestDailyPnL:
    def test_pnl_simple(self):
        d = date.today()
        record_trade("600519", "BUY", 100.0, 100)
        record_trade("600519", "SELL", 110.0, 100)
        result = daily_pnl(d)
        assert result["total_buy"] == 10000.0
        assert result["total_sell"] == 11000.0
        assert result["net_cash_flow"] == 1000.0
        assert result["trade_count"] == 2

    def test_pnl_empty_day(self):
        result = daily_pnl(date(2024, 1, 1))
        assert result["total_buy"] == 0
        assert result["trade_count"] == 0


class TestTradeSummary:
    def test_summary(self):
        record_trade("600519", "BUY", 100.0, 100)
        record_trade("000001", "BUY", 50.0, 200)
        record_trade("600519", "SELL", 110.0, 50)
        result = trade_summary(date.today(), date.today())
        assert result["total_trades"] == 3
        assert result["buy_count"] == 2
        assert result["sell_count"] == 1
        assert result["total_buy_amount"] == 20000.0
        assert result["total_sell_amount"] == 5500.0
        assert "600519" in result["symbols_traded"]
        assert "000001" in result["symbols_traded"]
