"""Tests for user_store module."""

import json
import tempfile
from pathlib import Path

import pytest

from astock_trade.config import TradeConfig, _config
from astock_trade.user_store import (
    save_watchlist, get_watchlist, list_watchlists, delete_watchlist,
    set_preference, get_preferences,
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
    monkeypatch.setattr("astock_trade.user_store.get_config", lambda: cfg)
    monkeypatch.setattr("astock_trade.config._config", cfg)
    yield cfg
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    _config = None


class TestWatchlist:
    def test_save_and_get(self):
        save_watchlist("u1", "default", ["600519", "000001"])
        wl = get_watchlist("u1", "default")
        assert wl["name"] == "default"
        assert wl["symbols"] == ["600519", "000001"]
        assert wl["user_id"] == "u1"
        assert "updated_at" in wl

    def test_get_nonexistent(self):
        assert get_watchlist("u1", "nonexistent") is None

    def test_list_watchlists(self):
        save_watchlist("u1", "tech", ["600519"])
        save_watchlist("u1", "bank", ["000001", "600036"])
        result = list_watchlists("u1")
        assert len(result) == 2
        counts = {r["name"]: r["symbol_count"] for r in result}
        assert counts == {"tech": 1, "bank": 2}

    def test_list_empty(self):
        assert list_watchlists("u99") == []

    def test_delete(self):
        save_watchlist("u1", "default", ["600519"])
        assert delete_watchlist("u1", "default") is True
        assert delete_watchlist("u1", "default") is False
        assert get_watchlist("u1", "default") is None

    def test_overwrite(self):
        save_watchlist("u1", "default", ["600519"])
        save_watchlist("u1", "default", ["000001", "002415"])
        wl = get_watchlist("u1", "default")
        assert len(wl["symbols"]) == 2

    def test_multi_user_isolation(self):
        save_watchlist("u1", "default", ["600519"])
        save_watchlist("u2", "default", ["000001"])
        assert get_watchlist("u1", "default")["symbols"] == ["600519"]
        assert get_watchlist("u2", "default")["symbols"] == ["000001"]


class TestPreferences:
    def test_set_and_get(self):
        set_preference("u1", "theme", "dark")
        set_preference("u1", "lang", "zh")
        prefs = get_preferences("u1")
        assert prefs["theme"] == "dark"
        assert prefs["lang"] == "zh"
        assert "_updated_at" in prefs

    def test_get_empty(self):
        assert get_preferences("new_user") == {}

    def test_update_existing(self):
        set_preference("u1", "theme", "dark")
        set_preference("u1", "theme", "light")
        assert get_preferences("u1")["theme"] == "light"
