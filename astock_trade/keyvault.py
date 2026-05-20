"""Key vault — encrypted API key storage.

Uses a simple approach: JSON file with base64-encoded keys, stored in
~/.astock_trade/vault/. For production, use Windows DPAPI or a KMS.
"""

import base64
import json
import os
from pathlib import Path

from .config import get_config
from .exceptions import VaultError


def _ensure_vault_dir() -> Path:
    d = get_config().vault_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def _obfuscate(data: str) -> str:
    """Simple obfuscation — NOT cryptography. Upgrade to DPAPI for production."""
    key = b"astock_trade_vault_2026"
    key_len = len(key)
    raw = data.encode("utf-8")
    xored = bytes(b ^ key[i % key_len] for i, b in enumerate(raw))
    return base64.b64encode(xored).decode("ascii")


def _deobfuscate(encoded: str) -> str:
    key = b"astock_trade_vault_2026"
    key_len = len(key)
    raw = base64.b64decode(encoded)
    xored = bytes(b ^ key[i % key_len] for i, b in enumerate(raw))
    return xored.decode("utf-8")


def store_credential(service: str, credentials: dict) -> None:
    """Store encrypted credentials for a service (broker, API, etc.)."""
    d = _ensure_vault_dir()
    p = d / f"{service}.enc"
    payload = json.dumps(credentials, ensure_ascii=False)
    encoded = _obfuscate(payload)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w") as f:
        f.write(encoded)
    os.replace(tmp, p)


def load_credential(service: str) -> dict:
    """Load and decrypt credentials for a service."""
    p = _ensure_vault_dir() / f"{service}.enc"
    if not p.exists():
        raise VaultError(f"No credentials stored for service: {service}")
    with open(p) as f:
        encoded = f.read()
    payload = _deobfuscate(encoded)
    return json.loads(payload)


def delete_credential(service: str) -> bool:
    """Delete stored credentials. Returns True if deleted."""
    p = _ensure_vault_dir() / f"{service}.enc"
    if p.exists():
        p.unlink()
        return True
    return False


def list_services() -> list[str]:
    """List all services with stored credentials."""
    d = _ensure_vault_dir()
    return sorted(p.stem for p in d.glob("*.enc"))
