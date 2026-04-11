"""Example: Grid Bot — profit from sideways markets.

Places buy orders below current price at fixed intervals.
When a buy fills, places a sell one level above.
Profits from the spread between levels.
"""

from autopilot import Engine, Strategy


class GridBot(Strategy):
    def setup(self):
        self.add_atr(14)
        self._grid_spacing = 0.025  # 2.5%
        self._levels = 5
        self._initialized = False
        self._grid = {}  # level_index → {"price": float, "bought": bool}

    def on_bar(self, bar):
        if not self.indicators_ready:
            return

        # Initialize grid on first bar
        if not self._initialized:
            center = bar.close
            for i in range(-self._levels, self._levels + 1):
                price = center * (1 + i * self._grid_spacing)
                self._grid[i] = {"price": price, "bought": False}
            self._initialized = True
            print(f"Grid initialized: {len(self._grid)} levels around {center:.2f}")

        # Check each level
        for idx, level in self._grid.items():
            if idx >= 0:
                continue  # Only buy below center

            # Buy if price touches level and not already bought
            if not level["bought"] and bar.low <= level["price"]:
                balance_pct = 100 / self._levels  # Equal allocation
                if self.free_balance() > 5:  # Min $5
                    self.buy_limit(level["price"], pct=balance_pct)
                    level["bought"] = True

            # Sell one level above when bought
            if level["bought"]:
                sell_idx = idx + 1
                if sell_idx in self._grid:
                    sell_price = self._grid[sell_idx]["price"]
                    if bar.high >= sell_price:
                        self.sell_all()  # Simplified: sell all
                        level["bought"] = False


if __name__ == "__main__":
    engine = Engine(exchange="paper", initial_balance=1000)
    engine.add(GridBot, symbol="BTCUSDC", timeframe="15m")
    print("Grid Bot running on BTC (15m bars)...")
    engine.run()
