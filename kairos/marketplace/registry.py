"""Strategy Registry — register, discover, and load strategies.

Usage:
    # Register a strategy
    @registry.register(
        name="ema_cross",
        description="Simple EMA crossover with RSI confirmation",
        author="TradingAutopilot",
        version="1.0.0",
        tags=["trend", "ema", "beginner"],
    )
    class EMACross(Strategy):
        ...

    # List available strategies
    for meta in registry.list():
        print(f"{meta.name} by {meta.author} — {meta.description}")

    # Load and run
    strategy_cls = registry.get("ema_cross")
    engine.add(strategy_cls, symbol="BTCUSDC", timeframe="1h")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from kairos.strategy import Strategy

logger = logging.getLogger("autopilot.marketplace")


@dataclass
class StrategyMeta:
    """Metadata for a marketplace strategy."""

    name: str
    description: str = ""
    author: str = "anonymous"
    version: str = "0.1.0"
    tags: list[str] = field(default_factory=list)
    category: str = "general"  # trend, mean-reversion, scalping, grid, dca
    timeframes: list[str] = field(default_factory=list)
    pairs: list[str] = field(default_factory=list)
    min_capital: float = 0
    risk_level: str = "medium"  # low, medium, high
    backtest_results: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class StrategyRegistry:
    """Central registry for marketplace strategies."""

    def __init__(self) -> None:
        self._strategies: dict[str, tuple[type[Strategy], StrategyMeta]] = {}

    def register(
        self,
        name: str,
        description: str = "",
        author: str = "anonymous",
        version: str = "0.1.0",
        tags: list[str] | None = None,
        category: str = "general",
        timeframes: list[str] | None = None,
        pairs: list[str] | None = None,
        min_capital: float = 0,
        risk_level: str = "medium",
    ):
        """Decorator to register a strategy in the marketplace."""
        meta = StrategyMeta(
            name=name,
            description=description,
            author=author,
            version=version,
            tags=tags or [],
            category=category,
            timeframes=timeframes or [],
            pairs=pairs or [],
            min_capital=min_capital,
            risk_level=risk_level,
        )

        def decorator(cls: type[Strategy]) -> type[Strategy]:
            self._strategies[name] = (cls, meta)
            logger.info(f"Registered strategy: {name} v{version} by {author}")
            return cls

        return decorator

    def get(self, name: str) -> type[Strategy] | None:
        """Get a strategy class by name."""
        entry = self._strategies.get(name)
        return entry[0] if entry else None

    def get_meta(self, name: str) -> StrategyMeta | None:
        """Get strategy metadata by name."""
        entry = self._strategies.get(name)
        return entry[1] if entry else None

    def list(
        self,
        category: str | None = None,
        tag: str | None = None,
        risk_level: str | None = None,
    ) -> list[StrategyMeta]:
        """List all registered strategies with optional filters."""
        results = []
        for _, (_, meta) in self._strategies.items():
            if category and meta.category != category:
                continue
            if tag and tag not in meta.tags:
                continue
            if risk_level and meta.risk_level != risk_level:
                continue
            results.append(meta)
        return results

    def search(self, query: str) -> list[StrategyMeta]:
        """Search strategies by name or description."""
        query = query.lower()
        return [
            meta for _, (_, meta) in self._strategies.items()
            if query in meta.name.lower() or query in meta.description.lower()
            or any(query in t.lower() for t in meta.tags)
        ]

    def export_catalog(self, path: str = "marketplace.json") -> None:
        """Export the full catalog to JSON."""
        catalog = [meta.to_dict() for _, (_, meta) in self._strategies.items()]
        Path(path).write_text(json.dumps(catalog, indent=2))
        logger.info(f"Exported {len(catalog)} strategies to {path}")

    def import_catalog(self, path: str = "marketplace.json") -> list[StrategyMeta]:
        """Import catalog from JSON (metadata only, no code)."""
        data = json.loads(Path(path).read_text())
        return [StrategyMeta(**d) for d in data]

    @property
    def count(self) -> int:
        return len(self._strategies)


# Global registry instance
registry = StrategyRegistry()
