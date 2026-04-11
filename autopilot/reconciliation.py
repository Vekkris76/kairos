"""Reconciliation — sync local state with exchange on startup.

After a restart, the engine needs to:
1. Check what orders are still open on the exchange
2. Check current positions/balances
3. Compare with saved state
4. Reconcile any differences
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from autopilot.exchanges.base import ExchangeAdapter
    from autopilot.orders.manager import OrderManager
    from autopilot.orders.position import PositionTracker
    from autopilot.state import StateManager

logger = logging.getLogger("autopilot.reconciliation")


async def reconcile_state(
    adapter: ExchangeAdapter,
    order_manager: OrderManager,
    positions: PositionTracker,
    state_manager: StateManager,
) -> dict:
    """Reconcile local state with exchange after restart.

    Returns a summary of what was reconciled.
    """
    summary = {
        "open_orders_synced": 0,
        "positions_restored": 0,
        "orphaned_orders_cancelled": 0,
    }

    # 1. Load saved state
    saved = state_manager.load()
    saved_positions = saved.get("positions", {})
    saved_orders = saved.get("open_orders", [])

    # 2. Get actual state from exchange
    try:
        exchange_orders = await adapter.get_open_orders()
        exchange_balances = await adapter.get_balances()
    except Exception as e:
        logger.error(f"Reconciliation failed — cannot reach exchange: {e}")
        return summary

    # 3. Sync open orders
    exchange_order_ids = {o.id for o in exchange_orders}
    for o in exchange_orders:
        order_manager.register_order(o)
        summary["open_orders_synced"] += 1
        logger.info(f"Synced open order: {o.id} {o.side.value} {o.symbol}")

    # 4. Cancel orphaned orders (in saved state but not on exchange)
    for saved_order in saved_orders:
        if saved_order["id"] not in exchange_order_ids:
            logger.warning(
                f"Orphaned order {saved_order['id']} — "
                f"was in state but not on exchange",
            )
            summary["orphaned_orders_cancelled"] += 1

    # 5. Restore positions from balances
    for currency, balance in exchange_balances.items():
        if currency in ("USDC", "USDT", "BNB"):
            continue
        if balance.total > 0:
            symbol = f"{currency}USDC"
            pos = positions.get(symbol)
            if not pos.is_open:
                # Position exists on exchange but not locally
                saved_pos = saved_positions.get(symbol, {})
                avg_entry = saved_pos.get("avg_entry", 0)
                logger.info(
                    f"Restored position: {balance.total} {currency} "
                    f"(avg_entry: {avg_entry})",
                )
                summary["positions_restored"] += 1

    logger.info(
        f"Reconciliation complete: "
        f"{summary['open_orders_synced']} orders synced, "
        f"{summary['positions_restored']} positions restored, "
        f"{summary['orphaned_orders_cancelled']} orphaned",
    )
    return summary
