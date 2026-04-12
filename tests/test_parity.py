"""Unit tests for autopilot.parity — the fill-matching heuristic used to
compare two engines' output.

Pure-Python tests, no I/O, run in milliseconds.
"""

from __future__ import annotations

from kairos.parity import (
    QUANTITY_TOLERANCE_PCT,
    FillRecord,
    MatchReport,
    match_fills,
)


def _fill(
    strategy: str = "hybrid_scalping",
    symbol: str = "BTCUSDC",
    side: str = "BUY",
    qty: float = 0.1,
    price: float = 50000.0,
    ts_ns: int = 1_700_000_000_000_000_000,
    role: str = "entry",
    pnl: float | None = None,
) -> FillRecord:
    return FillRecord(
        strategy_name=strategy,
        symbol=symbol,
        side=side,
        quantity=qty,
        price=price,
        ts_ns=ts_ns,
        role=role,
        realized_pnl=pnl,
    )


# ─── Matching heuristic ─────────────────────────────────────


def test_perfect_match() -> None:
    base = [_fill()]
    cand = [_fill()]
    report = match_fills(base, cand)
    assert len(report.matched) == 1
    assert report.extra_baseline == []
    assert report.extra_candidate == []
    assert report.matched[0].time_delta_seconds == 0
    assert report.matched[0].price_divergence_pct == 0


def test_extra_baseline_fill_is_unmatched() -> None:
    ts = 1_700_000_000_000_000_000
    base = [_fill(ts_ns=ts), _fill(ts_ns=ts + 60_000_000_000)]
    cand = [_fill(ts_ns=ts)]
    report = match_fills(base, cand)
    assert len(report.matched) == 1
    assert len(report.extra_baseline) == 1
    assert report.extra_candidate == []


def test_extra_candidate_fill_is_unmatched() -> None:
    ts = 1_700_000_000_000_000_000
    base = [_fill(ts_ns=ts)]
    cand = [_fill(ts_ns=ts), _fill(ts_ns=ts + 60_000_000_000)]
    report = match_fills(base, cand)
    assert len(report.matched) == 1
    assert report.extra_baseline == []
    assert len(report.extra_candidate) == 1


def test_different_strategy_does_not_match() -> None:
    base = [_fill(strategy="hybrid_scalping")]
    cand = [_fill(strategy="dca_signal")]
    report = match_fills(base, cand)
    assert report.matched == []
    assert len(report.extra_baseline) == 1
    assert len(report.extra_candidate) == 1


def test_different_side_does_not_match() -> None:
    base = [_fill(side="BUY")]
    cand = [_fill(side="SELL")]
    report = match_fills(base, cand)
    assert report.matched == []


def test_quantity_within_tolerance_matches() -> None:
    base = [_fill(qty=0.1)]
    cand = [_fill(qty=0.1 * (1 + QUANTITY_TOLERANCE_PCT * 0.9))]
    report = match_fills(base, cand)
    assert len(report.matched) == 1


def test_quantity_beyond_tolerance_does_not_match() -> None:
    base = [_fill(qty=0.1)]
    cand = [_fill(qty=0.1 * 1.02)]   # 2% off
    report = match_fills(base, cand)
    assert report.matched == []


def test_time_within_tolerance_matches() -> None:
    ts = 1_700_000_000_000_000_000
    base = [_fill(ts_ns=ts)]
    cand = [_fill(ts_ns=ts + 300 * 1_000_000_000)]  # 300s offset
    report = match_fills(base, cand, time_tolerance_seconds=900)
    assert len(report.matched) == 1
    assert 299 <= report.matched[0].time_delta_seconds <= 301


def test_time_beyond_tolerance_does_not_match() -> None:
    ts = 1_700_000_000_000_000_000
    base = [_fill(ts_ns=ts)]
    cand = [_fill(ts_ns=ts + 1000 * 1_000_000_000)]
    report = match_fills(base, cand, time_tolerance_seconds=900)
    assert report.matched == []


def test_price_divergence_within_tolerance_matches() -> None:
    base = [_fill(price=50_000.0)]
    cand = [_fill(price=50_000.0 * 1.0005)]   # 0.05%
    report = match_fills(base, cand)
    assert len(report.matched) == 1


def test_price_divergence_beyond_tolerance_does_not_match() -> None:
    base = [_fill(price=50_000.0)]
    cand = [_fill(price=50_000.0 * 1.002)]    # 0.2% > 0.1% tol
    report = match_fills(base, cand)
    assert report.matched == []


def test_greedy_pairs_temporally_closest_candidate() -> None:
    ts = 1_700_000_000_000_000_000
    base = [_fill(ts_ns=ts)]
    cand = [
        _fill(ts_ns=ts + 500 * 1_000_000_000),
        _fill(ts_ns=ts + 50 * 1_000_000_000),   # should win
        _fill(ts_ns=ts + 850 * 1_000_000_000),
    ]
    report = match_fills(base, cand)
    assert len(report.matched) == 1
    assert 49 <= report.matched[0].time_delta_seconds <= 51
    assert len(report.extra_candidate) == 2


def test_entry_only_matching_ignores_sl_tp() -> None:
    """SL and TP fills are bracket children — skipped by default."""
    base = [_fill(role="entry"), _fill(role="sl")]
    cand = [_fill(role="entry")]
    report = match_fills(base, cand)
    assert len(report.matched) == 1
    # SL wasn't considered for matching; not an "extra" either
    assert report.extra_baseline == []


def test_match_all_roles_when_entry_only_false() -> None:
    base = [_fill(role="entry"), _fill(role="sl", ts_ns=1_700_000_000_000_000_001)]
    cand = [_fill(role="entry"), _fill(role="sl", ts_ns=1_700_000_000_000_000_001)]
    report = match_fills(base, cand, match_entry_only=False)
    assert len(report.matched) == 2


# ─── Verdict logic ─────────────────────────────────────


def test_verdict_pass_when_all_matched_and_no_pnl_drift() -> None:
    base = [_fill(pnl=10.0)]
    cand = [_fill(pnl=10.0)]
    report = match_fills(base, cand)
    assert report.verdict == "PASS"


def test_verdict_warn_when_pnl_drifts_moderately() -> None:
    # Matched pair but candidate PnL is 1% lower
    base = [_fill(pnl=100.0)]
    cand = [_fill(pnl=99.0)]
    report = match_fills(base, cand)
    assert report.verdict == "WARN"


def test_verdict_fail_when_pnl_drift_large() -> None:
    base = [_fill(pnl=100.0)]
    cand = [_fill(pnl=95.0)]       # 5% divergence
    report = match_fills(base, cand)
    assert report.verdict == "FAIL"


def test_verdict_fail_when_meaningful_extra_candidate() -> None:
    """Extra candidate fill with >= 1 USDC notional → FAIL."""
    report = MatchReport(
        baseline_fills=[],
        candidate_fills=[_fill(qty=0.01, price=50_000)],   # 500 USDC notional
        matched=[],
        extra_baseline=[],
        extra_candidate=[_fill(qty=0.01, price=50_000)],
    )
    assert report.verdict == "FAIL"


def test_verdict_warn_when_tiny_extra_fill() -> None:
    """Dust extra (< 1 USDC notional) → WARN only."""
    tiny = _fill(qty=0.00001, price=50_000)   # 0.5 USDC
    report = MatchReport(
        baseline_fills=[],
        candidate_fills=[tiny],
        matched=[],
        extra_baseline=[],
        extra_candidate=[tiny],
    )
    assert report.verdict == "WARN"


def test_pnl_divergence_handles_zero_baseline() -> None:
    report = MatchReport(
        baseline_fills=[_fill(pnl=0.0)],
        candidate_fills=[_fill(pnl=0.0)],
    )
    assert report.pnl_divergence_pct == 0.0

    report = MatchReport(
        baseline_fills=[_fill(pnl=0.0)],
        candidate_fills=[_fill(pnl=5.0)],
    )
    assert report.pnl_divergence_pct == 100.0


def test_as_dict_serializable() -> None:
    base = [_fill(pnl=10.0)]
    cand = [_fill(pnl=10.0)]
    d = match_fills(base, cand).as_dict()
    assert d["verdict"] == "PASS"
    assert d["matched"] == 1
    assert d["baseline_fill_count"] == 1
    assert d["candidate_fill_count"] == 1
