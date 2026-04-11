"""Strategy Builder — create strategies from JSON config (no code needed).

Allows users to build strategies via a web UI that generates
a JSON config, which this module converts to a runnable Strategy.

Usage:
    config = {
        "name": "my_bot",
        "indicators": [
            {"type": "ema", "period": 8, "name": "fast"},
            {"type": "ema", "period": 21, "name": "slow"},
            {"type": "rsi", "period": 14},
        ],
        "entry": {
            "conditions": [
                {"indicator": "fast_ema", "operator": ">", "value": "slow_ema"},
                {"indicator": "rsi", "operator": ">", "value": 50},
            ],
            "action": "buy",
            "size_pct": 15,
        },
        "exit": {
            "conditions": [
                {"indicator": "fast_ema", "operator": "<", "value": "slow_ema"},
            ],
            "action": "sell_all",
        },
        "bracket": {
            "sl_atr": 1.5,
            "tp_atr": 3.0,
        },
    }

    strategy_cls = StrategyBuilder.from_config(config)
    engine.add(strategy_cls, symbol="BTCUSDC", timeframe="1h")
"""

from __future__ import annotations

import logging
from typing import Any

from autopilot.strategy import Strategy
from autopilot.types import Bar

logger = logging.getLogger("autopilot.builder")


class StrategyBuilder:
    """Build a Strategy class from a JSON configuration."""

    @staticmethod
    def from_config(config: dict[str, Any]) -> type[Strategy]:
        """Create a Strategy class from a config dict."""
        name = config.get("name", "CustomStrategy")
        indicators_config = config.get("indicators", [])
        entry_config = config.get("entry", {})
        exit_config = config.get("exit", {})
        bracket_config = config.get("bracket")

        class ConfigStrategy(Strategy):
            _config = config

            def setup(self):
                for ind in indicators_config:
                    ind_type = ind["type"]
                    if ind_type == "ema":
                        self.add_ema(ind["period"], ind.get("name", ""))
                    elif ind_type == "sma":
                        self.add_sma(ind["period"], ind.get("name", ""))
                    elif ind_type == "rsi":
                        self.add_rsi(ind.get("period", 14))
                    elif ind_type == "atr":
                        self.add_atr(ind.get("period", 14))
                    elif ind_type == "bollinger":
                        self.add_bollinger(
                            ind.get("period", 20),
                            ind.get("std", 2.0),
                        )
                    elif ind_type == "macd":
                        self.add_macd(
                            ind.get("fast", 12),
                            ind.get("slow", 26),
                            ind.get("signal", 9),
                        )
                    elif ind_type == "stochastic":
                        self.add_stochastic(
                            ind.get("k", 14),
                            ind.get("d", 3),
                        )
                    elif ind_type == "adx":
                        self.add_adx(ind.get("period", 14))

            def on_bar(self, bar: Bar):
                if not self.indicators_ready:
                    return

                # Check entry conditions
                if not self.has_position():
                    if _check_conditions(self, entry_config.get("conditions", []), bar):
                        size = entry_config.get("size_pct", 10)
                        if bracket_config:
                            self.buy_bracket(
                                size,
                                bracket_config.get("sl_atr", 1.5),
                                bracket_config.get("tp_atr", 3.0),
                            )
                        else:
                            self.buy(size)

                # Check exit conditions
                elif self.has_position():
                    if _check_conditions(self, exit_config.get("conditions", []), bar):
                        action = exit_config.get("action", "sell_all")
                        if action == "sell_all":
                            self.sell_all()

        ConfigStrategy.__name__ = name
        ConfigStrategy.__qualname__ = name
        return ConfigStrategy

    @staticmethod
    def validate_config(config: dict) -> list[str]:
        """Validate a strategy config. Returns list of errors."""
        errors = []

        if "indicators" not in config:
            errors.append("Missing 'indicators' section")

        if "entry" not in config:
            errors.append("Missing 'entry' section")

        if "exit" not in config:
            errors.append("Missing 'exit' section")

        for i, ind in enumerate(config.get("indicators", [])):
            if "type" not in ind:
                errors.append(f"Indicator {i}: missing 'type'")
            if ind.get("type") in ("ema", "sma", "rsi", "atr") and "period" not in ind:
                errors.append(f"Indicator {i}: missing 'period'")

        for section in ("entry", "exit"):
            conditions = config.get(section, {}).get("conditions", [])
            for j, cond in enumerate(conditions):
                if "indicator" not in cond:
                    errors.append(f"{section}.conditions[{j}]: missing 'indicator'")
                if "operator" not in cond:
                    errors.append(f"{section}.conditions[{j}]: missing 'operator'")
                if "value" not in cond:
                    errors.append(f"{section}.conditions[{j}]: missing 'value'")

        return errors

    @staticmethod
    def to_json(config: dict) -> str:
        """Serialize config to JSON string."""
        import json
        return json.dumps(config, indent=2)

    @staticmethod
    def from_json(json_str: str) -> dict:
        """Deserialize config from JSON string."""
        import json
        return json.loads(json_str)


def _check_conditions(strategy: Strategy, conditions: list[dict], bar: Bar) -> bool:
    """Evaluate a list of conditions against current indicator values."""
    if not conditions:
        return False

    for cond in conditions:
        indicator = cond["indicator"]
        operator = cond["operator"]
        raw_value = cond["value"]

        # Get indicator value
        left = _get_indicator_value(strategy, indicator, bar)

        # Get comparison value (can be another indicator or a number)
        if isinstance(raw_value, str):
            right = _get_indicator_value(strategy, raw_value, bar)
        else:
            right = float(raw_value)

        # Compare
        if operator == ">" and not (left > right):
            return False
        elif operator == "<" and not (left < right):
            return False
        elif operator == ">=" and not (left >= right):
            return False
        elif operator == "<=" and not (left <= right):
            return False
        elif operator == "==" and not (left == right):
            return False

    return True  # All conditions passed


def _get_indicator_value(strategy: Strategy, name: str, bar: Bar) -> float:
    """Resolve an indicator name to its current value."""
    if name == "close":
        return bar.close
    elif name == "open":
        return bar.open
    elif name == "high":
        return bar.high
    elif name == "low":
        return bar.low
    elif name == "volume":
        return bar.volume
    elif name == "rsi":
        return strategy.rsi()
    elif name == "atr":
        return strategy.atr()
    elif name == "fast_ema":
        return strategy.fast_ema()
    elif name == "slow_ema":
        return strategy.slow_ema()
    elif name == "vwap":
        return strategy.vwap()
    elif name == "adx":
        return strategy.adx()
    elif name.startswith("bb_"):
        bb = strategy.bollinger()
        if name == "bb_upper":
            return bb["upper"]
        elif name == "bb_lower":
            return bb["lower"]
        elif name == "bb_middle":
            return bb["middle"]
    elif name.startswith("macd_"):
        m = strategy.macd()
        if name == "macd_value":
            return m["macd"]
        elif name == "macd_signal":
            return m["signal"]
        elif name == "macd_histogram":
            return m["histogram"]

    # Try direct indicator lookup
    ind = strategy._indicators.get(name)
    if ind:
        return ind.value

    return 0.0
