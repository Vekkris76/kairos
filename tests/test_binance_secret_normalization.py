"""Tests for ``_normalize_binance_secret`` — HMAC vs Ed25519 detection.

Binance Spot accepts two key types. CCXT auto-detects Ed25519 only when
the secret is wrapped in PEM envelope, so we normalize at construction
time. This test suite covers every shape the caller might pass in.
"""

from __future__ import annotations

import base64

import pytest

from kairos.exchanges.binance import _normalize_binance_secret


# ── HMAC (pass-through) ─────────────────────────────────────────


def test_hmac_alphanumeric_secret_unchanged() -> None:
    """A typical 64-char HMAC secret must pass through untouched."""
    hmac_secret = "A1B2C3D4E5F6" + "x" * 52   # 64 chars, alphanumeric
    assert _normalize_binance_secret(hmac_secret) == hmac_secret


def test_hmac_secret_with_leading_trailing_whitespace_is_stripped() -> None:
    hmac_secret = "abcDEF123" + "x" * 55
    assert _normalize_binance_secret(f"  {hmac_secret}\n") == hmac_secret


# ── Ed25519 DER Base64 → PEM wrap ───────────────────────────────


def _make_ed25519_base64() -> str:
    """Build a realistic Base64-encoded PKCS#8 DER Ed25519 secret.

    Starts with the magic header ``0x30 0x2e 0x02`` so the Base64 encoding
    begins with ``MC4C``. Uses a synthetic 32-byte seed so no real key
    material is in the repo.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
    )

    key = Ed25519PrivateKey.from_private_bytes(b"\x00" * 32)
    der = key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return base64.b64encode(der).decode()


def test_ed25519_raw_base64_gets_wrapped_in_pem() -> None:
    raw = _make_ed25519_base64()
    assert raw.startswith("MC4C")

    wrapped = _normalize_binance_secret(raw)
    assert wrapped.startswith("-----BEGIN PRIVATE KEY-----")
    assert wrapped.endswith("-----END PRIVATE KEY-----")
    # The original key content must be preserved between the markers
    body = wrapped.replace("-----BEGIN PRIVATE KEY-----\n", "")
    body = body.replace("\n-----END PRIVATE KEY-----", "")
    assert body == raw


def test_ed25519_already_in_pem_is_left_alone() -> None:
    raw = _make_ed25519_base64()
    pem = f"-----BEGIN PRIVATE KEY-----\n{raw}\n-----END PRIVATE KEY-----"
    assert _normalize_binance_secret(pem) == pem


@pytest.mark.parametrize("prefix", ["MC4C", "MFMC"])
def test_ed25519_both_prefix_variants_detected(prefix: str) -> None:
    """Some Binance exports use the MFMC prefix (different DER tag)."""
    synthetic = prefix + ("A" * 60)   # not a real key, but prefix test only
    out = _normalize_binance_secret(synthetic)
    assert out.startswith("-----BEGIN PRIVATE KEY-----")
    assert synthetic in out


def test_ed25519_round_trip_loads_via_cryptography() -> None:
    """End-to-end: synthetic key → normalized → decode → sign."""
    from cryptography.hazmat.primitives.serialization import (
        load_pem_private_key,
    )

    raw = _make_ed25519_base64()
    pem = _normalize_binance_secret(raw)
    key = load_pem_private_key(pem.encode(), password=None)
    # Signing any message must succeed — that's what Binance's auth relies on
    sig = key.sign(b"timestamp=1700000000000&recvWindow=5000")
    assert len(sig) == 64   # Ed25519 signatures are always 64 bytes
