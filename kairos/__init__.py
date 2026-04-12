"""Kairos — adaptive crypto trading engine.

Curates the best primitives from the open-source ecosystem (ccxt for connectivity,
pandas-ta for math, hummingbot patterns for reconnect) and adds a single proprietary
layer on top: adaptivity. See https://github.com/Vekkris76/kairos for the full vision.

Renamed from `autopilot-engine` at v0.2.0a0.
"""

__version__ = "0.2.0a0"

from kairos.engine import Engine
from kairos.strategy import Strategy
from kairos.backtest.engine import BacktestEngine
from kairos.data.catalog import DataCatalog

__all__ = ["Engine", "Strategy", "BacktestEngine", "DataCatalog", "__version__"]
