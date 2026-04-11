"""Strategy base class — the heart of Autopilot Engine.

Users create strategies by subclassing Strategy and overriding
setup() and on_bar(). Everything else is handled automatically.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from autopilot.types import Bar, OrderSide

if TYPE_CHECKING:
    from autopilot.engine import Engine


class Strategy:
    """Base class for all trading strategies.

    Example:
        class MyBot(Strategy):
            def setup(self):
                self.add_ema(8, "fast")
                self.add_ema(21, "slow")
                self.add_rsi(14)

            def on_bar(self, bar):
                if self.fast_ema() > self.slow_ema() and self.rsi() > 50:
                    self.buy(15)
    """

    def __init__(self) -> None:
        self._engine: Engine | None = None
        self._symbol: str = ""
        self._timeframe: str = ""

        # Indicators — populated by add_*() in setup()
        self._indicators: dict[str, object] = {}
        self._indicator_names: dict[str, str] = {}  # alias → key

    # ── Lifecycle (override these) ────────────────────

    def setup(self) -> None:
        """Declare indicators. Called once before trading starts."""

    def on_bar(self, bar: Bar) -> None:
        """Called on every new bar. Override with your logic."""

    def on_fill(self, fill) -> None:
        """Called when an order is filled. Override if needed."""

    def on_stop(self) -> None:
        """Called when engine stops. Cleanup here."""

    # ── Indicator Declaration ─────────────────────────

    def add_ema(self, period: int, name: str = "") -> None:
        """Add Exponential Moving Average."""
        from autopilot.indicators.ema import EMA
        key = name or f"ema_{period}"
        self._indicators[key] = EMA(period)

    def add_sma(self, period: int, name: str = "") -> None:
        """Add Simple Moving Average."""
        from autopilot.indicators.sma import SMA
        key = name or f"sma_{period}"
        self._indicators[key] = SMA(period)

    def add_rsi(self, period: int = 14) -> None:
        """Add Relative Strength Index (returns 0-100)."""
        from autopilot.indicators.rsi import RSI
        self._indicators[f"rsi_{period}"] = RSI(period)

    def add_atr(self, period: int = 14) -> None:
        """Add Average True Range."""
        from autopilot.indicators.atr import ATR
        self._indicators[f"atr_{period}"] = ATR(period)

    def add_bollinger(self, period: int = 20, std: float = 2.0) -> None:
        """Add Bollinger Bands."""
        from autopilot.indicators.bollinger import BollingerBands
        self._indicators["bollinger"] = BollingerBands(period, std)

    def add_macd(
        self, fast: int = 12, slow: int = 26, signal: int = 9,
    ) -> None:
        """Add MACD."""
        from autopilot.indicators.macd import MACD
        self._indicators["macd"] = MACD(fast, slow, signal)

    # ── Indicator Accessors ───────────────────────────

    def ema(self, name: str) -> float:
        ind = self._indicators.get(name)
        return ind.value if ind else 0.0

    def fast_ema(self) -> float:
        return self.ema("fast")

    def slow_ema(self) -> float:
        return self.ema("slow")

    def rsi(self, period: int = 14) -> float:
        ind = self._indicators.get(f"rsi_{period}")
        return ind.value if ind else 50.0

    def atr(self, period: int = 14) -> float:
        ind = self._indicators.get(f"atr_{period}")
        return ind.value if ind else 0.0

    def bollinger(self) -> dict:
        ind = self._indicators.get("bollinger")
        if ind:
            return {"upper": ind.upper, "middle": ind.middle, "lower": ind.lower}
        return {"upper": 0, "middle": 0, "lower": 0}

    def macd(self) -> dict:
        ind = self._indicators.get("macd")
        if ind:
            return {"macd": ind.macd_value, "signal": ind.signal_value, "histogram": ind.histogram}
        return {"macd": 0, "signal": 0, "histogram": 0}

    # ── Order Methods ─────────────────────────────────

    def buy(self, pct: float = 10.0) -> bool:
        """Market buy using pct% of free balance. Returns True if submitted."""
        if not self._engine:
            return False
        return self._engine._submit_market_order(
            self._symbol, OrderSide.BUY, pct,
        )

    def sell_all(self) -> bool:
        """Sell entire position. Returns True if submitted."""
        if not self._engine:
            return False
        return self._engine._submit_sell_all(self._symbol)

    def buy_limit(self, price: float, pct: float = 10.0) -> str | None:
        """Place limit buy. Returns order_id or None."""
        if not self._engine:
            return None
        return self._engine._submit_limit_order(
            self._symbol, OrderSide.BUY, price, pct,
        )

    def sell_limit(self, price: float, qty: float | None = None) -> str | None:
        """Place limit sell. Returns order_id or None."""
        if not self._engine:
            return None
        return self._engine._submit_limit_order(
            self._symbol, OrderSide.SELL, price, qty=qty,
        )

    def buy_bracket(
        self, pct: float = 10.0, sl_atr: float = 1.5, tp_atr: float = 3.0,
    ) -> bool:
        """Buy with bracket (SL + TP based on ATR). Returns True if submitted."""
        if not self._engine:
            return False
        atr_val = self.atr()
        if atr_val <= 0:
            return False
        return self._engine._submit_bracket_order(
            self._symbol, pct, atr_val * sl_atr, atr_val * tp_atr,
        )

    def cancel(self, order_id: str) -> bool:
        """Cancel an open order."""
        if not self._engine:
            return False
        return self._engine._cancel_order(order_id)

    # ── Portfolio ─────────────────────────────────────

    def free_balance(self, currency: str = "USDC") -> float:
        if not self._engine:
            return 0.0
        return self._engine._get_free_balance(currency)

    def has_position(self) -> bool:
        if not self._engine:
            return False
        return self._engine._has_position(self._symbol)

    def position_qty(self) -> float:
        if not self._engine:
            return 0.0
        return self._engine._get_position_qty(self._symbol)

    def position_pnl(self) -> float:
        if not self._engine:
            return 0.0
        return self._engine._get_position_pnl(self._symbol)

    # ── Internal ──────────────────────────────────────

    def _bind(self, engine: Engine, symbol: str, timeframe: str) -> None:
        """Called by Engine to bind this strategy instance."""
        self._engine = engine
        self._symbol = symbol
        self._timeframe = timeframe

    def _update_indicators(self, bar: Bar) -> None:
        """Update all indicators with new bar data."""
        for ind in self._indicators.values():
            ind.update(bar)

    @property
    def indicators_ready(self) -> bool:
        """Check if all indicators have enough data."""
        return all(
            getattr(ind, "initialized", True)
            for ind in self._indicators.values()
        )
