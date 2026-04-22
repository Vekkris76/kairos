"""LiveStrategy — Actor-shaped strategy base for the LiveEngine.

Promoted to Kairos in v0.2.1 from the V3StrategyActor pattern that
emerged in Trading Autopilot's v3 work. This is the base class new
strategies should subclass for production live trading.

A LiveStrategy is conceptually "an Actor that subscribes to bars,
maintains indicators, and may submit orders". It inherits the full
Kairos Actor surface (lifecycle hooks, signals, timers, exception
isolation) and adds:

  - Indicator declaration: ``add_rsi(14)``, ``add_ema(8, "fast")``,
    ``add_atr(14)`` — populated in ``__init__``, updated automatically
    on every bar
  - Cache + state helpers: ``free_balance``, ``has_position``, ``last_close``
  - Order shortcuts: ``buy_bracket_pct(pct, atr_multiplier)`` for the
    common SMC-style entry pattern

The LiveEngine binds two extra attributes at registration:
  - ``self.cache``: the engine's MarketCache (read positions, balances, bars)
  - ``self.bracket_manager``: optional, set by callers who want bracket
    order semantics

Subclassing pattern::

    class MyStrategy(LiveStrategy):
        def __init__(self, config):
            super().__init__(config)
            self.add_ema(8, "fast")
            self.add_ema(21, "slow")
            self.add_rsi(14)
            self.add_atr(14)

        def on_bar_ready(self, bar):
            if self.fast_ema() > self.slow_ema() and self.rsi() > 50:
                import asyncio
                asyncio.create_task(self.buy_bracket_pct(15.0, 2.0))
"""

from __future__ import annotations

import logging
from typing import Any

from kairos.actors import Actor, ActorConfig

# Module-level logger used as a fallback for gated-submit logging
# when ``self.log`` hasn't been bound by the engine register step
# yet (tests that construct a bare strategy).
_submit_logger = logging.getLogger("kairos.live_strategy")


class LiveStrategy(Actor):
    """Strategy base class for the LiveEngine.

    Inherits from ``kairos.Actor`` so it gets event routing, timers,
    signal pub/sub, exception isolation. Adds strategy-specific helpers
    on top.

    Two attributes the engine binds at registration time:
      - ``self.cache`` (MarketCache, set by LiveEngine.add_actor)
      - ``self.bracket_manager`` (optional, set by caller; None → use
        the adapter directly via cache.accounts / submit_order)

    Two attributes the strategy author MUST set before passing the
    instance to ``engine.add_strategy()``:
      - ``self.symbol`` (e.g. ``"BTCUSDC"``)
      - ``self.timeframe`` (e.g. ``"15m"``)
    """

    bracket_manager: Any = None
    symbol: str = ""
    timeframe: str = ""

    def __init__(self, config: ActorConfig) -> None:
        super().__init__(config)
        self._indicators: dict[str, Any] = {}
        self._default_rsi_period: int | None = None
        self._default_atr_period: int | None = None
        # Optional lifecycle gate — set by LiveEngine.add_strategy when
        # the host app wants to block entry submits for non-CHAMPION
        # strategies. Callable: (strategy_name) -> bool, where True
        # means "allow BUY submit". SELL submits always pass.
        # See ``_submit_guarded`` below.
        self._lifecycle_gate: Any = None

    # ── Indicator declaration ─────────────────────────────────────

    def add_rsi(self, period: int = 14) -> None:
        """Declare an RSI indicator. Access via ``self.rsi(period)``."""
        from kairos.indicators.rsi import RSI

        self._indicators[f"rsi_{period}"] = RSI(period)
        if self._default_rsi_period is None:
            self._default_rsi_period = period

    def add_ema(self, period: int, name: str = "") -> None:
        """Declare an EMA indicator. Access via ``self.ema(name)``.

        ``name`` lets you have multiple EMAs (e.g. "fast", "slow").
        Defaults to ``f"ema_{period}"``.
        """
        from kairos.indicators.ema import EMA

        key = name or f"ema_{period}"
        self._indicators[key] = EMA(period)

    def add_atr(self, period: int = 14) -> None:
        """Declare an ATR indicator. Access via ``self.atr(period)``."""
        from kairos.indicators.atr import ATR

        self._indicators[f"atr_{period}"] = ATR(period)
        if self._default_atr_period is None:
            self._default_atr_period = period

    # ── Indicator accessors ──────────────────────────────────────

    def rsi(self, period: int | None = None) -> float:
        p = period or self._default_rsi_period
        ind = self._indicators.get(f"rsi_{p}")
        if ind is None or getattr(ind, "value", None) is None:
            return 0.0
        return float(ind.value)

    def ema(self, name: str) -> float:
        ind = self._indicators.get(name)
        if ind is None or getattr(ind, "value", None) is None:
            return 0.0
        return float(ind.value)

    def fast_ema(self) -> float:
        return self.ema("fast")

    def slow_ema(self) -> float:
        return self.ema("slow")

    def atr(self, period: int | None = None) -> float:
        p = period or self._default_atr_period
        ind = self._indicators.get(f"atr_{p}")
        if ind is None or getattr(ind, "value", None) is None:
            return 0.0
        return float(ind.value)

    # ── Cache + state helpers ────────────────────────────────────

    def free_balance(self, currency: str = "USDC") -> float:
        """Free (unlocked) balance for ``currency`` from the first
        registered account. Returns 0.0 if no account or no cache."""
        if self.cache is None:
            return 0.0
        accounts = self.cache.accounts()
        if not accounts:
            return 0.0
        return accounts[0].free(currency)

    def has_position(self) -> bool:
        """True if there is an open position for this strategy's symbol."""
        if self.cache is None or not self.symbol:
            return False
        pos = self.cache.position(self.symbol)
        return pos is not None and pos.quantity > 0

    def last_close(self) -> float:
        """Most recent bar close for this strategy's (symbol, timeframe)."""
        if self.cache is None or not self.symbol or not self.timeframe:
            return 0.0
        bar = self.cache.last_bar(self.symbol, self.timeframe)
        return bar.close if bar is not None else 0.0

    # ── Engine-driven hooks ──────────────────────────────────────

    def on_bar(self, bar: Any) -> None:
        """Update indicators, then call ``on_bar_ready`` if warmed up.

        Subclasses typically don't override ``on_bar`` directly — they
        override ``on_bar_ready(bar)`` for the trading logic. The warmup
        gate runs first; the strategy never sees a bar when its
        indicators are still cold.
        """
        # Filter to our symbol if the engine routes everyone everything
        if self.symbol and getattr(bar, "symbol", None) != self.symbol:
            return

        for ind in self._indicators.values():
            ind.update(bar)

        if self._all_indicators_warmed():
            self.on_bar_ready(bar)

    def on_bar_ready(self, bar: Any) -> None:
        """Override in subclasses — called when all indicators are warmed up."""

    def _all_indicators_warmed(self) -> bool:
        """All declared indicators have received at least ``period`` bars."""
        return all(
            getattr(ind, "initialized", True)
            for ind in self._indicators.values()
        )

    # ── Order submission shortcuts ───────────────────────────────

    async def _submit_guarded(
        self,
        *,
        symbol: str,
        side: Any,
        order_type: Any,
        quantity: float,
        price: float | None = None,
        time_in_force: Any = None,
        post_only: bool = False,
        reduce_only: bool = False,
        client_order_id: str | None = None,
        force: bool = False,
    ) -> Any:
        """Submit an order through the adapter, gated by lifecycle state.

        This is the ONLY entry-point strategy subclasses should use
        for live submits — it consults ``self._lifecycle_gate`` for
        BUY orders so a SHADOW / RETIRED / CHALLENGER strategy cannot
        accidentally open real exposure via the
        ``bracket_manager._adapter`` bypass.

        Behaviour:
          * ``side == OrderSide.BUY`` + gate set + gate returns False
            → log INFO, return None (no submit).
          * ``side == OrderSide.BUY`` + gate raises → log WARNING,
            return None (fail-closed).
          * ``side == OrderSide.SELL`` or any non-BUY side → bypass
            the gate (liability-reducing; always allowed).
          * ``force=True`` → bypass the gate regardless of side.
          * No gate wired (``_lifecycle_gate is None``) → always
            submit (pre-ASL behaviour).

        Resolves the adapter from ``self.bracket_manager._adapter``
        (same path the legacy direct submits used), falling back to
        ``self.adapter`` if set. Returns the Order object on success.
        """
        from kairos.types import OrderSide

        log = getattr(self, "log", _submit_logger)

        # Gate only BUY-side entries. SELL + cancels are always safe.
        # The gate callback takes no args — the host closes over the
        # strategy identity at registration time (see
        # ``LiveEngine.add_strategy(lifecycle_gate=...)``).
        if (
            not force
            and side == OrderSide.BUY
            and self._lifecycle_gate is not None
        ):
            try:
                allowed = bool(self._lifecycle_gate())
            except Exception as exc:
                log.warning(
                    f"Submit gate raised: {exc} — failing closed, "
                    f"dropping {side} {quantity} {symbol}"
                )
                return None
            if not allowed:
                log.info(
                    f"Submit gated: not CHAMPION — dropping "
                    f"{side} {quantity} {symbol} @ {price}"
                )
                return None

        # Resolve the adapter. Prefer the BracketManager's adapter
        # (what the legacy direct path used) so behaviour matches.
        adapter = None
        if self.bracket_manager is not None:
            adapter = getattr(self.bracket_manager, "_adapter", None)
        if adapter is None:
            adapter = getattr(self, "adapter", None)
        if adapter is None:
            log.error(
                "_submit_guarded: no adapter available"
            )
            return None

        # Forward only the kwargs the adapter actually accepts. Not
        # every adapter supports every field (PaperAdapter ignores
        # post_only, etc.) — build the kwargs dict conditionally so
        # older adapters stay callable.
        kwargs: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "quantity": quantity,
        }
        if price is not None:
            kwargs["price"] = price
        if time_in_force is not None:
            kwargs["time_in_force"] = time_in_force
        if post_only:
            kwargs["post_only"] = True
        if reduce_only:
            kwargs["reduce_only"] = True
        if client_order_id is not None:
            kwargs["client_order_id"] = client_order_id
        return await adapter.submit_order(**kwargs)

    async def _submit_bracket_guarded(
        self,
        *,
        symbol: str,
        side: Any,
        quantity: float,
        sl_price: float,
        tp_price: float,
        reference_price: float,
        force: bool = False,
    ) -> Any:
        """Bracket-order counterpart of ``_submit_guarded``.

        Gates BUY brackets on ``self._lifecycle_gate`` and delegates
        to ``self.bracket_manager.submit_bracket(...)``. SELL brackets
        and ``force=True`` pass through. Returns None when gated out
        or when the bracket manager is not wired.
        """
        from kairos.types import OrderSide

        log = getattr(self, "log", _submit_logger)

        if self.bracket_manager is None:
            log.warning(
                "_submit_bracket_guarded: no bracket_manager wired"
            )
            return None

        if (
            not force
            and side == OrderSide.BUY
            and self._lifecycle_gate is not None
        ):
            try:
                allowed = bool(self._lifecycle_gate())
            except Exception as exc:
                log.warning(
                    f"Bracket gate raised: {exc} — failing closed"
                )
                return None
            if not allowed:
                log.info(
                    f"Bracket gated: not CHAMPION — dropping BUY "
                    f"{quantity} {symbol} @ {reference_price}"
                )
                return None

        return await self.bracket_manager.submit_bracket(
            symbol=symbol,
            side=side,
            quantity=quantity,
            sl_price=sl_price,
            tp_price=tp_price,
            reference_price=reference_price,
        )

    async def _submit_bracket_two_phase_guarded(
        self,
        *,
        symbol: str,
        side: Any,
        quantity: float,
        sl_price: float,
        tp_price: float,
        reference_price: float,
        force: bool = False,
    ) -> Any:
        """Two-phase bracket counterpart of ``_submit_bracket_guarded``.

        Gates BUY brackets on ``self._lifecycle_gate`` and delegates
        to ``self.bracket_manager.submit_bracket_two_phase(...)``, which
        submits the entry now and arms SL+TP on the entry fill using
        the real ``filled_qty`` (see Kairos 0.3.5 CHANGELOG). SELL
        brackets and ``force=True`` pass through. Returns None when
        gated out or when the bracket manager is not wired.

        Use when partial fills are a real risk (LIMIT entries or
        illiquid books). For MARKET entries on liquid pairs the
        single-phase ``_submit_bracket_guarded`` is equivalent and
        simpler.
        """
        from kairos.types import OrderSide

        log = getattr(self, "log", _submit_logger)

        if self.bracket_manager is None:
            log.warning(
                "_submit_bracket_two_phase_guarded: no bracket_manager wired"
            )
            return None

        if (
            not force
            and side == OrderSide.BUY
            and self._lifecycle_gate is not None
        ):
            try:
                allowed = bool(self._lifecycle_gate())
            except Exception as exc:
                log.warning(
                    f"Bracket gate raised: {exc} — failing closed"
                )
                return None
            if not allowed:
                log.info(
                    f"Bracket gated (two-phase): not CHAMPION — dropping BUY "
                    f"{quantity} {symbol} @ {reference_price}"
                )
                return None

        return await self.bracket_manager.submit_bracket_two_phase(
            symbol=symbol,
            side=side,
            quantity=quantity,
            sl_price=sl_price,
            tp_price=tp_price,
            reference_price=reference_price,
        )

    async def buy_bracket_pct(
        self,
        pct_of_balance: float,
        atr_multiplier: float = 2.0,
    ) -> bool:
        """Submit a bracket BUY using ``pct_of_balance%`` of free USDC,
        with SL and TP at ``atr_multiplier × ATR`` from entry.

        Returns True if the bracket was submitted; logs (does not raise)
        on validation failure (no balance, no ATR, sub-min-notional, no
        bracket_manager wired, or lifecycle gate blocks the entry).

        Requires:
          - ``self.bracket_manager`` to be set (by the engine wiring)
          - ATR indicator declared via ``self.add_atr(...)``
          - At least one account in the cache with positive USDC
        """
        from kairos.types import OrderSide

        if self.bracket_manager is None:
            self.log.warning("buy_bracket_pct skipped — no bracket_manager wired")
            return False

        price = self.last_close()
        atr_val = self.atr()
        balance = self.free_balance()

        if price <= 0 or atr_val <= 0 or balance <= 0:
            self.log.info(
                f"buy_bracket_pct skipped — price={price} atr={atr_val} balance={balance}"
            )
            return False

        notional = balance * pct_of_balance / 100
        qty = notional / price
        if qty * price < 10.0:  # Binance Spot min notional
            self.log.info(
                f"buy_bracket_pct skipped — notional {qty * price:.2f} < 10 USDC"
            )
            return False

        try:
            # Route through the guarded bracket helper so the
            # lifecycle gate (when wired) can block non-CHAMPION
            # entries.
            result = await self._submit_bracket_guarded(
                symbol=self.symbol,
                side=OrderSide.BUY,
                quantity=qty,
                sl_price=price - atr_multiplier * atr_val,
                tp_price=price + atr_multiplier * atr_val,
                reference_price=price,
            )
            return result is not None
        except Exception as exc:
            self.log.error(f"buy_bracket_pct failed: {exc}")
            return False

    # ── Signal emission (for shared-engine / multi-tenant setups) ──

    def emit_signal(
        self,
        action: str,
        *,
        pct_of_capital: float = 0.0,
        sl_atr_mult: float | None = None,
        tp_atr_mult: float | None = None,
        price_level: float | None = None,
        order_ref: str | None = None,
        reason: str = "",
        symbol: str | None = None,
    ) -> None:
        """Publish a ``StrategySignal`` on the engine's event bus.

        Fire-and-forget from the caller's perspective: synchronous to
        call, delivery is async via the bus. Mirrors ``publish_signal``
        on ``Actor`` for consistency.

        Use alongside (or instead of) direct ``submit_order`` /
        ``buy_bracket_pct`` calls. Downstream consumers — typically a
        signal dispatcher in multi-tenant setups — subscribe to
        ``"strategy_signal"`` and fan out per-user orders using each
        user's capital, keys, and risk profile.

        Does nothing if the engine's event bus isn't bound yet
        (pre-``on_start``) — logs at debug level. Never raises.

        The ``strategy`` field of the emitted ``StrategySignal`` is set
        from the strategy class name, suffix-stripped (e.g.
        ``DCASignalStrategy`` → ``dcasignal``, lower-cased).

        Parameters mirror the ``StrategySignal`` dataclass — see
        ``kairos.types.StrategySignal`` for field semantics.
        """
        import asyncio
        import time

        from kairos.types import StrategySignal

        if self._event_bus is None:
            # pre-registration call — both log and bus may be absent
            logger = getattr(self, "log", None) or logging.getLogger(
                "kairos.live_strategy",
            )
            logger.debug(
                f"emit_signal({action}) skipped — event_bus not bound yet"
            )
            return

        cls = type(self).__name__
        strategy = cls[:-len("Strategy")] if cls.endswith("Strategy") else cls
        strategy = strategy.lower().replace(" ", "_")

        signal = StrategySignal(
            strategy=strategy,
            symbol=symbol or self.symbol,
            action=action,
            pct_of_capital=float(pct_of_capital),
            sl_atr_mult=sl_atr_mult,
            tp_atr_mult=tp_atr_mult,
            price_level=price_level,
            order_ref=order_ref,
            reason=reason,
            ts_ns=time.time_ns(),
            # Populated so downstream ASL gates can uniquely identify
            # the (strategy, symbol, timeframe) tuple. Pre-v0.4.1 this
            # was empty, which forced lifecycle lookups to a
            # strategy-only fallback that collapsed divergent states
            # across timeframes. If ``self.timeframe`` is unset (some
            # legacy strategies leave it ""), the signal falls back
            # to an empty string — downstream consumers treat that as
            # "no timeframe info" and degrade gracefully.
            timeframe=self.timeframe,
        )

        asyncio.create_task(
            self._event_bus.publish("strategy_signal", signal)
        )
