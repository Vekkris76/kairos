"""Example: Simple EMA Crossover Strategy.

This strategy buys when the fast EMA crosses above the slow EMA
(with RSI confirmation) and sells when it crosses below.

Usage:
    python examples/ema_cross.py
"""

from autopilot import Engine, Strategy


class EMACross(Strategy):
    def setup(self):
        self.add_ema(8, "fast")
        self.add_ema(21, "slow")
        self.add_rsi(14)

    def on_bar(self, bar):
        if not self.indicators_ready:
            return

        if self.fast_ema() > self.slow_ema() and self.rsi() > 50:
            if not self.has_position():
                self.buy(15)  # 15% of balance
        elif self.fast_ema() < self.slow_ema():
            if self.has_position():
                self.sell_all()


if __name__ == "__main__":
    engine = Engine(
        exchange="paper",  # Use "binance" for live trading
        base_currency="USDC",
    )

    # Run on multiple pairs simultaneously!
    engine.add(EMACross, symbol="BTCUSDC", timeframe="1h")
    engine.add(EMACross, symbol="ETHUSDC", timeframe="1h")

    print("Starting EMA Cross strategy on BTC + ETH...")
    engine.run()
