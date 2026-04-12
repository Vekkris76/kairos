"""Clock primitives — wall-time + monotonic + a deterministic test clock.

The whole runtime takes a `Clock` by dependency injection so that tests
can advance time precisely without `asyncio.sleep` calls. SystemClock is
a thin wrapper over `time.monotonic` and `time.time`. TestClock lets a
test fast-forward by an exact delta and drives scheduled callbacks
deterministically.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


class Clock(ABC):
    """Abstract clock — provides monotonic seconds and unix nanoseconds.

    Subclasses MUST be deterministic with respect to their declared time
    semantics: monotonic must never go backwards; unix_ns may jump if
    the wall clock changes (NTP correction) — callers MUST NOT rely on
    its monotonicity.
    """

    @abstractmethod
    def monotonic(self) -> float:
        """Return monotonic seconds since an arbitrary fixed point."""

    @abstractmethod
    def unix_ns(self) -> int:
        """Return current unix time in nanoseconds (UTC)."""

    def unix_seconds(self) -> float:
        """Convenience: unix time in seconds (float)."""
        return self.unix_ns() / 1_000_000_000


class SystemClock(Clock):
    """Real wall-clock backed by ``time.monotonic`` and ``time.time_ns``."""

    def monotonic(self) -> float:
        return time.monotonic()

    def unix_ns(self) -> int:
        return time.time_ns()


@dataclass
class TestClock(Clock):
    __test__ = False  # silence pytest collection warning (it's not a test class)
    """Deterministic clock for tests.

    The clock starts at ``initial_unix_ns`` (default: 2026-01-01 UTC).
    ``monotonic`` starts at 0 and only moves forward when ``advance``
    is called. ``unix_ns`` tracks ``initial_unix_ns + monotonic_ns``.

    Example:
        clock = TestClock()
        assert clock.monotonic() == 0.0
        clock.advance(1.5)  # +1.5 seconds
        assert clock.monotonic() == 1.5
    """

    initial_unix_ns: int = 1_767_225_600_000_000_000  # 2026-01-01T00:00:00Z
    _monotonic_ns: int = field(default=0, init=False)

    def monotonic(self) -> float:
        return self._monotonic_ns / 1_000_000_000

    def unix_ns(self) -> int:
        return self.initial_unix_ns + self._monotonic_ns

    def advance(self, seconds: float) -> None:
        """Move the clock forward by ``seconds`` (must be non-negative)."""
        if seconds < 0:
            raise ValueError(f"TestClock.advance: seconds must be >= 0, got {seconds}")
        self._monotonic_ns += int(seconds * 1_000_000_000)

    def set_unix_ns(self, ns: int) -> None:
        """Jump the wall-clock backing value without touching monotonic.

        Use sparingly — simulates NTP corrections in tests.
        """
        self.initial_unix_ns = ns - self._monotonic_ns
