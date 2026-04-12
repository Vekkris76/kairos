"""Backtest Engine — replay historical data through strategies.

Usage:
    bt = BacktestEngine(initial_balance=1000)
    bt.load_bars("BTCUSDC", "1h", bars)
    bt.add(MyStrategy, symbol="BTCUSDC", timeframe="1h")
    results = bt.run()
    print(results)
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from kairos.data.cache import BarCache
from kairos.exchanges.paper import PaperAdapter
from kairos.orders.position import PositionTracker
from kairos.risk.validator import RiskValidator
from kairos.strategy import Strategy
from kairos.types import Bar, OrderSide, OrderType

logger = logging.getLogger("autopilot.backtest")


@dataclass
class BacktestResults:
    """Backtest performance metrics."""

    total_bars: int = 0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    max_drawdown_pct: float = 0.0
    initial_balance: float = 0.0
    final_balance: float = 0.0
    equity_curve: list[float] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades > 0 else 0

    @property
    def return_pct(self) -> float:
        if self.initial_balance <= 0:
            return 0
        return (self.final_balance - self.initial_balance) / self.initial_balance * 100

    @property
    def profit_factor(self) -> float:
        # Calculated from equity curve
        gains = sum(
            self.equity_curve[i] - self.equity_curve[i - 1]
            for i in range(1, len(self.equity_curve))
            if self.equity_curve[i] > self.equity_curve[i - 1]
        )
        losses_val = abs(sum(
            self.equity_curve[i] - self.equity_curve[i - 1]
            for i in range(1, len(self.equity_curve))
            if self.equity_curve[i] < self.equity_curve[i - 1]
        ))
        return gains / losses_val if losses_val > 0 else 0

    def __str__(self) -> str:
        return (
            f"=== Backtest Results ===\n"
            f"Bars:          {self.total_bars}\n"
            f"Trades:        {self.total_trades}\n"
            f"Win Rate:      {self.win_rate:.1%}\n"
            f"Return:        {self.return_pct:+.2f}%\n"
            f"PnL:           {self.total_pnl:+.2f}\n"
            f"Max Drawdown:  {self.max_drawdown_pct:.2f}%\n"
            f"Profit Factor: {self.profit_factor:.2f}\n"
            f"Initial:       {self.initial_balance:.2f}\n"
            f"Final:         {self.final_balance:.2f}\n"
        )


class BacktestEngine:
    """Replays historical bars through strategies using a paper exchange."""

    def __init__(
        self,
        initial_balance: float = 1000.0,
        base_currency: str = "USDC",
        fee_rate: float = 0.001,
    ) -> None:
        self._initial_balance = initial_balance
        self._base_currency = base_currency
        self._fee_rate = fee_rate
        self._bar_data: dict[str, list[Bar]] = {}  # key → bars
        self._strategies: list[dict] = []

    def load_bars(
        self, symbol: str, timeframe: str, bars: list[Bar],
    ) -> None:
        """Load historical bar data for replay."""
        key = f"{symbol}:{timeframe}"
        self._bar_data[key] = sorted(bars, key=lambda b: b.timestamp)
        logger.info(f"Loaded {len(bars)} bars for {key}")

    def add(
        self, strategy_cls: type[Strategy], symbol: str, timeframe: str,
    ) -> None:
        """Register a strategy for backtesting."""
        self._strategies.append({
            "cls": strategy_cls,
            "symbol": symbol,
            "timeframe": timeframe,
        })

    def run(self) -> BacktestResults:
        """Run the backtest and return results."""
        # Setup
        adapter = PaperAdapter(
            initial_balances={self._base_currency: self._initial_balance},
            fee_rate=self._fee_rate,
        )
        cache = BarCache()
        positions = PositionTracker()
        risk = RiskValidator()

        # Create strategy instances
        instances = []
        for entry in self._strategies:
            inst = entry["cls"]()
            inst._engine = _BacktestEngineProxy(
                adapter, cache, positions, risk,
                self._base_currency,
            )
            inst._symbol = entry["symbol"]
            inst._timeframe = entry["timeframe"]
            inst.setup()
            instances.append(inst)

        # Register fill handler
        fills = []

        def on_fill(fill):
            fills.append(fill)
            last_price = cache.last_price(fill.symbol)
            positions.update(fill, last_price)

        adapter.on_fill(on_fill)

        # Subscribe bars (creates instruments)
        import asyncio
        loop = asyncio.new_event_loop()
        for entry in self._strategies:
            loop.run_until_complete(
                adapter.subscribe_bars(entry["symbol"], entry["timeframe"], lambda b: None),
            )

        # Collect all bars sorted by timestamp
        all_bars: list[Bar] = []
        for bars in self._bar_data.values():
            all_bars.extend(bars)
        all_bars.sort(key=lambda b: b.timestamp)

        # Replay
        results = BacktestResults(
            initial_balance=self._initial_balance,
            total_bars=len(all_bars),
        )
        peak = self._initial_balance
        equity = self._initial_balance

        for bar in all_bars:
            cache.add(bar)
            adapter.feed_bar(bar)

            for inst in instances:
                if inst._symbol != bar.symbol or inst._timeframe != bar.timeframe:
                    continue
                inst._update_indicators(bar)
                if inst.indicators_ready:
                    try:
                        inst.on_bar(bar)
                    except Exception as e:
                        logger.error(f"Strategy error: {e}")

            # Track equity
            balances = loop.run_until_complete(adapter.get_balances())
            equity = sum(b.total for b in balances.values())
            # Add position values
            for pos in positions.open_positions:
                price = cache.last_price(pos.symbol)
                equity += pos.quantity * price

            results.equity_curve.append(equity)
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak * 100 if peak > 0 else 0
            if dd > results.max_drawdown_pct:
                results.max_drawdown_pct = dd

        loop.close()

        # Calculate trade stats from fills
        trade_entries: dict[str, float] = {}
        for fill in fills:
            if fill.side == OrderSide.BUY:
                trade_entries[fill.symbol] = fill.price
            elif fill.side == OrderSide.SELL and fill.symbol in trade_entries:
                entry_price = trade_entries.pop(fill.symbol)
                pnl = (fill.price - entry_price) * fill.quantity
                results.total_trades += 1
                results.total_pnl += pnl
                if pnl > 0:
                    results.wins += 1
                else:
                    results.losses += 1

        results.final_balance = equity
        return results


class _BacktestEngineProxy:
    """Minimal engine proxy for strategies during backtest."""

    def __init__(self, adapter, cache, positions, risk, base_currency):
        self._adapter = adapter
        self._cache = cache
        self._positions = positions
        self._risk = risk
        self._base_currency = base_currency
        self._loop = asyncio.new_event_loop()

    def _submit_market_order(self, symbol, side, pct):
        price = self._cache.last_price(symbol)
        if price <= 0:
            return False
        bal = self._loop.run_until_complete(self._adapter.get_balances())
        free = bal.get(self._base_currency)
        if not free or free.free <= 0:
            return False
        qty = (free.free * pct / 100) / price
        inst = self._loop.run_until_complete(self._adapter.get_instrument(symbol))
        qty = int(qty / inst.qty_step) * inst.qty_step
        if qty <= 0:
            return False
        self._loop.run_until_complete(
            self._adapter.submit_order(symbol, side, OrderType.MARKET, qty),
        )
        return True

    def _submit_sell_all(self, symbol):
        pos = self._positions.get(symbol)
        if not pos.is_open:
            return False
        self._loop.run_until_complete(
            self._adapter.submit_order(symbol, OrderSide.SELL, OrderType.MARKET, pos.quantity),
        )
        return True

    def _submit_bracket_order(self, symbol, pct, sl_dist, tp_dist):
        return self._submit_market_order(symbol, OrderSide.BUY, pct)

    def _get_free_balance(self, currency):
        bal = self._loop.run_until_complete(self._adapter.get_balances())
        b = bal.get(currency)
        return b.free if b else 0

    def _has_position(self, symbol):
        return self._positions.get(symbol).is_open

    def _get_position_qty(self, symbol):
        return self._positions.get(symbol).quantity

    def _get_position_pnl(self, symbol):
        return self._positions.get(symbol).unrealized_pnl

    def _submit_limit_order(self, *a, **kw):
        return None

    def _cancel_order(self, *a):
        return False
