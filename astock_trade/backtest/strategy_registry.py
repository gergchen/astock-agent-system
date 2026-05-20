"""Strategy registry — auto-discover, register, and look up backtest strategies.

A strategy is a callable: (pd.DataFrame, **params) -> list[dict].
The registry auto-discovers all public functions from .strategies at import time.
Custom strategies can be added via register().
"""

import inspect
from typing import Callable, Optional

import pandas as pd

# Strategy function signature
StrategyFunc = Callable[..., list[dict]]

_registry: dict[str, dict] = {}


def _extract_defaults(fn: StrategyFunc) -> dict:
    """Extract keyword-defaults from a strategy function signature."""
    try:
        sig = inspect.signature(fn)
        return {
            name: p.default
            for name, p in sig.parameters.items()
            if p.default is not inspect.Parameter.empty and name != "df"
        }
    except (ValueError, TypeError):
        return {}


def _description(fn: StrategyFunc) -> str:
    """Extract first-line docstring, or fall back to function name."""
    doc = inspect.getdoc(fn)
    if doc:
        return doc.split("\n")[0].strip()
    return fn.__name__.replace("_", " ")


def register(name: str, fn: StrategyFunc) -> None:
    """Register a strategy function."""
    _registry[name] = {
        "fn": fn,
        "name": name,
        "defaults": _extract_defaults(fn),
        "description": _description(fn),
    }


def get(name: str) -> Optional[StrategyFunc]:
    """Look up a strategy function by name. Returns None if not found."""
    entry = _registry.get(name)
    return entry["fn"] if entry else None


def get_info(name: str) -> Optional[dict]:
    """Get full metadata for a strategy (fn, defaults, description)."""
    return _registry.get(name)


def list_all() -> dict[str, dict]:
    """Return all registered strategies with metadata."""
    return dict(_registry)


def list_names() -> list[str]:
    """Return sorted list of strategy names."""
    return sorted(_registry.keys())


# ── Auto-discover built-in strategies ─────────────────────────────


def _discover_from(module_name: str):
    """Discover strategies from a module."""
    import importlib
    try:
        mod = importlib.import_module(module_name, package=__package__)
    except ImportError:
        return
    for name in dir(mod):
        if name.startswith("_"):
            continue
        obj = getattr(mod, name)
        if callable(obj) and hasattr(obj, "__name__"):
            try:
                sig = inspect.signature(obj)
                params = list(sig.parameters.keys())
                if params and params[0] == "df":
                    register(name, obj)
            except (ValueError, TypeError):
                pass


def _discover_builtins() -> None:
    """Import all public strategy functions from .strategies and .enhanced_strategies."""
    _discover_from(".strategies")
    _discover_from(".enhanced_strategies")


_discover_builtins()
