"""Built-in strategies — pre-registered in the marketplace."""

from autopilot.marketplace.registry import registry
from autopilot.strategy import Strategy


@registry.register(
    name="ema_cross",
    description="EMA crossover with RSI momentum confirmation. "
    "Buys when fast EMA crosses above slow EMA and RSI > 50.",
    author="Autopilot",
    version="1.0.0",
    tags=["trend", "ema", "rsi", "beginner"],
    category="trend",
    timeframes=["1h", "4h"],
    pairs=["BTCUSDC", "ETHUSDC"],
    min_capital=50,
    risk_level="medium",
)
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
                self.buy(15)
        elif self.fast_ema() < self.slow_ema():
            if self.has_position():
                self.sell_all()


@registry.register(
    name="rsi_dca",
    description="Dollar Cost Averaging on RSI oversold dips. "
    "Buys layers when RSI < 30, sells on RSI > 70 or take-profit.",
    author="Autopilot",
    version="1.0.0",
    tags=["dca", "rsi", "accumulation", "beginner"],
    category="dca",
    timeframes=["4h", "1d"],
    pairs=["BTCUSDC", "ETHUSDC"],
    min_capital=50,
    risk_level="low",
)
class RSIDCA(Strategy):
    def setup(self):
        self.add_rsi(14)
        self._layers = 0

    def on_bar(self, bar):
        if not self.indicators_ready:
            return
        if self.rsi() < 30 and self._layers < 3:
            self.buy(10)
            self._layers += 1
        elif self.rsi() > 70 and self.has_position():
            self.sell_all()
            self._layers = 0


@registry.register(
    name="bollinger_bounce",
    description="Mean reversion on Bollinger Bands. "
    "Buys at lower band with RSI oversold, sells at upper band.",
    author="Autopilot",
    version="1.0.0",
    tags=["mean-reversion", "bollinger", "rsi", "intermediate"],
    category="mean-reversion",
    timeframes=["1h", "4h"],
    pairs=["BTCUSDC", "ETHUSDC", "SOLUSDC"],
    min_capital=100,
    risk_level="medium",
)
class BollingerBounce(Strategy):
    def setup(self):
        self.add_bollinger(20, 2.0)
        self.add_rsi(14)

    def on_bar(self, bar):
        if not self.indicators_ready:
            return
        bb = self.bollinger()
        if bar.close < bb["lower"] and self.rsi() < 30:
            if not self.has_position():
                self.buy(15)
        elif bar.close > bb["upper"] and self.has_position():
            self.sell_all()


@registry.register(
    name="momentum_scalp",
    description="Triple confirmation scalping: EMA trend + RSI momentum + "
    "Bollinger position. Bracket orders with 1:2 R:R.",
    author="Autopilot",
    version="1.0.0",
    tags=["scalping", "momentum", "bracket", "advanced"],
    category="scalping",
    timeframes=["15m", "1h"],
    pairs=["BTCUSDC", "ETHUSDC", "SOLUSDC"],
    min_capital=100,
    risk_level="high",
)
class MomentumScalp(Strategy):
    def setup(self):
        self.add_ema(8, "fast")
        self.add_ema(21, "slow")
        self.add_rsi(14)
        self.add_atr(14)
        self.add_bollinger(20, 2.0)

    def on_bar(self, bar):
        if not self.indicators_ready or self.has_position():
            return
        bb = self.bollinger()
        if (
            self.fast_ema() > self.slow_ema()
            and self.rsi() > 50
            and bar.close > bb["middle"]
        ):
            self.buy_bracket(15, sl_atr=1.5, tp_atr=3.0)
