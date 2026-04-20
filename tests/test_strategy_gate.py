"""Tests for the LiveStrategy lifecycle-submit gate (Kairos 0.3.2).

The gate is consulted by ``LiveStrategy._submit_guarded`` and
``_submit_bracket_guarded`` before every BUY order, so downstream
hosts (trading-autopilot) can block strategies in non-CHAMPION
lifecycle states from opening real exposure through the adapter
bypass. See ``openspec/changes/strategy-lifecycle-submit-gate/`` in
trading-autopilot for the full rationale.

The gate is a zero-argument callable — the host closes over the
per-strategy identifier at registration time.
"""

from __future__ import annotations

import pytest

from kairos.actors import ActorConfig
from kairos.strategies.live import LiveStrategy
from kairos.types import Order, OrderSide, OrderStatus, OrderType


pytestmark = pytest.mark.asyncio


class _RecordingAdapter:
    """Minimal adapter double — records every ``submit_order`` call."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def submit_order(
        self,
        *,
        symbol: str,
        side,
        order_type,
        quantity: float,
        price: float | None = None,
        time_in_force=None,
        post_only: bool = False,
        client_order_id: str | None = None,
    ) -> Order:
        self.calls.append({
            "symbol": symbol, "side": side, "order_type": order_type,
            "quantity": quantity, "price": price,
        })
        return Order(
            id=f"mock-{len(self.calls)}",
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price,
            stop_price=None,
            status=OrderStatus.SUBMITTED,
        )


class _FakeBracketManager:
    """Holds the adapter + submit_bracket + submit_bracket_two_phase stubs."""

    def __init__(self, adapter: _RecordingAdapter) -> None:
        self._adapter = adapter
        self.bracket_calls: list[dict] = []
        self.two_phase_calls: list[dict] = []

    async def submit_bracket(self, **kwargs):
        self.bracket_calls.append(kwargs)
        return {"entry_order_id": "mock-entry"}

    async def submit_bracket_two_phase(self, **kwargs):
        self.two_phase_calls.append(kwargs)
        return {"entry_order_id": "mock-entry-tp", "state": "pending_fill"}


def _make_strategy(
    gate=None,
) -> tuple[LiveStrategy, _RecordingAdapter, _FakeBracketManager]:
    """Build a LiveStrategy + wire adapter + bracket manager."""
    adapter = _RecordingAdapter()
    bracket = _FakeBracketManager(adapter)
    strat = LiveStrategy(ActorConfig())
    strat.bracket_manager = bracket
    strat._lifecycle_gate = gate
    return strat, adapter, bracket


# ── _submit_guarded ──────────────────────────────────────────────


async def test_gate_none_allows_buy():
    strat, adapter, _ = _make_strategy(gate=None)
    order = await strat._submit_guarded(
        symbol="BTCUSDC", side=OrderSide.BUY,
        order_type=OrderType.LIMIT, quantity=0.001, price=70000,
    )
    assert order is not None
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["side"] == OrderSide.BUY


async def test_gate_true_allows_buy():
    strat, adapter, _ = _make_strategy(gate=lambda: True)
    order = await strat._submit_guarded(
        symbol="BTCUSDC", side=OrderSide.BUY,
        order_type=OrderType.MARKET, quantity=0.001,
    )
    assert order is not None
    assert len(adapter.calls) == 1


async def test_gate_false_blocks_buy():
    strat, adapter, _ = _make_strategy(gate=lambda: False)
    order = await strat._submit_guarded(
        symbol="BTCUSDC", side=OrderSide.BUY,
        order_type=OrderType.MARKET, quantity=0.001,
    )
    assert order is None
    assert adapter.calls == []


async def test_gate_false_still_passes_sell():
    """Liability-reducing submits must always pass."""
    strat, adapter, _ = _make_strategy(gate=lambda: False)
    order = await strat._submit_guarded(
        symbol="BTCUSDC", side=OrderSide.SELL,
        order_type=OrderType.MARKET, quantity=0.001,
    )
    assert order is not None
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["side"] == OrderSide.SELL


async def test_force_bypasses_gate():
    strat, adapter, _ = _make_strategy(gate=lambda: False)
    order = await strat._submit_guarded(
        symbol="BTCUSDC", side=OrderSide.BUY,
        order_type=OrderType.MARKET, quantity=0.001, force=True,
    )
    assert order is not None
    assert len(adapter.calls) == 1


async def test_gate_exception_fails_closed():
    """Any error in the gate callback MUST block the submit."""
    def bad_gate() -> bool:
        raise RuntimeError("gate internal error")

    strat, adapter, _ = _make_strategy(gate=bad_gate)
    order = await strat._submit_guarded(
        symbol="BTCUSDC", side=OrderSide.BUY,
        order_type=OrderType.MARKET, quantity=0.001,
    )
    assert order is None
    assert adapter.calls == []


# ── _submit_bracket_guarded ──────────────────────────────────────


async def test_bracket_gate_false_blocks_buy():
    strat, _, bracket = _make_strategy(gate=lambda: False)
    result = await strat._submit_bracket_guarded(
        symbol="BTCUSDC", side=OrderSide.BUY, quantity=0.001,
        sl_price=68000, tp_price=75000, reference_price=70000,
    )
    assert result is None
    assert bracket.bracket_calls == []


async def test_bracket_gate_true_allows_buy():
    strat, _, bracket = _make_strategy(gate=lambda: True)
    result = await strat._submit_bracket_guarded(
        symbol="BTCUSDC", side=OrderSide.BUY, quantity=0.001,
        sl_price=68000, tp_price=75000, reference_price=70000,
    )
    assert result is not None
    assert len(bracket.bracket_calls) == 1


async def test_bracket_gate_none_allows_buy():
    strat, _, bracket = _make_strategy(gate=None)
    result = await strat._submit_bracket_guarded(
        symbol="BTCUSDC", side=OrderSide.BUY, quantity=0.001,
        sl_price=68000, tp_price=75000, reference_price=70000,
    )
    assert result is not None
    assert len(bracket.bracket_calls) == 1


async def test_bracket_gate_false_passes_sell():
    """Sell brackets are liability-reducing — gate bypassed."""
    strat, _, bracket = _make_strategy(gate=lambda: False)
    result = await strat._submit_bracket_guarded(
        symbol="BTCUSDC", side=OrderSide.SELL, quantity=0.001,
        sl_price=72000, tp_price=68000, reference_price=70000,
    )
    assert result is not None
    assert len(bracket.bracket_calls) == 1


# ── _submit_bracket_two_phase_guarded ────────────────────────────


async def test_bracket_two_phase_gate_false_blocks_buy():
    strat, _, bracket = _make_strategy(gate=lambda: False)
    result = await strat._submit_bracket_two_phase_guarded(
        symbol="BTCUSDC", side=OrderSide.BUY, quantity=0.001,
        sl_price=68000, tp_price=75000, reference_price=70000,
    )
    assert result is None
    assert bracket.two_phase_calls == []
    assert bracket.bracket_calls == []


async def test_bracket_two_phase_gate_true_allows_buy():
    strat, _, bracket = _make_strategy(gate=lambda: True)
    result = await strat._submit_bracket_two_phase_guarded(
        symbol="BTCUSDC", side=OrderSide.BUY, quantity=0.001,
        sl_price=68000, tp_price=75000, reference_price=70000,
    )
    assert result is not None
    assert len(bracket.two_phase_calls) == 1
    assert bracket.bracket_calls == []   # single-phase NOT used


async def test_bracket_two_phase_gate_none_allows_buy():
    strat, _, bracket = _make_strategy(gate=None)
    result = await strat._submit_bracket_two_phase_guarded(
        symbol="BTCUSDC", side=OrderSide.BUY, quantity=0.001,
        sl_price=68000, tp_price=75000, reference_price=70000,
    )
    assert result is not None
    assert len(bracket.two_phase_calls) == 1


async def test_bracket_two_phase_gate_false_passes_sell():
    """Sell two-phase brackets are liability-reducing — gate bypassed."""
    strat, _, bracket = _make_strategy(gate=lambda: False)
    result = await strat._submit_bracket_two_phase_guarded(
        symbol="BTCUSDC", side=OrderSide.SELL, quantity=0.001,
        sl_price=72000, tp_price=68000, reference_price=70000,
    )
    assert result is not None
    assert len(bracket.two_phase_calls) == 1


async def test_bracket_two_phase_no_manager_returns_none():
    """Safety: missing bracket_manager returns None without crashing."""
    strat = LiveStrategy(ActorConfig())
    strat.bracket_manager = None
    strat._lifecycle_gate = None
    result = await strat._submit_bracket_two_phase_guarded(
        symbol="BTCUSDC", side=OrderSide.BUY, quantity=0.001,
        sl_price=68000, tp_price=75000, reference_price=70000,
    )
    assert result is None


async def test_bracket_two_phase_gate_exception_fails_closed():
    """Gate callback raising an exception must block the submit."""
    def bad_gate() -> bool:
        raise RuntimeError("gate internal error")

    strat, _, bracket = _make_strategy(gate=bad_gate)
    result = await strat._submit_bracket_two_phase_guarded(
        symbol="BTCUSDC", side=OrderSide.BUY, quantity=0.001,
        sl_price=68000, tp_price=75000, reference_price=70000,
    )
    assert result is None
    assert bracket.two_phase_calls == []


async def test_bracket_two_phase_force_bypasses_gate():
    strat, _, bracket = _make_strategy(gate=lambda: False)
    result = await strat._submit_bracket_two_phase_guarded(
        symbol="BTCUSDC", side=OrderSide.BUY, quantity=0.001,
        sl_price=68000, tp_price=75000, reference_price=70000,
        force=True,
    )
    assert result is not None
    assert len(bracket.two_phase_calls) == 1
