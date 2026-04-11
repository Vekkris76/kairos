"""Autopilot Engine — Simple, powerful, Python-first crypto trading framework."""

__version__ = "0.1.0"

from autopilot.engine import Engine
from autopilot.strategy import Strategy
from autopilot.backtest.engine import BacktestEngine
from autopilot.data.catalog import DataCatalog

__all__ = ["Engine", "Strategy", "BacktestEngine", "DataCatalog", "__version__"]
