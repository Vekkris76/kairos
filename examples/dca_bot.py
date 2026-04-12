"""Example: DCA Bot — buy the dip, sell the rip.

Buys when RSI is oversold (<30). Adds more if price drops further.
Sells when RSI is overbought (>70) or take-profit reached.
"""

from kairos import Engine, Strategy


class DCABot(Strategy):
    def setup(self):
        self.add_rsi(14)
        self._layers = 0
        self._max_layers = 3
        self._last_buy_price = 0

    def on_bar(self, bar):
        if not self.indicators_ready:
            return

        rsi = self.rsi()

        # SELL: RSI overbought or +5% profit
        if self.has_position():
            pnl_pct = self.position_pnl() / (self.free_balance() or 1) * 100
            if rsi > 70 or pnl_pct > 5:
                self.sell_all()
                self._layers = 0
                self._last_buy_price = 0
                return

        # BUY: RSI oversold
        if rsi < 30 and self._layers == 0:
            self.buy(10)  # 10% of balance
            self._layers = 1
            self._last_buy_price = bar.close

        # DCA: Price dropped 3%+ from last buy
        elif self.has_position() and self._layers < self._max_layers:
            if bar.close < self._last_buy_price * 0.97:
                self.buy(10)
                self._layers += 1
                self._last_buy_price = bar.close


if __name__ == "__main__":
    engine = Engine(exchange="paper", initial_balance=500)
    engine.add(DCABot, symbol="BTCUSDC", timeframe="4h")
    engine.add(DCABot, symbol="ETHUSDC", timeframe="4h")
    print("DCA Bot running on BTC + ETH (4h bars)...")
    engine.run()
