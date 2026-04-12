"""Tests for kairos.runtime.event_bus."""

from __future__ import annotations

import pytest

from kairos.runtime.event_bus import EventBus, UnknownEventKindError


pytestmark = pytest.mark.asyncio


async def test_publish_and_consume() -> None:
    bus = EventBus()
    sub = bus.subscribe({"bar"}, name="test")
    await bus.publish("bar", {"close": 100.0})

    kind, event = await sub.queue.get()
    assert kind == "bar"
    assert event == {"close": 100.0}


async def test_subscriber_only_receives_subscribed_kinds() -> None:
    bus = EventBus()
    sub = bus.subscribe({"bar"}, name="bar_only")

    await bus.publish("bar", "got_it")
    await bus.publish("tick", "ignored")

    kind, event = await sub.queue.get()
    assert kind == "bar"
    assert event == "got_it"
    assert sub.queue.empty()  # tick was not delivered


async def test_two_subscribers_both_receive() -> None:
    bus = EventBus()
    sub_a = bus.subscribe({"order_filled"}, name="a")
    sub_b = bus.subscribe({"order_filled"}, name="b")

    delivered = await bus.publish("order_filled", "fill_event")
    assert delivered == 2

    kind_a, ev_a = await sub_a.queue.get()
    kind_b, ev_b = await sub_b.queue.get()
    assert ev_a == ev_b == "fill_event"


async def test_signal_namespace_works() -> None:
    bus = EventBus()
    sub = bus.subscribe({"signal:risk_state"}, name="risk_listener")

    await bus.publish("signal:risk_state", "HALTED")
    kind, ev = await sub.queue.get()
    assert kind == "signal:risk_state"
    assert ev == "HALTED"


async def test_unknown_event_kind_raises_on_subscribe() -> None:
    bus = EventBus()
    with pytest.raises(UnknownEventKindError):
        bus.subscribe({"bars"}, name="typo")  # 'bars' instead of 'bar'


async def test_unknown_event_kind_raises_on_publish() -> None:
    bus = EventBus()
    with pytest.raises(UnknownEventKindError):
        await bus.publish("bars", {})


async def test_signal_without_name_rejected() -> None:
    bus = EventBus()
    with pytest.raises(UnknownEventKindError):
        bus.subscribe({"signal:"}, name="empty_signal_name")


async def test_unsubscribe_stops_delivery() -> None:
    bus = EventBus()
    sub = bus.subscribe({"bar"}, name="temp")
    bus.unsubscribe(sub)

    delivered = await bus.publish("bar", "lost")
    assert delivered == 0


async def test_empty_subscription_set_rejected() -> None:
    bus = EventBus()
    with pytest.raises(ValueError, match="at least one"):
        bus.subscribe(set(), name="nothing")


async def test_close_blocks_new_subscriptions() -> None:
    bus = EventBus()
    bus.close()
    with pytest.raises(RuntimeError, match="closed"):
        bus.subscribe({"bar"}, name="late")


async def test_close_blocks_publish() -> None:
    bus = EventBus()
    sub = bus.subscribe({"bar"}, name="x")
    bus.close()

    delivered = await bus.publish("bar", {})
    assert delivered == 0
    assert sub.queue.empty()


async def test_subscriber_count() -> None:
    bus = EventBus()
    assert bus.subscriber_count == 0
    bus.subscribe({"bar"}, name="a")
    bus.subscribe({"tick"}, name="b")
    assert bus.subscriber_count == 2
