"""Strategy parameter store — versioned strategy configurations."""

import json
import os
from datetime import datetime
from pathlib import Path

from .config import get_config


def save_strategy(name: str, params: dict) -> Path:
    """Save a strategy. Each save appends a new version entry."""
    p = get_config().strategies_dir / f"{name}.json"
    if p.exists():
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {"name": name, "versions": []}

    version_entry = {
        "version": len(data["versions"]) + 1,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "params": params,
    }
    data["versions"].append(version_entry)

    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
    return p


def load_strategy(name: str, version: int | None = None) -> dict | None:
    """Load a strategy. If version is None, returns the latest."""
    p = get_config().strategies_dir / f"{name}.json"
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    versions = data.get("versions", [])
    if not versions:
        return None
    if version is not None:
        for v in versions:
            if v["version"] == version:
                return v["params"]
        return None
    return versions[-1]["params"]


def list_strategies() -> list[dict]:
    """List all saved strategies with metadata."""
    result = []
    for f in get_config().strategies_dir.glob("*.json"):
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        versions = data.get("versions", [])
        result.append({
            "name": data["name"],
            "version_count": len(versions),
            "latest_saved": versions[-1]["timestamp"] if versions else None,
        })
    return result


def get_strategy_history(name: str) -> list[dict]:
    """Get all versions of a strategy."""
    p = get_config().strategies_dir / f"{name}.json"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("versions", [])
