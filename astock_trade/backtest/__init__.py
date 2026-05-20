"""Backtesting engine — replay historical data through signal → risk → execution pipeline."""

from .engine import BacktestEngine, BacktestResult
from .metrics import calculate_metrics
from .strategies import ma_crossover, price_breakout
