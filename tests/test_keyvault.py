"""Tests for keyvault module."""

import tempfile
from pathlib import Path

import pytest

from astock_trade.config import TradeConfig, _config
from astock_trade.exceptions import VaultError
from astock_trade.keyvault import (
    store_credential, load_credential, delete_credential, list_services,
)


@pytest.fixture(autouse=True)
def temp_config(monkeypatch):
    global _config
    _config = None
    d = Path(tempfile.mkdtemp())
    vault = d / "vault"
    cfg = TradeConfig(
        data_dir=d,
        trade_journal_dir=d / "journal",
        strategies_dir=d / "strategies",
        watchlists_dir=d / "watchlists",
        alerts_dir=d / "alerts",
        bus_dir=d / "bus",
        vault_dir=vault,
    )
    monkeypatch.setattr("astock_trade.keyvault.get_config", lambda: cfg)
    monkeypatch.setattr("astock_trade.config._config", cfg)
    yield cfg
    import shutil
    shutil.rmtree(d, ignore_errors=True)
    _config = None


class TestStoreAndLoad:
    def test_store_and_load(self):
        store_credential("eastmoney", {"api_key": "test_key_123"})
        creds = load_credential("eastmoney")
        assert creds["api_key"] == "test_key_123"

    def test_store_multiple_services(self):
        store_credential("eastmoney", {"api_key": "key1"})
        store_credential("xt", {"api_key": "key2"})
        assert load_credential("eastmoney")["api_key"] == "key1"
        assert load_credential("xt")["api_key"] == "key2"

    def test_load_nonexistent(self):
        with pytest.raises(VaultError, match="No credentials"):
            load_credential("nonexistent")

    def test_store_overwrite(self):
        store_credential("eastmoney", {"api_key": "old"})
        store_credential("eastmoney", {"api_key": "new"})
        assert load_credential("eastmoney")["api_key"] == "new"

    def test_store_complex_json(self):
        creds = {"api_key": "abc", "api_secret": "xyz", "broker_id": "12345"}
        store_credential("xt", creds)
        loaded = load_credential("xt")
        assert loaded == creds

    def test_obfuscation_not_plaintext(self, temp_config):
        store_credential("eastmoney", {"api_key": "super_secret"})
        p = temp_config.vault_dir / "eastmoney.enc"
        with open(p) as f:
            raw = f.read()
        assert "super_secret" not in raw


class TestDelete:
    def test_delete_existing(self):
        store_credential("eastmoney", {"api_key": "k"})
        assert delete_credential("eastmoney") is True
        with pytest.raises(VaultError):
            load_credential("eastmoney")

    def test_delete_nonexistent(self):
        assert delete_credential("nonexistent") is False

    def test_delete_only_target(self):
        store_credential("eastmoney", {"api_key": "k1"})
        store_credential("xt", {"api_key": "k2"})
        delete_credential("eastmoney")
        assert load_credential("xt")["api_key"] == "k2"


class TestListServices:
    def test_list_empty(self):
        assert list_services() == []

    def test_list_with_data(self):
        store_credential("eastmoney", {"api_key": "k"})
        store_credential("xt", {"api_key": "k"})
        assert set(list_services()) == {"eastmoney", "xt"}
