"""MarketCache — in-memory store for bars, ticks, orders, positions, accounts.

Single-process, single-engine. O(1) lookups for "last bar of (instrument,
timeframe)" and "open positions". Configurable per-stream retention. Provides
deterministic warmup gating so the engine can call ``on_bar_ready`` only
after a strategy's declared indicators have enough bars.

Design notes:
- All getters return *snapshots* (copied lists) — caller can iterate without
  worrying about mutation by the engine on another task. (We chose copy-cost
  over a more complex iteration-protection scheme; trade-off works for our
  scale: <500 bars per stream, <100 open orders, <10 instruments.)
- We do NOT cache historical bars beyond the configured retention. For
  longer history, use the BacktestEngine's data catalog.
- Tests should drive the cache via direct ``ingest_*`` calls; production
  flow has the LiveEngine wire those calls from the adapter's events.
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Iterable

from kairos.types import Bar, Fill, Instrument, Order, OrderStatus, Position

logger = logging.getLogger("kairos.cache")


@dataclass
class Account:
    """Per-venue account snapshot.

    Mirrors what an exchange returns from "fetch balances" — currency-keyed
    free and locked amounts, plus an opaque venue identifier.
    """

    venue: str
    balances_free: dict[str, float] = field(default_factory=dict)
    balances_locked: dict[str, float] = field(default_factory=dict)

    def free(self, currency: str) -> float:
        return self.balances_free.get(currency, 0.0)

    def locked(self, currency: str) -> float:
        return self.balances_locked.get(currency, 0.0)

    def total(self, currency: str) -> float:
        return self.free(currency) + self.locked(currency)


class MarketCache:
    """In-memory cache for the live engine.

    All mutators are sync (no awaits). The engine drives them from its event
    consumers; consumers are single-threaded asyncio tasks so we do not need
    locks. Readers may run concurrently, but since we return copies they're
    safe.
    """

    def __init__(self, *, max_bars_per_stream: int = 500, max_ticks_per_instrument: int = 100) -> None:
        if max_bars_per_stream <= 0:
            raise ValueError(f"max_bars_per_stream must be > 0, got {max_bars_per_stream}")
        if max_ticks_per_instrument <= 0:
            raise ValueError(f"max_ticks_per_instrument must be > 0, got {max_ticks_per_instrument}")

        self._max_bars = max_bars_per_stream
        self._max_ticks = max_ticks_per_instrument

        # Bars keyed by (symbol, timeframe). deque(maxlen=) auto-evicts oldest.
        self._bars: dict[tuple[str, str], deque[Bar]] = {}
        # Last tick keyed by symbol; we also keep a small recent ring per symbol.
        self._ticks: dict[str, deque[float]] = {}
        # Orders keyed by client_order_id (or exchange order id if no client id).
        self._orders: dict[str, Order] = {}
        # Positions keyed by symbol (netting mode — one position per instrument).
        self._positions: dict[str, Position] = {}
        # Accounts keyed by venue id.
        self._accounts: dict[str, Account] = {}
        # Instrument metadata keyed by symbol.
        self._instruments: dict[str, Instrument] = {}

    # ── Bars ───────────────────────────────────────────────────────────

    def ingest_bar(self, bar: Bar, *, timeframe: str | None = None) -> None:
        """Append a bar to the (symbol, timeframe) stream. Auto-evicts oldest."""
        tf = timeframe or bar.timeframe
        key = (bar.symbol, tf)
        if key not in self._bars:
            self._bars[key] = deque(maxlen=self._max_bars)
        self._bars[key].append(bar)

    def bars(self, symbol: str, timeframe: str, *, limit: int | None = None) -> list[Bar]:
        """Return a snapshot of bars for (symbol, timeframe), oldest first."""
        d = self._bars.get((symbol, timeframe))
        if d is None:
            return []
        if limit is None:
            return list(d)
        # Return the LAST `limit` bars (chronological order preserved)
        return list(d)[-limit:]

    def last_bar(self, symbol: str, timeframe: str) -> Bar | None:
        """Most recent bar, or None if the stream is empty."""
        d = self._bars.get((symbol, timeframe))
        if not d:
            return None
        return d[-1]

    def bar_count(self, symbol: str, timeframe: str) -> int:
        d = self._bars.get((symbol, timeframe))
        return len(d) if d else 0

    def is_warmed_up(self, symbol: str, timeframe: str, required_bars: int) -> bool:
        """True iff the stream has at least ``required_bars`` bars buffered.

        Used by the engine to gate ``Strategy.on_bar_ready`` invocations:
        the engine calls ``on_bar`` (pre-warmup) for every bar but only
        calls ``on_bar_ready`` once the strategy's indicators have enough
        history to produce valid values.
        """
        return self.bar_count(symbol, timeframe) >= required_bars

    # ── Ticks ──────────────────────────────────────────────────────────

    def ingest_tick(self, symbol: str, price: float) -> None:
        """Record a tick (last-price update) for ``symbol``."""
        if symbol not in self._ticks:
            self._ticks[symbol] = deque(maxlen=self._max_ticks)
        self._ticks[symbol].append(price)

    def last_tick(self, symbol: str) -> float | None:
        d = self._ticks.get(symbol)
        if not d:
            return None
        return d[-1]

    def last_price(self, symbol: str) -> float | None:
        """Best-effort 'current' price: tick > last bar close > None."""
        tick = self.last_tick(symbol)
        if tick is not None:
            return tick
        # Fall back to whichever timeframe of bar we have
        for (s, _tf), d in self._bars.items():
            if s == symbol and d:
                return d[-1].close
        return None

    # ── Orders ─────────────────────────────────────────────────────────

    def ingest_order(self, order: Order) -> None:
        """Insert or update an order by id."""
        self._orders[order.id] = order

    def order(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)

    def orders(self) -> list[Order]:
        """All known orders (any status). Snapshot."""
        return list(self._orders.values())

    def orders_open(self, symbol: str | None = None) -> list[Order]:
        """Orders in PENDING / SUBMITTED / ACCEPTED / PARTIALLY_FILLED state."""
        open_states = {
            OrderStatus.PENDING,
            OrderStatus.SUBMITTED,
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
        }
        out = [o for o in self._orders.values() if o.status in open_states]
        if symbol is not None:
            out = [o for o in out if o.symbol == symbol]
        return out

    # ── Positions ──────────────────────────────────────────────────────

    def ingest_fill(self, fill: Fill) -> None:
        """Update the netted position for the fill's symbol.

        Implements simple netting: BUY adds to qty (volume-weighted average
        on existing long), SELL reduces. Realized PnL is tracked at the
        position level. Spot only — for futures we'd need short-side logic.
        """
        pos = self._positions.setdefault(fill.symbol, Position(symbol=fill.symbol))

        from kairos.types import OrderSide

        if fill.side == OrderSide.BUY:
            if pos.quantity <= 0:
                pos.avg_entry = fill.price
                pos.quantity = fill.quantity
            else:
                total_cost = pos.avg_entry * pos.quantity + fill.price * fill.quantity
                pos.quantity += fill.quantity
                pos.avg_entry = total_cost / pos.quantity if pos.quantity > 0 else 0.0
        else:  # SELL
            if pos.quantity > 0:
                realized = (fill.price - pos.avg_entry) * fill.quantity
                pos.realized_pnl += realized - fill.commission
                pos.quantity -= fill.quantity
                if pos.quantity <= 1e-9:
                    pos.quantity = 0.0
                    pos.avg_entry = 0.0

        # Round to control float drift
        pos.quantity = round(pos.quantity, 10)

    def position(self, symbol: str) -> Position | None:
        """Current position for ``symbol``, or None if never traded."""
        return self._positions.get(symbol)

    def positions(self) -> list[Position]:
        return list(self._positions.values())

    def positions_open(self, symbol: str | None = None) -> list[Position]:
        out = [p for p in self._positions.values() if p.is_open]
        if symbol is not None:
            out = [p for p in out if p.symbol == symbol]
        return out

    # ── Accounts ───────────────────────────────────────────────────────

    def ingest_account(self, account: Account) -> None:
        """Insert or update an account snapshot for a venue."""
        self._accounts[account.venue] = account

    def account(self, venue: str) -> Account | None:
        return self._accounts.get(venue)

    def accounts(self) -> list[Account]:
        return list(self._accounts.values())

    # ── Instruments ────────────────────────────────────────────────────

    def ingest_instruments(self, instruments: Iterable[Instrument]) -> None:
        for inst in instruments:
            self._instruments[inst.symbol] = inst

    def instrument(self, symbol: str) -> Instrument | None:
        return self._instruments.get(symbol)

    # ── Introspection ──────────────────────────────────────────────────

    def stats(self) -> dict[str, int]:
        """Counts for ops dashboards / tests."""
        return {
            "bar_streams": len(self._bars),
            "total_bars": sum(len(d) for d in self._bars.values()),
            "tick_streams": len(self._ticks),
            "orders": len(self._orders),
            "open_orders": len(self.orders_open()),
            "positions": len(self._positions),
            "open_positions": len(self.positions_open()),
            "accounts": len(self._accounts),
            "instruments": len(self._instruments),
        }
