"""Test the §7 design hook on ``Fill.explanation``.

In v0.2 the field exists but is None; v0.3 will fill it. This test
locks the contract so the field never accidentally disappears.
"""

from __future__ import annotations

from kairos.types import Fill, OrderSide


def test_fill_explanation_defaults_to_none() -> None:
    fill = Fill(
        order_id="o1",
        trade_id="t1",
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        price=50_000,
        quantity=0.1,
        commission=0.0,
        timestamp=0,
    )
    assert fill.explanation is None
    assert fill.bracket_id is None
    assert fill.strategy_name is None


def test_fill_accepts_explanation_dict() -> None:
    """v0.3 pre-population path — verify the field accepts a dict."""
    explanation = {
        "rsi": 28.5,
        "regime": "ranging",
        "filter": "liquidity_sweep",
        "win_probability": 0.62,
    }
    fill = Fill(
        order_id="o1",
        trade_id="t1",
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        price=50_000,
        quantity=0.1,
        commission=0.0,
        timestamp=0,
        explanation=explanation,
        bracket_id="br-abc123",
        strategy_name="hybrid_scalping",
    )
    assert fill.explanation == explanation
    assert fill.bracket_id == "br-abc123"
    assert fill.strategy_name == "hybrid_scalping"


def test_fill_strategy_name_optional() -> None:
    """Backwards compat: existing v0.1 callers don't set strategy_name."""
    fill = Fill(
        order_id="o1",
        trade_id="t1",
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        price=50_000,
        quantity=0.1,
        commission=0.0,
        timestamp=0,
    )
    # No exception, all optional fields default cleanly
    assert fill.strategy_name is None
