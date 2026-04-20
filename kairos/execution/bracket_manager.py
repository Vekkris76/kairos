"""BracketManager — atomic bracket orders + OCO semantics.

Manages the lifecycle of bracket orders: ENTRY + STOP-LOSS + TAKE-PROFIT.
Three guarantees:

1. **Atomicity at submission**: if entry succeeds but SL or TP submission
   fails, the entry is immediately closed with a reverse MARKET order. The
   bracket is never left "half-armed".

2. **OCO at fill time**: if TP fills, the SL is cancelled within 2s; if SL
   fills, the TP is cancelled within 2s.

3. **Idempotent cancel**: cancelling a bracket already half-completed (one
   leg filled) is a no-op for the filled leg.

The manager is pure logic — it talks to an adapter (REST endpoints) to
submit/cancel and to a callback to notify of bracket-level events.

Usage:
    bm = BracketManager(adapter=binance, policy=StaticPolicy())
    bracket_id = await bm.submit_bracket(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.001,
        sl_price=49000.0,
        tp_price=52000.0,
        reference_price=50000.0,
    )
    # Later, when the adapter reports a fill:
    await bm.on_order_filled(filled_order_id)  # auto-cancels the OCO sibling
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from kairos.execution.policy import ExecutionContext, ExecutionPolicy, StaticPolicy
from kairos.types import Fill, OrderSide

if TYPE_CHECKING:
    from kairos.exchanges.base import ExchangeAdapter

logger = logging.getLogger("kairos.bracket")


@dataclass
class Bracket:
    """A grouped entry+SL+TP order set."""

    bracket_id: str
    symbol: str
    side: OrderSide  # entry side; SL/TP are the opposite
    quantity: float
    entry_order_id: str | None = None
    sl_order_id: str | None = None
    tp_order_id: str | None = None
    sl_price: float | None = None
    tp_price: float | None = None
    state: Literal[
        "pending", "pending_fill", "armed", "completed", "failed"
    ] = "pending"
    exit_type: Literal["tp", "sl", "manual"] | None = None
    failure_reason: str | None = None
    # Populated when the entry fill is observed via ``on_order_filled``.
    # ``quantity`` above is rewritten to match ``filled_qty`` on partial
    # fills so downstream code (cancel, introspection) reflects reality.
    filled_qty: float | None = None
    filled_price: float | None = None
    # Two-phase arming: SL+TP submitted after entry fill, not before.
    two_phase: bool = False
    # Internal — populated by submit_bracket_two_phase, consumed by _arm_exits.
    _sl_price_pending: float | None = None
    _tp_price_pending: float | None = None


class BracketSubmissionError(RuntimeError):
    """Raised when entry submitted but SL/TP failed and entry was closed."""


class BracketManager:
    """Owns the bracket-order lifecycle.

    Stateful: tracks active brackets and the order_id → bracket_id mapping
    so ``on_order_filled`` can find the OCO sibling fast.
    """

    def __init__(
        self,
        adapter: "ExchangeAdapter",
        policy: ExecutionPolicy | None = None,
    ) -> None:
        self._adapter = adapter
        self._policy: ExecutionPolicy = policy or StaticPolicy()
        self._brackets: dict[str, Bracket] = {}
        # order_id → bracket_id, for fast OCO lookup on fills
        self._order_to_bracket: dict[str, str] = {}

    # ── Submission ─────────────────────────────────────────────────

    async def submit_bracket(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: float,
        sl_price: float,
        tp_price: float,
        reference_price: float,
        bracket_id: str | None = None,
    ) -> Bracket:
        """Submit entry + SL + TP atomically.

        Returns the Bracket object on success. Raises
        ``BracketSubmissionError`` if SL or TP submission fails after
        entry filled (the entry will have been closed with a reverse
        MARKET order in that case).
        """
        bid = bracket_id or f"br-{uuid.uuid4().hex[:12]}"
        bracket = Bracket(
            bracket_id=bid,
            symbol=symbol,
            side=side,
            quantity=quantity,
            sl_price=sl_price,
            tp_price=tp_price,
        )
        self._brackets[bid] = bracket

        # 1. Submit entry (decided by policy — usually MARKET)
        entry_decision = self._policy.decide(
            ExecutionContext(
                symbol=symbol,
                side=side,
                quantity=quantity,
                role="entry",
                reference_price=reference_price,
            )
        )
        try:
            entry_order = await self._adapter.submit_order(
                symbol=symbol,
                side=side,
                order_type=entry_decision.order_type,
                quantity=quantity,
                price=entry_decision.price,
                stop_price=entry_decision.stop_price,
                time_in_force=entry_decision.time_in_force,
                post_only=entry_decision.post_only,
            )
            bracket.entry_order_id = entry_order.id
            self._order_to_bracket[entry_order.id] = bid
            logger.info(f"Bracket {bid}: entry submitted ({entry_order.id})")
        except Exception as exc:
            bracket.state = "failed"
            bracket.failure_reason = f"entry_submit: {exc}"
            logger.error(f"Bracket {bid}: entry submission failed: {exc}")
            raise

        exit_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY

        # 2. Submit SL — if this fails, close entry
        sl_decision = self._policy.decide(
            ExecutionContext(
                symbol=symbol,
                side=exit_side,
                quantity=quantity,
                role="sl",
                reference_price=sl_price,
            )
        )
        try:
            sl_order = await self._adapter.submit_order(
                symbol=symbol,
                side=exit_side,
                order_type=sl_decision.order_type,
                quantity=quantity,
                price=sl_decision.price,
                stop_price=sl_decision.stop_price,
                time_in_force=sl_decision.time_in_force,
                reduce_only=True,
            )
            bracket.sl_order_id = sl_order.id
            self._order_to_bracket[sl_order.id] = bid
            logger.info(f"Bracket {bid}: SL armed ({sl_order.id} @ {sl_price})")
        except Exception as exc:
            await self._abort_after_entry(bracket, reason=f"sl_submit: {exc}")
            raise BracketSubmissionError(
                f"Bracket {bid} SL submission failed; entry was closed. Reason: {exc}"
            ) from exc

        # 3. Submit TP — if this fails, close entry AND cancel SL
        tp_decision = self._policy.decide(
            ExecutionContext(
                symbol=symbol,
                side=exit_side,
                quantity=quantity,
                role="tp",
                reference_price=tp_price,
            )
        )
        try:
            tp_order = await self._adapter.submit_order(
                symbol=symbol,
                side=exit_side,
                order_type=tp_decision.order_type,
                quantity=quantity,
                price=tp_decision.price,
                stop_price=tp_decision.stop_price,
                time_in_force=tp_decision.time_in_force,
                reduce_only=True,
            )
            bracket.tp_order_id = tp_order.id
            self._order_to_bracket[tp_order.id] = bid
            logger.info(f"Bracket {bid}: TP armed ({tp_order.id} @ {tp_price})")
        except Exception as exc:
            # Cancel SL too, then close entry
            await self._safe_cancel(symbol, bracket.sl_order_id)
            await self._abort_after_entry(bracket, reason=f"tp_submit: {exc}")
            raise BracketSubmissionError(
                f"Bracket {bid} TP submission failed; SL cancelled, entry closed. Reason: {exc}"
            ) from exc

        bracket.state = "armed"
        return bracket

    # ── Two-phase submission ───────────────────────────────────────

    async def submit_bracket_two_phase(
        self,
        *,
        symbol: str,
        side: OrderSide,
        quantity: float,
        sl_price: float,
        tp_price: float,
        reference_price: float,
        bracket_id: str | None = None,
    ) -> Bracket:
        """Submit only the entry; arm SL+TP on the entry fill.

        Unlike ``submit_bracket``, this method returns after the entry
        submission only. SL and TP are submitted by ``on_order_filled``
        when the entry fill arrives, using the actual ``filled_qty``
        (not the requested ``quantity``). This eliminates SL/TP
        over-sizing on partial fills.

        Use when partial fills are a real risk (limit entries, illiquid
        markets, paper adapter with fee simulation). For spot MARKET
        orders on liquid pairs, ``submit_bracket`` is equivalent and
        simpler.

        Preconditions: the caller MUST ``await`` ``on_order_filled``
        for the entry fill. The live engine's current ``_route`` does
        not ``await`` actor hooks — wiring this into a v3 strategy
        requires the strategy to delegate via an ``async`` bridge.
        """
        bid = bracket_id or f"br-{uuid.uuid4().hex[:12]}"
        bracket = Bracket(
            bracket_id=bid,
            symbol=symbol,
            side=side,
            quantity=quantity,
            sl_price=sl_price,
            tp_price=tp_price,
            two_phase=True,
            _sl_price_pending=sl_price,
            _tp_price_pending=tp_price,
        )
        self._brackets[bid] = bracket

        # Submit entry only — SL/TP deferred to _arm_exits
        entry_decision = self._policy.decide(
            ExecutionContext(
                symbol=symbol,
                side=side,
                quantity=quantity,
                role="entry",
                reference_price=reference_price,
            )
        )
        try:
            entry_order = await self._adapter.submit_order(
                symbol=symbol,
                side=side,
                order_type=entry_decision.order_type,
                quantity=quantity,
                price=entry_decision.price,
                stop_price=entry_decision.stop_price,
                time_in_force=entry_decision.time_in_force,
                post_only=entry_decision.post_only,
            )
            bracket.entry_order_id = entry_order.id
            self._order_to_bracket[entry_order.id] = bid
            bracket.state = "pending_fill"
            logger.info(
                f"Bracket {bid}: entry submitted two-phase "
                f"({entry_order.id}); SL/TP armed on fill"
            )
        except Exception as exc:
            bracket.state = "failed"
            bracket.failure_reason = f"entry_submit: {exc}"
            logger.error(f"Bracket {bid}: entry submission failed: {exc}")
            raise

        return bracket

    async def _arm_exits(self, bracket: Bracket) -> None:
        """Submit SL + TP using the actual ``filled_qty``.

        Called by ``on_order_filled`` when the entry leg of a two-phase
        bracket fills. On submission failure of either leg, the entry
        is closed with a reverse MARKET and ``BracketSubmissionError``
        is raised.
        """
        assert bracket._sl_price_pending is not None
        assert bracket._tp_price_pending is not None

        bid = bracket.bracket_id
        filled_qty = bracket.quantity  # already updated by on_order_filled
        exit_side = OrderSide.SELL if bracket.side == OrderSide.BUY else OrderSide.BUY

        # Submit SL
        sl_decision = self._policy.decide(
            ExecutionContext(
                symbol=bracket.symbol,
                side=exit_side,
                quantity=filled_qty,
                role="sl",
                reference_price=bracket._sl_price_pending,
            )
        )
        try:
            sl_order = await self._adapter.submit_order(
                symbol=bracket.symbol,
                side=exit_side,
                order_type=sl_decision.order_type,
                quantity=filled_qty,
                price=sl_decision.price,
                stop_price=sl_decision.stop_price,
                time_in_force=sl_decision.time_in_force,
                reduce_only=True,
            )
            bracket.sl_order_id = sl_order.id
            self._order_to_bracket[sl_order.id] = bid
            logger.info(
                f"Bracket {bid}: SL armed two-phase "
                f"({sl_order.id} @ {bracket._sl_price_pending}, qty={filled_qty})"
            )
        except Exception as exc:
            await self._abort_after_entry(bracket, reason=f"two_phase sl_submit: {exc}")
            raise BracketSubmissionError(
                f"Bracket {bid} two-phase SL failed; entry closed. Reason: {exc}"
            ) from exc

        # Submit TP
        tp_decision = self._policy.decide(
            ExecutionContext(
                symbol=bracket.symbol,
                side=exit_side,
                quantity=filled_qty,
                role="tp",
                reference_price=bracket._tp_price_pending,
            )
        )
        try:
            tp_order = await self._adapter.submit_order(
                symbol=bracket.symbol,
                side=exit_side,
                order_type=tp_decision.order_type,
                quantity=filled_qty,
                price=tp_decision.price,
                stop_price=tp_decision.stop_price,
                time_in_force=tp_decision.time_in_force,
                reduce_only=True,
            )
            bracket.tp_order_id = tp_order.id
            self._order_to_bracket[tp_order.id] = bid
            logger.info(
                f"Bracket {bid}: TP armed two-phase "
                f"({tp_order.id} @ {bracket._tp_price_pending}, qty={filled_qty})"
            )
        except Exception as exc:
            await self._safe_cancel(bracket.symbol, bracket.sl_order_id)
            await self._abort_after_entry(bracket, reason=f"two_phase tp_submit: {exc}")
            raise BracketSubmissionError(
                f"Bracket {bid} two-phase TP failed; SL cancelled, entry closed. Reason: {exc}"
            ) from exc

        bracket.state = "armed"
        logger.info(
            f"Bracket {bid} fully armed two-phase (filled_qty={filled_qty})"
        )

    async def _abort_after_entry(self, bracket: Bracket, *, reason: str) -> None:
        """Reverse the entry with a MARKET in the opposite direction.

        Best-effort: if the close fails too, we log and mark the bracket
        as failed. This is the catastrophic path that ProtectionActor
        should also be watching.
        """
        bracket.state = "failed"
        bracket.failure_reason = reason
        exit_side = OrderSide.SELL if bracket.side == OrderSide.BUY else OrderSide.BUY
        try:
            from kairos.types import OrderType as _OT

            await self._adapter.submit_order(
                symbol=bracket.symbol,
                side=exit_side,
                order_type=_OT.MARKET,
                quantity=bracket.quantity,
                reduce_only=True,
            )
            logger.error(
                f"Bracket {bracket.bracket_id}: aborted ({reason}); "
                f"entry closed with reverse MARKET"
            )
        except Exception as exc:
            logger.critical(
                f"Bracket {bracket.bracket_id}: ABORT FAILED to close entry. "
                f"Original cause: {reason}. Close error: {exc}. "
                f"MANUAL INTERVENTION REQUIRED."
            )

    # ── OCO on fill ────────────────────────────────────────────────

    async def on_order_filled(self, fill: Fill | str) -> Bracket | None:
        """Process a fill notification. If the order is an SL/TP leg of a
        bracket, cancel the sibling leg.

        Accepts either a ``Fill`` object (preferred — carries
        ``quantity`` + ``price`` so partial entry fills can be
        reflected back onto the Bracket) or a raw ``order_id`` string
        (legacy path kept for callers that only have the id at hand).

        Returns the affected Bracket (now ``completed``) or None if the
        order is not part of a bracket.
        """
        if isinstance(fill, Fill):
            order_id = fill.order_id
            filled_qty: float | None = fill.quantity
            filled_price: float | None = fill.price
        else:
            order_id = fill
            filled_qty = None
            filled_price = None

        bid = self._order_to_bracket.get(order_id)
        if bid is None:
            return None

        bracket = self._brackets.get(bid)
        if bracket is None:
            logger.warning(f"on_order_filled: bracket {bid} unknown")
            return None

        # Entry filled: nothing to OCO; SL/TP already armed
        if order_id == bracket.entry_order_id:
            bracket.filled_qty = filled_qty
            bracket.filled_price = filled_price
            # NOTE: SL and TP were already submitted with the original
            # quantity. Updating bracket.quantity here so cancel_bracket
            # and future introspection reflect the actual filled size.
            # Re-arming SL/TP with corrected qty is out of scope for
            # this fix — it would require cancelling and re-submitting
            # both legs, which risks a window of unprotected exposure.
            if filled_qty is not None and filled_qty != bracket.quantity:
                logger.info(
                    f"Bracket {bid}: partial fill detected — "
                    f"requested={bracket.quantity}, filled={filled_qty}. "
                    f"bracket.quantity updated; SL/TP remain at original size."
                )
                bracket.quantity = filled_qty
            # Two-phase: arm SL+TP now that we know the real filled_qty
            if bracket.two_phase and bracket.state == "pending_fill":
                await self._arm_exits(bracket)
                return None
            logger.debug(
                f"Bracket {bid}: entry filled "
                f"({filled_qty if filled_qty is not None else 'qty unknown'}), "
                f"SL+TP remain armed"
            )
            return None

        # SL or TP filled — cancel the sibling
        sibling: str | None = None
        exit_type: Literal["tp", "sl"]
        if order_id == bracket.sl_order_id:
            sibling = bracket.tp_order_id
            exit_type = "sl"
        elif order_id == bracket.tp_order_id:
            sibling = bracket.sl_order_id
            exit_type = "tp"
        else:
            logger.warning(
                f"Bracket {bid}: filled order {order_id} is not entry/SL/TP"
            )
            return None

        await self._safe_cancel(bracket.symbol, sibling)
        bracket.state = "completed"
        bracket.exit_type = exit_type
        # Forget mapping for completed bracket
        for oid in (bracket.entry_order_id, bracket.sl_order_id, bracket.tp_order_id):
            if oid is not None:
                self._order_to_bracket.pop(oid, None)
        logger.info(f"Bracket {bid} completed via {exit_type.upper()}")
        return bracket

    # ── Cancellation ───────────────────────────────────────────────

    async def cancel_bracket(self, bracket_id: str) -> bool:
        """Cancel both legs of a bracket. Returns True if any leg was active."""
        bracket = self._brackets.get(bracket_id)
        if bracket is None:
            return False
        cancelled_any = False
        for oid in (bracket.sl_order_id, bracket.tp_order_id):
            if oid is None:
                continue
            ok = await self._safe_cancel(bracket.symbol, oid)
            cancelled_any = cancelled_any or ok
        if cancelled_any:
            bracket.state = "completed"
            bracket.exit_type = "manual"
        return cancelled_any

    async def _safe_cancel(self, symbol: str, order_id: str | None) -> bool:
        """Cancel an order, swallowing 'already filled / not found' errors."""
        if order_id is None:
            return False
        try:
            ok = await self._adapter.cancel_order(symbol=symbol, order_id=order_id)
            return bool(ok)
        except Exception as exc:
            # Common: order already filled at venue moments before our cancel.
            # Not catastrophic — log + continue.
            logger.warning(f"Cancel of order {order_id} returned: {exc}")
            return False

    # ── Introspection ──────────────────────────────────────────────

    def bracket(self, bracket_id: str) -> Bracket | None:
        return self._brackets.get(bracket_id)

    def active_brackets(self) -> list[Bracket]:
        return [b for b in self._brackets.values() if b.state == "armed"]

    def bracket_for_order(self, order_id: str) -> Bracket | None:
        bid = self._order_to_bracket.get(order_id)
        return self._brackets.get(bid) if bid else None
