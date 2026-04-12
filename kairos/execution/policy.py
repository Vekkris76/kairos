"""ExecutionPolicy — pluggable order-type / timing decisions.

This is a §7 design hook for v0.3 differentiator §1 (adaptive execution).

In v0.2: the live runtime ships ``StaticPolicy`` (always MARKET for entries,
LIMIT for SL/TP). Strategies don't see this — the OrderManager applies it
internally before submitting to the adapter.

In v0.3: an ``AdaptivePolicy`` will plug in here. It will observe the per-pair
realized slippage by regime + spread, and learn the optimal order type +
timing per (instrument × regime × spread). The OrderManager swap is a single
constructor argument:

    OrderManager(adapter=binance, policy=AdaptivePolicy(model=trained_model))

No strategy code changes; no engine changes. The hook in v0.2 just needs to
exist with the right shape.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from kairos.types import OrderSide, OrderType, TimeInForce


@dataclass(frozen=True)
class ExecutionContext:
    """Inputs to a policy decision.

    The policy may use any of these fields. ``StaticPolicy`` ignores all of
    them; ``AdaptivePolicy`` (v0.3) will use most.
    """

    symbol: str
    side: OrderSide
    quantity: float
    role: Literal["entry", "sl", "tp"]
    reference_price: float | None = None  # current best price (mid or last)
    spread_bps: float | None = None       # current spread in basis points
    regime: str | None = None             # detected market regime, if any
    urgency: Literal["low", "normal", "high"] = "normal"


@dataclass(frozen=True)
class ExecutionDecision:
    """Output of a policy decision — what kind of order to submit."""

    order_type: OrderType
    price: float | None = None              # for LIMIT/STOP_LIMIT
    stop_price: float | None = None          # for STOP_MARKET/STOP_LIMIT
    time_in_force: TimeInForce = TimeInForce.GTC
    post_only: bool = False
    reduce_only: bool = False
    # For adaptive policies that want to retry after a deadline:
    fallback_after_seconds: float | None = None   # ignored in v0.2
    fallback_order_type: OrderType | None = None   # ignored in v0.2


class ExecutionPolicy(ABC):
    """Decide how to submit an order given context.

    Subclasses override ``decide``. The OrderManager invokes the policy
    once per ``submit_*`` call and uses the returned decision to choose
    REST/WS endpoint, order type, price, etc.
    """

    @abstractmethod
    def decide(self, ctx: ExecutionContext) -> ExecutionDecision:
        """Return the order shape to submit for this context."""


class StaticPolicy(ExecutionPolicy):
    """Trivial baseline: MARKET for entries, LIMIT for SL/TP.

    Default in v0.2. Replace with ``AdaptivePolicy`` in v0.3 to get
    differentiator §1.
    """

    def decide(self, ctx: ExecutionContext) -> ExecutionDecision:
        if ctx.role == "entry":
            return ExecutionDecision(
                order_type=OrderType.MARKET,
                time_in_force=TimeInForce.GTC,
            )
        if ctx.role == "sl":
            # Stop-market for SL: triggers immediately on adverse move
            if ctx.reference_price is None:
                raise ValueError(
                    "StaticPolicy: SL submission requires reference_price (the SL trigger)"
                )
            return ExecutionDecision(
                order_type=OrderType.STOP_MARKET,
                stop_price=ctx.reference_price,
            )
        if ctx.role == "tp":
            # Limit for TP at the target price
            if ctx.reference_price is None:
                raise ValueError(
                    "StaticPolicy: TP submission requires reference_price (the TP target)"
                )
            return ExecutionDecision(
                order_type=OrderType.LIMIT,
                price=ctx.reference_price,
            )
        raise ValueError(f"Unknown role: {ctx.role!r}")
