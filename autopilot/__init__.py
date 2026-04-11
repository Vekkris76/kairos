"""Autopilot Engine — Simple, powerful, Python-first crypto trading framework."""

__version__ = "0.1.0"

from autopilot.strategy import Strategy
from autopilot.engine import Engine

__all__ = ["Engine", "Strategy", "__version__"]
