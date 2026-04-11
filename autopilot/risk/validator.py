"""Pre-trade risk validation."""

from __future__ import annotations

import logging
import time
from collections import deque

from autopilot.types import Balance, Instrument, OrderSide, TradingState

logger = logging.getLogger("autopilot.risk")


class RiskValidator:
    """Validates orders before submission."""

    def __init__(
        self,
        max_orders_per_minute: int = 30,
        max_drawdown_pct: float = 15.0,
        max_daily_loss_pct: float = 3.0,
    ) -> None:
        self._max_orders_pm = max_orders_per_minute
        self._max_drawdown = max_drawdown_pct
        self._max_daily_loss = max_daily_loss_pct
        self._order_timestamps: deque[float] = deque()
        self._state = TradingState.ACTIVE
        self._peak_equity = 0.0
        self._day_start_equity = 0.0

    @property
    def state(self) -> TradingState:
        return self._state

    def validate_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        price: float,
        instrument: Instrument,
        balances: dict[str, Balance],
    ) -> str | None:
        """Validate an order. Returns None if OK, error string if rejected."""
        # 1. Trading state
        if self._state == TradingState.HALTED:
            return "Trading is HALTED — manual reset required"
        if self._state == TradingState.REDUCING and side == OrderSide.BUY:
            return "Trading is REDUCING — only sell orders allowed"

        # 2. Rate limit
        now = time.time()
        self._order_timestamps = deque(
            t for t in self._order_timestamps if t > now - 60
        )
        if len(self._order_timestamps) >= self._max_orders_pm:
            return f"Rate limit: max {self._max_orders_pm} orders/minute"

        # 3. Quantity checks
        if quantity <= 0:
            return "Quantity must be positive"
        if quantity < instrument.min_qty:
            return f"Qty {quantity} below min {instrument.min_qty}"
        if quantity > instrument.max_qty:
            return f"Qty {quantity} above max {instrument.max_qty}"

        # 4. Notional check
        notional = quantity * price
        if notional < instrument.min_notional:
            return f"Notional {notional:.2f} below min {instrument.min_notional}"

        # 5. Balance check (for buys)
        if side == OrderSide.BUY:
            quote_balance = balances.get(instrument.quote)
            if not quote_balance or quote_balance.free < notional:
                available = quote_balance.free if quote_balance else 0
                return f"Insufficient {instrument.quote}: need {notional:.2f}, have {available:.2f}"

        # Record order timestamp
        self._order_timestamps.append(now)
        return None  # All checks passed

    def update_equity(self, equity: float) -> None:
        """Update equity tracking for drawdown calculation."""
        if equity > self._peak_equity:
            self._peak_equity = equity

        if self._day_start_equity == 0:
            self._day_start_equity = equity

        # Check drawdown
        if self._peak_equity > 0:
            drawdown_pct = (self._peak_equity - equity) / self._peak_equity * 100
            daily_loss_pct = 0.0
            if self._day_start_equity > 0:
                daily_loss_pct = (self._day_start_equity - equity) / self._day_start_equity * 100

            prev_state = self._state

            if drawdown_pct >= self._max_drawdown or daily_loss_pct >= self._max_daily_loss:
                self._state = TradingState.HALTED
            elif drawdown_pct >= self._max_drawdown * 0.7:
                self._state = TradingState.REDUCING
            elif self._state == TradingState.REDUCING and drawdown_pct < self._max_drawdown * 0.5:
                self._state = TradingState.ACTIVE

            if self._state != prev_state:
                logger.warning(
                    f"Risk state: {prev_state.value} → {self._state.value} "
                    f"(drawdown={drawdown_pct:.1f}%, daily={daily_loss_pct:.1f}%)",
                )

    def reset(self) -> None:
        """Manual reset to ACTIVE state."""
        self._state = TradingState.ACTIVE
        self._peak_equity = 0.0
        self._day_start_equity = 0.0
        logger.info("Risk validator reset to ACTIVE")
