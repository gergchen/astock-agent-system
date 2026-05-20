"""User preferences store — watchlists and per-user settings."""

import json
import os
from datetime import datetime
from pathlib import Path

from .config import get_config


def save_watchlist(user_id: str, name: str, symbols: list[str]) -> Path:
    """Save a named watchlist for a user."""
    user_dir = get_config().watchlists_dir / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    p = user_dir / f"{name}.json"
    data = {
        "user_id": user_id,
        "name": name,
        "symbols": symbols,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return p


def get_watchlist(user_id: str, name: str) -> dict | None:
    """Get a named watchlist."""
    p = get_config().watchlists_dir / user_id / f"{name}.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def list_watchlists(user_id: str) -> list[dict]:
    """List all watchlists for a user."""
    user_dir = get_config().watchlists_dir / user_id
    if not user_dir.exists():
        return []
    result = []
    for f in user_dir.glob("*.json"):
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        result.append({"name": data["name"], "symbol_count": len(data["symbols"]),
                       "updated_at": data.get("updated_at")})
    return result


def delete_watchlist(user_id: str, name: str) -> bool:
    """Delete a watchlist. Returns True if deleted."""
    p = get_config().watchlists_dir / user_id / f"{name}.json"
    if p.exists():
        p.unlink()
        return True
    return False


def set_preference(user_id: str, key: str, value) -> None:
    """Set a user preference."""
    p = get_config().data_dir / "preferences" / f"{user_id}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists():
        with open(p, encoding="utf-8") as f:
            prefs = json.load(f)
    else:
        prefs = {}
    prefs[key] = value
    prefs["_updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(prefs, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def get_preferences(user_id: str) -> dict:
    """Get all preferences for a user."""
    p = get_config().data_dir / "preferences" / f"{user_id}.json"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)
