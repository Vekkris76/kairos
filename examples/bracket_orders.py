"""BracketManager example — atomic entry + SL + TP with OCO semantics.

Uses a mock adapter so it runs offline. In production, swap the adapter
for ``BinanceLive`` and your strategy will get the same behavior.

Run::

    python examples/bracket_orders.py
"""

from __future__ import annotations

import asyncio
import logging

from kairos import BracketManager
from kairos.types import Order, OrderSide, OrderStatus, OrderType, TimeInForce

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


class MockAdapter:
    """Pretends to be an exchange. Logs every submit/cancel."""

    def __init__(self) -> None:
        self._counter = 0

    async def submit_order(self, **kwargs) -> Order:
        self._counter += 1
        oid = f"mock-{self._counter}"
        print(f"  ➜ submit: {kwargs['side'].name} {kwargs['quantity']} "
              f"{kwargs['symbol']} type={kwargs['order_type'].name}")
        return Order(
            id=oid,
            symbol=kwargs["symbol"],
            side=kwargs["side"],
            type=kwargs["order_type"],
            quantity=kwargs["quantity"],
            price=kwargs.get("price"),
            stop_price=kwargs.get("stop_price"),
            status=OrderStatus.ACCEPTED,
        )

    async def cancel_order(self, *, symbol: str, order_id: str) -> bool:
        print(f"  ➜ cancel: {order_id}")
        return True


async def main() -> None:
    adapter = MockAdapter()
    bm = BracketManager(adapter=adapter)

    print("\n[1] Submit a bracket: BUY 0.001 BTCUSDC, SL @ 49000, TP @ 52000")
    bracket = await bm.submit_bracket(
        symbol="BTCUSDC",
        side=OrderSide.BUY,
        quantity=0.001,
        sl_price=49_000.0,
        tp_price=52_000.0,
        reference_price=50_000.0,
    )
    print(f"  Bracket {bracket.bracket_id} state={bracket.state}")
    print(f"  entry={bracket.entry_order_id} sl={bracket.sl_order_id} "
          f"tp={bracket.tp_order_id}")

    print("\n[2] Simulate TP fill — engine should auto-cancel SL via OCO")
    result = await bm.on_order_filled(bracket.tp_order_id)
    print(f"  Bracket {result.bracket_id} state={result.state} "
          f"exit_type={result.exit_type}")

    print("\n[3] Submit a second bracket then manually cancel it")
    b2 = await bm.submit_bracket(
        symbol="ETHUSDC",
        side=OrderSide.BUY,
        quantity=0.05,
        sl_price=2900.0,
        tp_price=3200.0,
        reference_price=3000.0,
    )
    cancelled = await bm.cancel_bracket(b2.bracket_id)
    print(f"  cancel_bracket returned {cancelled}, state={b2.state}")


if __name__ == "__main__":
    asyncio.run(main())
