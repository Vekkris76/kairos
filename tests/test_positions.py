"""Tests for position tracking."""

from kairos.orders.position import PositionTracker
from kairos.types import Fill, OrderSide


def _fill(symbol: str, side: OrderSide, price: float, qty: float, commission: float = 0) -> Fill:
    return Fill(
        order_id="o1", trade_id="t1", symbol=symbol,
        side=side, price=price, quantity=qty,
        commission=commission, timestamp=0,
    )


class TestPositionTracker:
    def test_open_position(self):
        pt = PositionTracker()
        pt.update(_fill("BTCUSDC", OrderSide.BUY, 70000, 0.001))
        pos = pt.get("BTCUSDC")
        assert pos.is_open
        assert pos.quantity == 0.001
        assert pos.avg_entry == 70000

    def test_close_position_profit(self):
        pt = PositionTracker()
        pt.update(_fill("BTCUSDC", OrderSide.BUY, 70000, 0.001))
        pt.update(_fill("BTCUSDC", OrderSide.SELL, 71000, 0.001))
        pos = pt.get("BTCUSDC")
        assert not pos.is_open
        assert pos.realized_pnl == 1.0  # (71000-70000)*0.001

    def test_close_position_loss(self):
        pt = PositionTracker()
        pt.update(_fill("BTCUSDC", OrderSide.BUY, 70000, 0.001))
        pt.update(_fill("BTCUSDC", OrderSide.SELL, 69000, 0.001))
        pos = pt.get("BTCUSDC")
        assert pos.realized_pnl == -1.0

    def test_commission_deducted(self):
        pt = PositionTracker()
        pt.update(_fill("BTCUSDC", OrderSide.BUY, 70000, 0.001))
        pt.update(_fill("BTCUSDC", OrderSide.SELL, 71000, 0.001, commission=0.5))
        pos = pt.get("BTCUSDC")
        assert pos.realized_pnl == 0.5  # 1.0 profit - 0.5 commission

    def test_dca_avg_entry(self):
        pt = PositionTracker()
        pt.update(_fill("BTCUSDC", OrderSide.BUY, 70000, 0.001))
        pt.update(_fill("BTCUSDC", OrderSide.BUY, 68000, 0.001))
        pos = pt.get("BTCUSDC")
        assert pos.quantity == 0.002
        assert pos.avg_entry == 69000  # (70000+68000)/2

    def test_partial_close(self):
        pt = PositionTracker()
        pt.update(_fill("BTCUSDC", OrderSide.BUY, 70000, 0.002))
        pt.update(_fill("BTCUSDC", OrderSide.SELL, 72000, 0.001))
        pos = pt.get("BTCUSDC")
        assert pos.is_open
        assert pos.quantity == 0.001
        assert pos.realized_pnl == 2.0  # (72000-70000)*0.001

    def test_multiple_symbols(self):
        pt = PositionTracker()
        pt.update(_fill("BTCUSDC", OrderSide.BUY, 70000, 0.001))
        pt.update(_fill("ETHUSDC", OrderSide.BUY, 2000, 0.01))
        assert pt.get("BTCUSDC").is_open
        assert pt.get("ETHUSDC").is_open
        assert len(pt.open_positions) == 2

    def test_flat_position(self):
        pt = PositionTracker()
        pos = pt.get("BTCUSDC")
        assert not pos.is_open
        assert pos.side == "FLAT"
