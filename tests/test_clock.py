"""Tests for kairos.runtime.clock."""

from __future__ import annotations

import pytest

from kairos.runtime.clock import SystemClock, TestClock


# ── SystemClock ──────────────────────────────────────────────────


def test_system_clock_monotonic_advances() -> None:
    c = SystemClock()
    t1 = c.monotonic()
    t2 = c.monotonic()
    assert t2 >= t1  # never goes backwards


def test_system_clock_unix_ns_is_recent() -> None:
    import time

    c = SystemClock()
    now = c.unix_ns()
    real_now = time.time_ns()
    assert abs(now - real_now) < 1_000_000_000  # within 1 second


def test_system_clock_unix_seconds_matches_unix_ns() -> None:
    c = SystemClock()
    s = c.unix_seconds()
    ns = c.unix_ns()
    assert abs(s - ns / 1e9) < 0.01


# ── TestClock ────────────────────────────────────────────────────


def test_test_clock_starts_at_zero_monotonic() -> None:
    c = TestClock()
    assert c.monotonic() == 0.0


def test_test_clock_advance_moves_monotonic() -> None:
    c = TestClock()
    c.advance(1.5)
    assert c.monotonic() == pytest.approx(1.5)
    c.advance(0.25)
    assert c.monotonic() == pytest.approx(1.75)


def test_test_clock_advance_moves_unix() -> None:
    c = TestClock(initial_unix_ns=2_000_000_000_000_000_000)
    c.advance(10.0)
    assert c.unix_ns() == 2_000_000_000_000_000_000 + 10 * 1_000_000_000


def test_test_clock_rejects_negative_advance() -> None:
    c = TestClock()
    with pytest.raises(ValueError, match="must be >= 0"):
        c.advance(-0.1)


def test_test_clock_advance_zero_is_noop() -> None:
    c = TestClock()
    c.advance(0)
    assert c.monotonic() == 0.0


def test_test_clock_set_unix_ns_preserves_monotonic() -> None:
    c = TestClock()
    c.advance(5.0)
    c.set_unix_ns(3_000_000_000_000_000_000)
    assert c.unix_ns() == 3_000_000_000_000_000_000
    # monotonic preserved
    assert c.monotonic() == pytest.approx(5.0)
    # advancing now still adds to monotonic and unix in lockstep
    c.advance(2.0)
    assert c.monotonic() == pytest.approx(7.0)
    assert c.unix_ns() == 3_000_000_000_000_000_000 + 2 * 1_000_000_000
