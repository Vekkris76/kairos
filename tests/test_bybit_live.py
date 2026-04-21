"""Tests for kairos.adapters.bybit_live WS parsers + pure helpers.

Network-dependent paths (real REST, real WS handshake) are exercised by
the manual testnet smoke runbook. Here we unit-test the interval mapping,
status/type enums, URL selection, and the two ``_process_*_ws_message``
branches that carry 95 % of the integration risk.
"""

from __future__ import annotations

import json

import pytest

from kairos.adapters.bybit_live import (
    BybitLive,
    _BYBIT_REST_PROD,
    _BYBIT_REST_TEST,
    _BYBIT_WS_PRIV_PROD,
    _BYBIT_WS_PRIV_TEST,
    _BYBIT_WS_PUB_PROD,
    _BYBIT_WS_PUB_TEST,
    _bybit_interval,
    _map_bybit_order_status,
    _map_bybit_order_type,
)
from kairos.types import Bar, Fill, Order, OrderSide, OrderStatus, OrderType

pytestmark = pytest.mark.asyncio


def test_bybit_venue_id() -> None:
    assert BybitLive.venue_id == "bybit"
    adapter = BybitLive(api_key="k", api_secret="s")
    assert adapter.venue_id == "bybit"


def test_rest_and_ws_bases_switch_on_testnet_flag() -> None:
    prod = BybitLive(api_key="k", api_secret="s", testnet=False)
    test = BybitLive(api_key="k", api_secret="s", testnet=True)

    assert prod._rest_base() == _BYBIT_REST_PROD
    assert prod._ws_public_url() == _BYBIT_WS_PUB_PROD
    assert prod._ws_private_url() == _BYBIT_WS_PRIV_PROD
    assert test._rest_base() == _BYBIT_REST_TEST
    assert test._ws_public_url() == _BYBIT_WS_PUB_TEST
    assert test._ws_private_url() == _BYBIT_WS_PRIV_TEST


def test_bybit_interval_mapping() -> None:
    assert _bybit_interval("1m") == "1"
    assert _bybit_interval("3m") == "3"
    assert _bybit_interval("5m") == "5"
    assert _bybit_interval("15m") == "15"
    assert _bybit_interval("30m") == "30"
    assert _bybit_interval("1h") == "60"
    assert _bybit_interval("2h") == "120"
    assert _bybit_interval("4h") == "240"
    assert _bybit_interval("6h") == "360"
    assert _bybit_interval("12h") == "720"
    assert _bybit_interval("1d") == "D"
    assert _bybit_interval("1w") == "W"
    assert _bybit_interval("1M") == "M"

    with pytest.raises(ValueError, match="unsupported timeframe"):
        _bybit_interval("7m")


def test_map_bybit_order_status() -> None:
    assert _map_bybit_order_status("New") == OrderStatus.ACCEPTED
    assert _map_bybit_order_status("PartiallyFilled") == OrderStatus.PARTIALLY_FILLED
    assert _map_bybit_order_status("Filled") == OrderStatus.FILLED
    assert _map_bybit_order_status("Cancelled") == OrderStatus.CANCELLED
    assert _map_bybit_order_status("Rejected") == OrderStatus.REJECTED
    # Unknown → safe fallback
    assert _map_bybit_order_status("Frobulated") == OrderStatus.SUBMITTED
    assert _map_bybit_order_status(None) == OrderStatus.SUBMITTED


def test_map_bybit_order_type() -> None:
    assert _map_bybit_order_type("Market") == OrderType.MARKET
    assert _map_bybit_order_type("Limit") == OrderType.LIMIT
    assert _map_bybit_order_type("StopMarket") == OrderType.STOP_MARKET
    assert _map_bybit_order_type("StopLimit") == OrderType.STOP_LIMIT
    assert _map_bybit_order_type(None) == OrderType.MARKET


# ── private WS (order topic) parsing ────────────────────────────


def _order_frame(**overrides) -> str:
    """Build a realistic Bybit private-WS ``order`` frame, overridable."""
    base = {
        "topic": "order",
        "data": [{
            "orderId": "abc123",
            "symbol": "BTCUSDT",
            "side": "Buy",
            "orderType": "Limit",
            "orderStatus": "Filled",
            "qty": "0.01",
            "price": "50000",
            "cumExecQty": "0.01",
            "avgPrice": "49950",
            "cumExecFee": "0.05",
            "createdTime": "1700000000000",
        }],
    }
    base["data"][0].update(overrides)
    return json.dumps(base)


async def test_process_private_ws_message_emits_fill_on_filled() -> None:
    adapter = BybitLive(api_key="k", api_secret="s")
    captured: list[Fill] = []

    async def fill_cb(fill: Fill) -> None:
        captured.append(fill)

    adapter.set_fill_callback(fill_cb)
    await adapter._process_private_ws_message(_order_frame())

    assert len(captured) == 1
    fill = captured[0]
    assert fill.symbol == "BTCUSDT"
    assert fill.side == OrderSide.BUY
    assert fill.price == 49_950.0
    assert fill.quantity == 0.01
    assert fill.commission == 0.05
    assert fill.order_id == "abc123"
    assert fill.trade_id == "abc123"
    assert fill.timestamp == 1_700_000_000_000


async def test_process_private_ws_message_emits_fill_on_partially_filled() -> None:
    adapter = BybitLive(api_key="k", api_secret="s")
    fills: list[Fill] = []
    orders: list[Order] = []

    async def fill_cb(f: Fill) -> None:
        fills.append(f)

    async def order_cb(o: Order) -> None:
        orders.append(o)

    adapter.set_fill_callback(fill_cb)
    adapter.set_order_update_callback(order_cb)

    await adapter._process_private_ws_message(
        _order_frame(
            orderStatus="PartiallyFilled",
            cumExecQty="0.003",
            avgPrice="49900",
        )
    )

    assert len(fills) == 1
    assert fills[0].quantity == 0.003
    assert fills[0].price == 49_900.0
    assert len(orders) == 1
    assert orders[0].status == OrderStatus.PARTIALLY_FILLED


async def test_process_private_ws_message_skips_new() -> None:
    adapter = BybitLive(api_key="k", api_secret="s")
    fills: list[Fill] = []
    orders: list[Order] = []

    async def fill_cb(f: Fill) -> None:
        fills.append(f)

    async def order_cb(o: Order) -> None:
        orders.append(o)

    adapter.set_fill_callback(fill_cb)
    adapter.set_order_update_callback(order_cb)

    await adapter._process_private_ws_message(
        _order_frame(orderStatus="New", cumExecQty="0", avgPrice="0")
    )

    assert fills == []
    assert len(orders) == 1
    assert orders[0].status == OrderStatus.ACCEPTED
    assert orders[0].side == OrderSide.BUY
    assert orders[0].type == OrderType.LIMIT


# ── public WS (kline topic) parsing ─────────────────────────────


def _kline_frame(*, confirm: bool, symbol: str = "BTCUSDT", interval: str = "240") -> str:
    return json.dumps({
        "topic": f"kline.{interval}.{symbol}",
        "data": [{
            "start": 1_700_000_000_000,
            "end": 1_700_086_400_000,
            "open": "50000",
            "high": "51000",
            "low": "49000",
            "close": "50500",
            "volume": "100.5",
            "confirm": confirm,
        }],
    })


async def test_bar_emitted_only_on_confirm_true() -> None:
    adapter = BybitLive(api_key="k", api_secret="s")
    bars: list[Bar] = []

    async def bar_cb(bar: Bar) -> None:
        bars.append(bar)

    adapter.set_bar_callback(bar_cb)
    # subscribe_bars would normally populate this; wire it directly for
    # the pure-parser test.
    adapter._bar_subscriptions["kline.240.BTCUSDT"] = ("BTCUSDT", "4h")

    await adapter._process_market_ws_message(_kline_frame(confirm=False))
    assert bars == []

    await adapter._process_market_ws_message(_kline_frame(confirm=True))
    assert len(bars) == 1
    bar = bars[0]
    assert bar.symbol == "BTCUSDT"
    assert bar.timeframe == "4h"
    assert bar.timestamp == 1_700_000_000_000
    assert bar.open == 50_000.0
    assert bar.close == 50_500.0
    assert bar.volume == 100.5
