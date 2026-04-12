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

from typing import Any

from kairos.actors import Actor, ActorConfig


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

    async def buy_bracket_pct(
        self,
        pct_of_balance: float,
        atr_multiplier: float = 2.0,
    ) -> bool:
        """Submit a bracket BUY using ``pct_of_balance%`` of free USDC,
        with SL and TP at ``atr_multiplier × ATR`` from entry.

        Returns True if the bracket was submitted; logs (does not raise)
        on validation failure (no balance, no ATR, sub-min-notional, no
        bracket_manager wired).

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
            await self.bracket_manager.submit_bracket(
                symbol=self.symbol,
                side=OrderSide.BUY,
                quantity=qty,
                sl_price=price - atr_multiplier * atr_val,
                tp_price=price + atr_multiplier * atr_val,
                reference_price=price,
            )
            return True
        except Exception as exc:
            self.log.error(f"buy_bracket_pct failed: {exc}")
            return False
