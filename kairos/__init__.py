"""Kairos — adaptive crypto trading engine.

Curates the best primitives from the open-source ecosystem (ccxt for connectivity,
pandas-ta for math, hummingbot patterns for reconnect) and adds a single proprietary
layer on top: adaptivity. See https://github.com/Vekkris76/kairos for the full vision.

Renamed from `autopilot-engine` at v0.2.0a0.
"""

__version__ = "0.2.1"

from kairos.engine import Engine
from kairos.strategy import Strategy
from kairos.backtest.engine import BacktestEngine
from kairos.data.catalog import DataCatalog

# v0.2 live runtime
from kairos.actors import Actor, ActorConfig
from kairos.adapters import BinanceLive, LiveAdapter
from kairos.cache import Account, MarketCache
from kairos.execution import (
    Bracket,
    BracketManager,
    BracketSubmissionError,
    ExecutionContext,
    ExecutionDecision,
    ExecutionPolicy,
    Reconciler,
    ReconciliationReport,
    StaticPolicy,
)
from kairos.runtime import (
    Clock,
    EventBus,
    LiveEngine,
    ParameterProvider,
    Scheduler,
    StaticProvider,
    SystemClock,
    TestClock,
)
from kairos.strategies import LiveStrategy

__all__ = [
    "__version__",
    # v0.1 surface (paper / backtest)
    "Engine",
    "Strategy",
    "BacktestEngine",
    "DataCatalog",
    # v0.2 live runtime — orchestration
    "Actor",
    "ActorConfig",
    "Clock",
    "EventBus",
    "LiveEngine",
    "Scheduler",
    "SystemClock",
    "TestClock",
    # v0.2 live runtime — cache
    "Account",
    "MarketCache",
    # v0.2 live runtime — execution
    "Bracket",
    "BracketManager",
    "BracketSubmissionError",
    "ExecutionContext",
    "ExecutionDecision",
    "ExecutionPolicy",
    "Reconciler",
    "ReconciliationReport",
    "StaticPolicy",
    # v0.2 live runtime — adapters
    "BinanceLive",
    "LiveAdapter",
    # v0.2 design hooks (used by v0.3+ differentiators)
    "ParameterProvider",
    "StaticProvider",
    # v0.2.1 strategy base for LiveEngine
    "LiveStrategy",
]
