"""Tests for kairos.runtime.parameters (StaticProvider design hook)."""

from __future__ import annotations

import pytest

from kairos.runtime.parameters import ParameterProvider, StaticProvider


def test_static_provider_get_returns_value() -> None:
    p = StaticProvider({"rsi_threshold": 50.0, "ema_fast": 8})
    assert p.get("rsi_threshold") == 50.0
    assert p.get("ema_fast") == 8


def test_static_provider_get_returns_default_for_missing() -> None:
    p = StaticProvider({"x": 1})
    assert p.get("missing", default=42) == 42
    assert p.get("missing") is None


def test_static_provider_indexer_works_for_present_keys() -> None:
    p = StaticProvider({"x": 1})
    assert p["x"] == 1


def test_static_provider_indexer_raises_on_missing() -> None:
    p = StaticProvider({"x": 1})
    with pytest.raises(KeyError, match="missing"):
        _ = p["missing"]


def test_static_provider_set_overrides_value() -> None:
    p = StaticProvider({"x": 1})
    p.set("x", 999)
    assert p.get("x") == 999


def test_static_provider_all_returns_snapshot() -> None:
    p = StaticProvider({"a": 1, "b": 2})
    snapshot = p.all()
    snapshot["c"] = 3  # mutating snapshot must not leak
    assert p.get("c") is None


def test_static_provider_empty_constructor() -> None:
    p = StaticProvider()
    assert p.get("anything") is None
    assert p.all() == {}


def test_static_provider_is_parameter_provider() -> None:
    p = StaticProvider()
    assert isinstance(p, ParameterProvider)
