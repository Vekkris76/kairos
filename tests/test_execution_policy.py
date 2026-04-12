"""Tests for kairos.execution.policy (StaticPolicy + ExecutionContext/Decision)."""

from __future__ import annotations

import pytest

from kairos.execution.policy import (
    ExecutionContext,
    ExecutionDecision,
    StaticPolicy,
)
from kairos.types import OrderSide, OrderType, TimeInForce


def test_static_policy_entry_returns_market() -> None:
    policy = StaticPolicy()
    decision = policy.decide(
        ExecutionContext(
            symbol="BTCUSDC",
            side=OrderSide.BUY,
            quantity=0.1,
            role="entry",
            reference_price=50_000,
        )
    )
    assert decision.order_type == OrderType.MARKET
    assert decision.time_in_force == TimeInForce.GTC


def test_static_policy_sl_returns_stop_market_at_reference_price() -> None:
    policy = StaticPolicy()
    decision = policy.decide(
        ExecutionContext(
            symbol="BTCUSDC",
            side=OrderSide.SELL,
            quantity=0.1,
            role="sl",
            reference_price=49_000,
        )
    )
    assert decision.order_type == OrderType.STOP_MARKET
    assert decision.stop_price == 49_000


def test_static_policy_tp_returns_limit_at_reference_price() -> None:
    policy = StaticPolicy()
    decision = policy.decide(
        ExecutionContext(
            symbol="BTCUSDC",
            side=OrderSide.SELL,
            quantity=0.1,
            role="tp",
            reference_price=52_000,
        )
    )
    assert decision.order_type == OrderType.LIMIT
    assert decision.price == 52_000


def test_static_policy_sl_without_reference_price_raises() -> None:
    policy = StaticPolicy()
    with pytest.raises(ValueError, match="reference_price"):
        policy.decide(
            ExecutionContext(
                symbol="BTCUSDC",
                side=OrderSide.SELL,
                quantity=0.1,
                role="sl",
                reference_price=None,
            )
        )


def test_static_policy_tp_without_reference_price_raises() -> None:
    policy = StaticPolicy()
    with pytest.raises(ValueError, match="reference_price"):
        policy.decide(
            ExecutionContext(
                symbol="BTCUSDC",
                side=OrderSide.SELL,
                quantity=0.1,
                role="tp",
                reference_price=None,
            )
        )


def test_static_policy_unknown_role_raises() -> None:
    policy = StaticPolicy()
    with pytest.raises(ValueError, match="Unknown role"):
        policy.decide(
            ExecutionContext(
                symbol="BTCUSDC",
                side=OrderSide.BUY,
                quantity=0.1,
                role="garbage",  # type: ignore[arg-type]
                reference_price=50_000,
            )
        )


def test_execution_context_is_frozen() -> None:
    ctx = ExecutionContext(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.1,
        role="entry",
    )
    with pytest.raises(Exception):  # FrozenInstanceError
        ctx.symbol = "ETHUSDC"  # type: ignore[misc]


def test_execution_decision_is_frozen() -> None:
    d = ExecutionDecision(order_type=OrderType.MARKET)
    with pytest.raises(Exception):
        d.order_type = OrderType.LIMIT  # type: ignore[misc]
