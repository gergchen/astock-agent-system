"""Tests for strategy_store module."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from astock_trade.config import TradeConfig, _config
from astock_trade.strategy_store import (
    save_strategy, load_strategy, list_strategies, get_strategy_history,
)


@pytest.fixture(autouse=True)
def temp_config(monkeypatch):
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
    monkeypatch.setattr("astock_trade.strategy_store.get_config", lambda: cfg)
    monkeypatch.setattr("astock_trade.config._config", cfg)
    yield cfg
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    _config = None


class TestSaveAndLoad:
    def test_save_first_version(self):
        params = {"ma_short": 5, "ma_long": 20}
        save_strategy("ma_cross", params)
        loaded = load_strategy("ma_cross")
        assert loaded == params

    def test_save_multiple_versions(self):
        save_strategy("ma_cross", {"ma_short": 5})
        save_strategy("ma_cross", {"ma_short": 10})
        hist = get_strategy_history("ma_cross")
        assert len(hist) == 2
        assert hist[0]["version"] == 1
        assert hist[1]["version"] == 2

    def test_load_latest(self):
        save_strategy("ma_cross", {"v": 1})
        save_strategy("ma_cross", {"v": 2})
        loaded = load_strategy("ma_cross")
        assert loaded == {"v": 2}

    def test_load_specific_version(self):
        save_strategy("ma_cross", {"v": 1})
        save_strategy("ma_cross", {"v": 2})
        loaded = load_strategy("ma_cross", version=1)
        assert loaded == {"v": 1}

    def test_load_nonexistent(self):
        assert load_strategy("nonexistent") is None

    def test_load_invalid_version(self):
        save_strategy("ma_cross", {"v": 1})
        assert load_strategy("ma_cross", version=99) is None


class TestListStrategies:
    def test_list_empty(self):
        assert list_strategies() == []

    def test_list_with_data(self):
        save_strategy("ma_cross", {"v": 1})
        save_strategy("rsi", {"v": 1})
        result = list_strategies()
        assert len(result) == 2
        names = {r["name"] for r in result}
        assert names == {"ma_cross", "rsi"}

    def test_list_metadata(self):
        save_strategy("ma_cross", {"v": 1})
        save_strategy("ma_cross", {"v": 2})
        result = list_strategies()
        assert result[0]["version_count"] == 2
        assert result[0]["latest_saved"] is not None
