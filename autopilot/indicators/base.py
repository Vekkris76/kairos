"""Base indicator interface."""

from __future__ import annotations

from autopilot.types import Bar


class Indicator:
    """Base class for all indicators."""

    def __init__(self, period: int) -> None:
        self.period = period
        self._count = 0

    def update(self, bar: Bar) -> None:
        """Update indicator with a new bar."""
        self._count += 1

    @property
    def value(self) -> float:
        return 0.0

    @property
    def initialized(self) -> bool:
        return self._count >= self.period
