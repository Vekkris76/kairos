"""Tests for risk validator."""

from kairos.risk.validator import RiskValidator
from kairos.types import Balance, Instrument, OrderSide, TradingState


def _instrument() -> Instrument:
    return Instrument(
        symbol="BTCUSDC", base="BTC", quote="USDC",
        min_qty=0.00001, max_qty=1000, qty_step=0.00001,
        min_notional=5.0, price_precision=2, qty_precision=5,
    )


def _balances(usdc: float = 100) -> dict[str, Balance]:
    return {"USDC": Balance(currency="USDC", free=usdc, locked=0)}


class TestRiskValidator:
    def test_valid_order_passes(self):
        rv = RiskValidator()
        err = rv.validate_order(
            "BTCUSDC", OrderSide.BUY, 0.001, 70000,
            _instrument(), _balances(100),
        )
        assert err is None

    def test_insufficient_balance(self):
        rv = RiskValidator()
        err = rv.validate_order(
            "BTCUSDC", OrderSide.BUY, 0.01, 70000,
            _instrument(), _balances(10),  # 10 USDC < 700 needed
        )
        assert err is not None
        assert "Insufficient" in err

    def test_below_min_qty(self):
        rv = RiskValidator()
        err = rv.validate_order(
            "BTCUSDC", OrderSide.BUY, 0.000001, 70000,
            _instrument(), _balances(100),
        )
        assert err is not None
        assert "min" in err.lower()

    def test_below_min_notional(self):
        rv = RiskValidator()
        err = rv.validate_order(
            "BTCUSDC", OrderSide.BUY, 0.00001, 70000,
            _instrument(), _balances(100),  # notional = 0.7 < 5
        )
        assert err is not None
        assert "Notional" in err

    def test_halted_rejects(self):
        rv = RiskValidator()
        rv._state = TradingState.HALTED
        err = rv.validate_order(
            "BTCUSDC", OrderSide.BUY, 0.001, 70000,
            _instrument(), _balances(100),
        )
        assert err is not None
        assert "HALTED" in err

    def test_reducing_allows_sell(self):
        rv = RiskValidator()
        rv._state = TradingState.REDUCING
        err = rv.validate_order(
            "BTCUSDC", OrderSide.SELL, 0.001, 70000,
            _instrument(), _balances(100),
        )
        assert err is None

    def test_reducing_blocks_buy(self):
        rv = RiskValidator()
        rv._state = TradingState.REDUCING
        err = rv.validate_order(
            "BTCUSDC", OrderSide.BUY, 0.001, 70000,
            _instrument(), _balances(100),
        )
        assert err is not None
        assert "REDUCING" in err

    def test_drawdown_halts(self):
        rv = RiskValidator(max_drawdown_pct=10)
        rv.update_equity(100)
        rv.update_equity(89)  # 11% drawdown
        assert rv.state == TradingState.HALTED

    def test_reset(self):
        rv = RiskValidator()
        rv._state = TradingState.HALTED
        rv.reset()
        assert rv.state == TradingState.ACTIVE

    def test_rate_limit(self):
        rv = RiskValidator(max_orders_per_minute=2)
        inst = _instrument()
        bal = _balances(10000)
        # First 2 orders pass
        assert rv.validate_order("BTCUSDC", OrderSide.BUY, 0.001, 70000, inst, bal) is None
        assert rv.validate_order("BTCUSDC", OrderSide.BUY, 0.001, 70000, inst, bal) is None
        # Third is rate limited
        err = rv.validate_order("BTCUSDC", OrderSide.BUY, 0.001, 70000, inst, bal)
        assert err is not None
        assert "Rate" in err
