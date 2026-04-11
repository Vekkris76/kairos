"""Example: Backtest with real Binance data.

Downloads 90 days of BTCUSDC 1h bars from Binance and runs
an EMA crossover strategy. No API keys needed (public data).

Usage:
    python examples/backtest_live.py
"""

import json
import time
from urllib.request import urlopen

from autopilot import BacktestEngine, Strategy
from autopilot.types import Bar


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
                self.buy(20)
        elif self.fast_ema() < self.slow_ema():
            if self.has_position():
                self.sell_all()


def fetch_bars(symbol: str, interval: str, days: int = 90) -> list[Bar]:
    """Download historical bars from Binance (no auth needed)."""
    print(f"Downloading {days} days of {symbol} {interval} bars...")
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (days * 86400 * 1000)
    bars = []

    while start_ms < end_ms:
        url = (
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={symbol}&interval={interval}"
            f"&startTime={start_ms}&limit=1000"
        )
        with urlopen(url) as resp:
            klines = json.loads(resp.read())
        if not klines:
            break
        for k in klines:
            bars.append(Bar(
                symbol=symbol, timeframe=interval,
                timestamp=k[0],
                open=float(k[1]), high=float(k[2]),
                low=float(k[3]), close=float(k[4]),
                volume=float(k[5]),
            ))
        start_ms = klines[-1][6] + 1
        time.sleep(0.2)

    print(f"  Loaded {len(bars)} bars")
    return bars


if __name__ == "__main__":
    # Download data
    bars = fetch_bars("BTCUSDC", "1h", days=90)

    # Run backtest
    bt = BacktestEngine(initial_balance=1000, fee_rate=0.001)
    bt.load_bars("BTCUSDC", "1h", bars)
    bt.add(EMACross, symbol="BTCUSDC", timeframe="1h")

    print("\nRunning backtest...")
    results = bt.run()

    print(results)
