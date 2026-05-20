"""Tests for config module."""

import os
from pathlib import Path

import pytest

from astock_trade.config import TradeConfig, get_config, _config


@pytest.fixture(autouse=True)
def reset_config():
    global _config
    _config = None
    yield
    _config = None


class TestTradeConfig:
    def test_default_values(self):
        cfg = TradeConfig()
        assert cfg.intraday_scan_interval_minutes == 5
        assert cfg.quote_poll_interval_seconds == 60
        assert cfg.price_breakout_pct == 3.0
        assert cfg.max_position_pct == 0.30
        assert cfg.morning_open == "09:30"
        assert cfg.afternoon_close == "15:00"

    def test_data_dir_field(self):
        cfg = TradeConfig(data_dir=Path("/tmp/test_data"))
        assert cfg.data_dir == Path("/tmp/test_data")

    def test_custom_dirs(self):
        cfg = TradeConfig(
            trade_journal_dir=Path("/tmp/journal"),
        )
        assert cfg.trade_journal_dir == Path("/tmp/journal")

    def test_env_override_int(self, monkeypatch):
        monkeypatch.setenv("ATRADE_INTRADAY_SCAN_INTERVAL_MINUTES", "10")
        cfg = TradeConfig()
        assert cfg.intraday_scan_interval_minutes == 10

    def test_env_override_float(self, monkeypatch):
        monkeypatch.setenv("ATRADE_PRICE_BREAKOUT_PCT", "5.0")
        cfg = TradeConfig()
        assert cfg.price_breakout_pct == 5.0

    def test_env_override_path(self, monkeypatch):
        monkeypatch.setenv("ATRADE_DATA_DIR", "/custom/data")
        cfg = TradeConfig()
        assert isinstance(cfg.data_dir, Path)
        assert cfg.data_dir == Path("/custom/data")

    def test_directories_created(self, tmp_path):
        d = tmp_path / "test_data"
        cfg = TradeConfig(
            data_dir=d,
            trade_journal_dir=d / "journal",
        )
        assert d.exists()
        assert (d / "journal").exists()

    def test_vault_dir_not_auto_created(self, tmp_path):
        vault = tmp_path / "custom_vault"
        cfg = TradeConfig(data_dir=tmp_path / "data", vault_dir=vault)
        assert vault.exists() is False


class TestGetConfig:
    def test_singleton(self):
        global _config
        _config = None
        cfg1 = get_config()
        cfg2 = get_config()
        assert cfg1 is cfg2

    def test_respects_global(self, monkeypatch):
        cfg = TradeConfig(data_dir=Path("/custom"))
        monkeypatch.setattr("astock_trade.config._config", cfg)
        assert get_config().data_dir == Path("/custom")
