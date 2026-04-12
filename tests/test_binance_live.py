"""Tests for kairos.adapters.binance_live user-data WS internals.

The network-dependent paths (real WebSocket + real REST) are exercised by
the manual testnet smoke runbook. Here we unit-test the pure parsing and
control-flow bits: message dispatch, order-status mapping, testnet URL
selection, and lifecycle.
"""

from __future__ import annotations

import json

import pytest

from kairos.adapters.binance_live import (
    BinanceLive,
    _BINANCE_REST_PROD,
    _BINANCE_REST_TEST,
    _BINANCE_WS_PROD,
    _BINANCE_WS_TEST,
    _map_binance_order_status,
    _map_binance_order_type,
)
from kairos.types import Fill, Order, OrderSide, OrderStatus, OrderType


pytestmark = pytest.mark.asyncio


def test_rest_and_ws_bases_switch_on_testnet_flag() -> None:
    prod = BinanceLive(api_key="k", api_secret="s", testnet=False)
    test = BinanceLive(api_key="k", api_secret="s", testnet=True)

    assert prod._rest_base() == _BINANCE_REST_PROD
    assert prod._ws_base() == _BINANCE_WS_PROD
    assert test._rest_base() == _BINANCE_REST_TEST
    assert test._ws_base() == _BINANCE_WS_TEST


def test_map_binance_order_status() -> None:
    assert _map_binance_order_status("NEW") == OrderStatus.ACCEPTED
    assert _map_binance_order_status("PARTIALLY_FILLED") == OrderStatus.PARTIALLY_FILLED
    assert _map_binance_order_status("FILLED") == OrderStatus.FILLED
    assert _map_binance_order_status("CANCELED") == OrderStatus.CANCELLED
    assert _map_binance_order_status("REJECTED") == OrderStatus.REJECTED
    assert _map_binance_order_status("EXPIRED") == OrderStatus.CANCELLED
    # Unknown → safe fallback
    assert _map_binance_order_status("FROBULATED") == OrderStatus.SUBMITTED
    assert _map_binance_order_status(None) == OrderStatus.SUBMITTED


def test_map_binance_order_type() -> None:
    assert _map_binance_order_type("MARKET") == OrderType.MARKET
    assert _map_binance_order_type("LIMIT") == OrderType.LIMIT
    assert _map_binance_order_type("LIMIT_MAKER") == OrderType.LIMIT
    assert _map_binance_order_type("STOP_LOSS") == OrderType.STOP_MARKET
    assert _map_binance_order_type("STOP_LOSS_LIMIT") == OrderType.STOP_LIMIT
    assert _map_binance_order_type("TAKE_PROFIT_LIMIT") == OrderType.STOP_LIMIT


# ── executionReport parsing ─────────────────────────────────────


def _execution_report(**overrides) -> str:
    """Build a realistic Binance executionReport frame, overridable."""
    base = {
        "e": "executionReport",
        "s": "BTCUSDC",
        "S": "BUY",
        "o": "LIMIT",
        "q": "0.01",
        "p": "50000.00",
        "i": 12345,
        "t": 67890,
        "X": "FILLED",
        "x": "TRADE",
        "L": "49950.00",   # last executed price
        "l": "0.01",       # last executed qty
        "n": "0.05",       # commission
        "T": 1_700_000_000_000,  # event time (ms)
    }
    base.update(overrides)
    return json.dumps(base)


async def test_process_user_ws_message_emits_fill_on_trade() -> None:
    adapter = BinanceLive(api_key="k", api_secret="s")
    captured: list[Fill] = []

    async def fill_cb(fill: Fill) -> None:
        captured.append(fill)

    adapter.set_fill_callback(fill_cb)
    await adapter._process_user_ws_message(_execution_report())

    assert len(captured) == 1
    fill = captured[0]
    assert fill.symbol == "BTCUSDC"
    assert fill.side == OrderSide.BUY
    assert fill.price == 49_950.0
    assert fill.quantity == 0.01
    assert fill.commission == 0.05
    assert fill.order_id == "12345"
    assert fill.trade_id == "67890"
    assert fill.timestamp == 1_700_000_000_000


async def test_process_user_ws_message_skips_non_execution_reports() -> None:
    adapter = BinanceLive(api_key="k", api_secret="s")
    captured: list[Fill] = []

    async def fill_cb(fill: Fill) -> None:
        captured.append(fill)

    adapter.set_fill_callback(fill_cb)

    for e_type in ("outboundAccountPosition", "balanceUpdate", "listStatus"):
        await adapter._process_user_ws_message(json.dumps({"e": e_type}))

    assert captured == []


async def test_process_user_ws_message_skips_new_exec_type() -> None:
    """exec_type=NEW means order accepted, not a fill yet."""
    adapter = BinanceLive(api_key="k", api_secret="s")
    captured: list[Fill] = []

    async def fill_cb(fill: Fill) -> None:
        captured.append(fill)

    adapter.set_fill_callback(fill_cb)
    msg = _execution_report(x="NEW", X="NEW", L="0", l="0")
    await adapter._process_user_ws_message(msg)

    assert captured == []


async def test_process_user_ws_message_forwards_order_update() -> None:
    adapter = BinanceLive(api_key="k", api_secret="s")
    orders: list[Order] = []

    async def order_cb(order: Order) -> None:
        orders.append(order)

    adapter.set_order_update_callback(order_cb)
    # NEW status — just an order confirmation (no fill)
    msg = _execution_report(x="NEW", X="NEW", L="0", l="0")
    await adapter._process_user_ws_message(msg)

    assert len(orders) == 1
    assert orders[0].id == "12345"
    assert orders[0].symbol == "BTCUSDC"
    assert orders[0].side == OrderSide.BUY
    assert orders[0].status == OrderStatus.ACCEPTED
    assert orders[0].type == OrderType.LIMIT


async def test_process_user_ws_message_partial_fill_emits_both() -> None:
    adapter = BinanceLive(api_key="k", api_secret="s")
    fills: list[Fill] = []
    orders: list[Order] = []

    async def fill_cb(f: Fill) -> None:
        fills.append(f)

    async def order_cb(o: Order) -> None:
        orders.append(o)

    adapter.set_fill_callback(fill_cb)
    adapter.set_order_update_callback(order_cb)

    msg = _execution_report(
        X="PARTIALLY_FILLED", x="TRADE",
        l="0.003", L="49900.00",
    )
    await adapter._process_user_ws_message(msg)

    assert len(fills) == 1
    assert fills[0].quantity == 0.003
    assert fills[0].price == 49_900.0
    assert len(orders) == 1
    assert orders[0].status == OrderStatus.PARTIALLY_FILLED


async def test_process_user_ws_message_sell_side() -> None:
    adapter = BinanceLive(api_key="k", api_secret="s")
    fills: list[Fill] = []

    async def fill_cb(f: Fill) -> None:
        fills.append(f)

    adapter.set_fill_callback(fill_cb)
    await adapter._process_user_ws_message(_execution_report(S="SELL"))
    assert fills[0].side == OrderSide.SELL
