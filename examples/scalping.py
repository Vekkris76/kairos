"""Example: Scalping Bot — quick entries on momentum with tight SL/TP.

Uses EMA trend + RSI momentum + ATR for bracket sizing.
Enters on confluence, exits with 1:2 risk-reward bracket.
"""

from autopilot import Engine, Strategy


class ScalpingBot(Strategy):
    def setup(self):
        self.add_ema(8, "fast")
        self.add_ema(21, "slow")
        self.add_rsi(14)
        self.add_atr(14)
        self.add_bollinger(20, 2.0)

    def on_bar(self, bar):
        if not self.indicators_ready:
            return

        # Skip if already in position
        if self.has_position():
            return

        ema_bullish = self.fast_ema() > self.slow_ema()
        rsi_ok = self.rsi() > 50
        bb = self.bollinger()
        above_middle = bar.close > bb["middle"]

        # Triple confirmation: EMA + RSI + above BB middle
        if ema_bullish and rsi_ok and above_middle:
            # Enter with bracket: SL at 1.5× ATR, TP at 3× ATR (1:2 R:R)
            self.buy_bracket(
                pct=15,        # 15% of balance
                sl_atr=1.5,    # Stop loss distance
                tp_atr=3.0,    # Take profit distance
            )

    def on_fill(self, fill):
        print(
            f"  {fill.side.value} {fill.quantity:.6f} "
            f"{fill.symbol} @ {fill.price:.2f}"
        )


if __name__ == "__main__":
    engine = Engine(exchange="paper", initial_balance=200)
    engine.add(ScalpingBot, symbol="BTCUSDC", timeframe="15m")
    engine.add(ScalpingBot, symbol="ETHUSDC", timeframe="15m")
    engine.add(ScalpingBot, symbol="SOLUSDC", timeframe="15m")
    print("Scalping Bot running on BTC + ETH + SOL (15m bars)...")
    engine.run()
