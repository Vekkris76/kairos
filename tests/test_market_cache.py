"""Tests for kairos.cache.market_cache."""

from __future__ import annotations

import pytest

from kairos.cache import Account, MarketCache
from kairos.types import Bar, Fill, Instrument, Order, OrderSide, OrderStatus, OrderType


def _bar(symbol: str = "BTCUSDC", tf: str = "15m", ts: int = 0, close: float = 50000.0) -> Bar:
    return Bar(
        symbol=symbol,
        timeframe=tf,
        timestamp=ts,
        open=close - 10,
        high=close + 20,
        low=close - 30,
        close=close,
        volume=100.0,
    )


def _fill(symbol: str = "BTCUSDC", side: OrderSide = OrderSide.BUY, qty: float = 0.1, price: float = 50000.0) -> Fill:
    return Fill(
        order_id="o1",
        trade_id="t1",
        symbol=symbol,
        side=side,
        price=price,
        quantity=qty,
        commission=0.0,
        timestamp=0,
    )


def _order(symbol: str = "BTCUSDC", status: OrderStatus = OrderStatus.ACCEPTED, oid: str = "o-1") -> Order:
    return Order(
        id=oid,
        symbol=symbol,
        side=OrderSide.BUY,
        type=OrderType.LIMIT,
        quantity=0.1,
        price=50000.0,
        status=status,
    )


# ── Bars ────────────────────────────────────────────────────────


def test_ingest_and_retrieve_bars_in_order() -> None:
    cache = MarketCache()
    for i in range(5):
        cache.ingest_bar(_bar(ts=i * 1000))
    bars = cache.bars("BTCUSDC", "15m")
    assert len(bars) == 5
    assert [b.timestamp for b in bars] == [0, 1000, 2000, 3000, 4000]


def test_last_bar_returns_most_recent() -> None:
    cache = MarketCache()
    cache.ingest_bar(_bar(ts=1000, close=50_000))
    cache.ingest_bar(_bar(ts=2000, close=51_000))
    last = cache.last_bar("BTCUSDC", "15m")
    assert last is not None
    assert last.timestamp == 2000
    assert last.close == 51_000


def test_last_bar_returns_none_when_empty() -> None:
    cache = MarketCache()
    assert cache.last_bar("BTCUSDC", "15m") is None


def test_bars_returns_empty_list_for_unknown_stream() -> None:
    cache = MarketCache()
    assert cache.bars("ETHUSDC", "1h") == []


def test_bar_retention_evicts_oldest() -> None:
    cache = MarketCache(max_bars_per_stream=10)
    for i in range(15):
        cache.ingest_bar(_bar(ts=i))
    bars = cache.bars("BTCUSDC", "15m")
    assert len(bars) == 10
    # First 5 evicted; we keep 5..14
    assert [b.timestamp for b in bars] == list(range(5, 15))


def test_bars_with_limit_returns_last_n() -> None:
    cache = MarketCache()
    for i in range(20):
        cache.ingest_bar(_bar(ts=i))
    last_5 = cache.bars("BTCUSDC", "15m", limit=5)
    assert len(last_5) == 5
    assert [b.timestamp for b in last_5] == [15, 16, 17, 18, 19]


def test_bars_returns_snapshot_not_live_view() -> None:
    """Iterator safety: snapshot is independent of subsequent ingest."""
    cache = MarketCache()
    cache.ingest_bar(_bar(ts=1))
    snap = cache.bars("BTCUSDC", "15m")
    cache.ingest_bar(_bar(ts=2))
    assert len(snap) == 1   # snapshot did not grow


def test_is_warmed_up() -> None:
    cache = MarketCache()
    assert cache.is_warmed_up("BTCUSDC", "15m", 14) is False
    for i in range(13):
        cache.ingest_bar(_bar(ts=i))
    assert cache.is_warmed_up("BTCUSDC", "15m", 14) is False
    cache.ingest_bar(_bar(ts=13))
    assert cache.is_warmed_up("BTCUSDC", "15m", 14) is True


def test_bar_count() -> None:
    cache = MarketCache()
    assert cache.bar_count("BTCUSDC", "15m") == 0
    cache.ingest_bar(_bar(ts=1))
    cache.ingest_bar(_bar(ts=2))
    assert cache.bar_count("BTCUSDC", "15m") == 2


def test_separate_streams_per_timeframe() -> None:
    cache = MarketCache()
    cache.ingest_bar(_bar(tf="15m", ts=1))
    cache.ingest_bar(_bar(tf="1h", ts=2))
    assert cache.bar_count("BTCUSDC", "15m") == 1
    assert cache.bar_count("BTCUSDC", "1h") == 1


# ── Ticks ────────────────────────────────────────────────────────


def test_ingest_and_retrieve_last_tick() -> None:
    cache = MarketCache()
    cache.ingest_tick("BTCUSDC", 50_000.0)
    cache.ingest_tick("BTCUSDC", 50_100.0)
    assert cache.last_tick("BTCUSDC") == 50_100.0


def test_last_price_prefers_tick_over_bar() -> None:
    cache = MarketCache()
    cache.ingest_bar(_bar(close=50_000))
    cache.ingest_tick("BTCUSDC", 50_500.0)
    assert cache.last_price("BTCUSDC") == 50_500.0


def test_last_price_falls_back_to_bar_close_when_no_tick() -> None:
    cache = MarketCache()
    cache.ingest_bar(_bar(close=50_000))
    assert cache.last_price("BTCUSDC") == 50_000.0


def test_last_price_returns_none_when_no_data() -> None:
    cache = MarketCache()
    assert cache.last_price("UNKNOWN") is None


# ── Orders ───────────────────────────────────────────────────────


def test_ingest_and_get_order() -> None:
    cache = MarketCache()
    o = _order(oid="abc")
    cache.ingest_order(o)
    assert cache.order("abc") is o


def test_orders_open_filters_by_status() -> None:
    cache = MarketCache()
    cache.ingest_order(_order(oid="open1", status=OrderStatus.ACCEPTED))
    cache.ingest_order(_order(oid="open2", status=OrderStatus.PENDING))
    cache.ingest_order(_order(oid="filled", status=OrderStatus.FILLED))
    cache.ingest_order(_order(oid="canc", status=OrderStatus.CANCELLED))
    open_orders = cache.orders_open()
    assert {o.id for o in open_orders} == {"open1", "open2"}


def test_orders_open_filters_by_symbol() -> None:
    cache = MarketCache()
    cache.ingest_order(_order(oid="btc", symbol="BTCUSDC"))
    cache.ingest_order(_order(oid="eth", symbol="ETHUSDC"))
    btc_only = cache.orders_open(symbol="BTCUSDC")
    assert len(btc_only) == 1
    assert btc_only[0].id == "btc"


# ── Positions (netting via fills) ────────────────────────────────


def test_buy_then_sell_nets_to_zero() -> None:
    cache = MarketCache()
    cache.ingest_fill(_fill(side=OrderSide.BUY, qty=0.1, price=50_000))
    cache.ingest_fill(_fill(side=OrderSide.SELL, qty=0.1, price=51_000))
    pos = cache.position("BTCUSDC")
    assert pos is not None
    assert pos.quantity == 0.0
    assert pos.realized_pnl == pytest.approx(100.0)  # (51000-50000)*0.1


def test_buy_then_partial_sell_keeps_remaining() -> None:
    cache = MarketCache()
    cache.ingest_fill(_fill(side=OrderSide.BUY, qty=0.2, price=50_000))
    cache.ingest_fill(_fill(side=OrderSide.SELL, qty=0.1, price=52_000))
    pos = cache.position("BTCUSDC")
    assert pos is not None
    assert pos.quantity == pytest.approx(0.1)
    assert pos.realized_pnl == pytest.approx(200.0)
    assert pos.avg_entry == pytest.approx(50_000)  # avg unchanged on partial close


def test_two_buys_average_entry_is_volume_weighted() -> None:
    cache = MarketCache()
    cache.ingest_fill(_fill(side=OrderSide.BUY, qty=0.1, price=50_000))
    cache.ingest_fill(_fill(side=OrderSide.BUY, qty=0.1, price=51_000))
    pos = cache.position("BTCUSDC")
    assert pos is not None
    assert pos.quantity == pytest.approx(0.2)
    assert pos.avg_entry == pytest.approx(50_500)


def test_positions_open_filters_zero_qty() -> None:
    cache = MarketCache()
    cache.ingest_fill(_fill(symbol="BTCUSDC", side=OrderSide.BUY, qty=0.1))
    cache.ingest_fill(_fill(symbol="BTCUSDC", side=OrderSide.SELL, qty=0.1))
    cache.ingest_fill(_fill(symbol="ETHUSDC", side=OrderSide.BUY, qty=1.0))
    open_pos = cache.positions_open()
    assert len(open_pos) == 1
    assert open_pos[0].symbol == "ETHUSDC"


# ── Accounts ─────────────────────────────────────────────────────


def test_ingest_account_and_query_balances() -> None:
    cache = MarketCache()
    acct = Account(
        venue="binance",
        balances_free={"USDC": 1000.0, "BTC": 0.05},
        balances_locked={"USDC": 50.0},
    )
    cache.ingest_account(acct)
    got = cache.account("binance")
    assert got is not None
    assert got.free("USDC") == 1000.0
    assert got.locked("USDC") == 50.0
    assert got.total("USDC") == 1050.0
    assert got.free("EUR") == 0.0  # missing currency = 0


# ── Instruments ──────────────────────────────────────────────────


def test_ingest_and_query_instrument() -> None:
    cache = MarketCache()
    inst = Instrument(
        symbol="BTCUSDC",
        base="BTC",
        quote="USDC",
        min_qty=0.00001,
        max_qty=9000.0,
        qty_step=0.00001,
        min_notional=10.0,
        price_precision=2,
        qty_precision=5,
    )
    cache.ingest_instruments([inst])
    got = cache.instrument("BTCUSDC")
    assert got is not None
    assert got.min_notional == 10.0


# ── Configuration validation ─────────────────────────────────────


def test_zero_max_bars_rejected() -> None:
    with pytest.raises(ValueError, match="max_bars_per_stream"):
        MarketCache(max_bars_per_stream=0)


def test_zero_max_ticks_rejected() -> None:
    with pytest.raises(ValueError, match="max_ticks_per_instrument"):
        MarketCache(max_ticks_per_instrument=0)


# ── Stats ────────────────────────────────────────────────────────


def test_stats_reports_counts() -> None:
    cache = MarketCache()
    cache.ingest_bar(_bar(ts=1))
    cache.ingest_tick("BTCUSDC", 50_000)
    cache.ingest_order(_order(oid="o1", status=OrderStatus.ACCEPTED))
    cache.ingest_order(_order(oid="o2", status=OrderStatus.FILLED))
    cache.ingest_fill(_fill(side=OrderSide.BUY))
    s = cache.stats()
    assert s["bar_streams"] == 1
    assert s["total_bars"] == 1
    assert s["tick_streams"] == 1
    assert s["orders"] == 2
    assert s["open_orders"] == 1
    assert s["positions"] == 1
    assert s["open_positions"] == 1
