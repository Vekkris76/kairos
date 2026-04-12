"""Fill matcher — pairs equivalent fills from two engines for parity checks.

Core algorithm (greedy O(n×m)):
    For each left fill, find the closest unmatched right fill satisfying the
    tolerance heuristic. Unpaired fills on either side are "extras" and
    contribute to the divergence verdict.

Heuristic (defaults, configurable):
    Same strategy, same symbol, same side
    Quantity within ±1%
    Time within ±N seconds (bar-type dependent — default 900s = 15min bars)
    Price within ±0.1%

Verdicts:
    PASS: zero extras, PnL divergence < 0.5%
    WARN: PnL divergence 0.5%–2%, or small/dust extras
    FAIL: PnL divergence > 2%, or meaningful unmatched fills

Typical usage:

    from autopilot.parity import FillRecord, match_fills

    report = match_fills(
        baseline=fills_from_engine_a,
        candidate=fills_from_engine_b,
    )
    if report.verdict == "PASS":
        # safe to cut over
        ...
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Verdict = Literal["PASS", "WARN", "FAIL"]


# Tolerances — tune per-project if needed.
DEFAULT_TIME_TOLERANCE_SECONDS = 900   # 15 minutes — default for 15m bars
QUANTITY_TOLERANCE_PCT = 0.01          # ±1%
PRICE_TOLERANCE_PCT = 0.001            # ±0.1%


@dataclass
class FillRecord:
    """Normalized fill shape used by the matcher. Adapters translate engine-
    specific fill types into this."""
    strategy_name: str
    symbol: str
    side: str                      # "BUY" | "SELL"
    quantity: float
    price: float
    ts_ns: int                     # nanosecond timestamp (UTC)
    role: str = "entry"            # "entry" | "sl" | "tp"
    realized_pnl: float | None = None

    def notional(self) -> float:
        return self.quantity * self.price


@dataclass
class FillMatch:
    """A paired fill from baseline and candidate."""
    baseline: FillRecord
    candidate: FillRecord
    time_delta_seconds: float
    price_divergence_pct: float   # 0-100 scale


@dataclass
class MatchReport:
    """Outcome of a parity comparison between two fill streams."""
    baseline_fills: list[FillRecord] = field(default_factory=list)
    candidate_fills: list[FillRecord] = field(default_factory=list)
    matched: list[FillMatch] = field(default_factory=list)
    extra_baseline: list[FillRecord] = field(default_factory=list)
    extra_candidate: list[FillRecord] = field(default_factory=list)

    @property
    def baseline_pnl(self) -> float:
        return sum((f.realized_pnl or 0) for f in self.baseline_fills)

    @property
    def candidate_pnl(self) -> float:
        return sum((f.realized_pnl or 0) for f in self.candidate_fills)

    @property
    def pnl_divergence_pct(self) -> float:
        """Percentage divergence of candidate vs baseline PnL."""
        if abs(self.baseline_pnl) < 1e-9:
            return 0.0 if abs(self.candidate_pnl) < 1e-9 else 100.0
        return (self.candidate_pnl - self.baseline_pnl) / abs(self.baseline_pnl) * 100.0

    @property
    def verdict(self) -> Verdict:
        """Classify the run. Dust extras (notional < 1) count as WARN, not FAIL."""
        extras = self.extra_baseline + self.extra_candidate
        critical_extras = [f for f in extras if f.notional() >= 1.0]
        if critical_extras:
            return "FAIL"
        if extras:
            return "WARN"
        div = abs(self.pnl_divergence_pct)
        if div > 2.0:
            return "FAIL"
        if div > 0.5:
            return "WARN"
        return "PASS"

    @property
    def max_time_delta_seconds(self) -> float:
        return max((m.time_delta_seconds for m in self.matched), default=0.0)

    @property
    def max_price_divergence_pct(self) -> float:
        return max((m.price_divergence_pct for m in self.matched), default=0.0)

    def as_dict(self) -> dict:
        """Serializable summary for reports/logs."""
        return {
            "baseline_fill_count": len(self.baseline_fills),
            "candidate_fill_count": len(self.candidate_fills),
            "matched": len(self.matched),
            "extra_baseline": len(self.extra_baseline),
            "extra_candidate": len(self.extra_candidate),
            "baseline_pnl": round(self.baseline_pnl, 6),
            "candidate_pnl": round(self.candidate_pnl, 6),
            "pnl_divergence_pct": round(self.pnl_divergence_pct, 4),
            "max_time_delta_seconds": round(self.max_time_delta_seconds, 2),
            "max_price_divergence_pct": round(self.max_price_divergence_pct, 4),
            "verdict": self.verdict,
        }


def match_fills(
    baseline: list[FillRecord],
    candidate: list[FillRecord],
    time_tolerance_seconds: float = DEFAULT_TIME_TOLERANCE_SECONDS,
    quantity_tolerance_pct: float = QUANTITY_TOLERANCE_PCT,
    price_tolerance_pct: float = PRICE_TOLERANCE_PCT,
    match_entry_only: bool = True,
) -> MatchReport:
    """Pair baseline fills to candidate fills and produce a parity report.

    Parameters
    ----------
    baseline:
        The "ground-truth" fill stream (e.g. production engine).
    candidate:
        The stream being evaluated (e.g. new engine version).
    time_tolerance_seconds:
        Max seconds of time drift allowed between matched fills.
    quantity_tolerance_pct:
        Relative quantity tolerance as a fraction (0.01 = 1%).
    price_tolerance_pct:
        Relative price tolerance as a fraction (0.001 = 0.1%).
    match_entry_only:
        If True, only match fills with role='entry' — SL/TP fills are bracket
        children and matched implicitly by virtue of pairing the entry.

    Returns
    -------
    MatchReport with matched pairs, extras on both sides, and a verdict.
    """
    if match_entry_only:
        base_for_match = [f for f in baseline if f.role == "entry"]
        cand_for_match = [f for f in candidate if f.role == "entry"]
    else:
        base_for_match = list(baseline)
        cand_for_match = list(candidate)

    matches: list[FillMatch] = []
    used_candidate: set[int] = set()
    extra_baseline: list[FillRecord] = []

    for bf in base_for_match:
        best: FillMatch | None = None
        best_idx = -1
        best_score = float("inf")

        for i, cf in enumerate(cand_for_match):
            if i in used_candidate:
                continue

            # Hard gates — wrong on ANY of these → no match at all
            if bf.strategy_name != cf.strategy_name:
                continue
            if bf.symbol != cf.symbol:
                continue
            if bf.side != cf.side:
                continue
            if bf.quantity <= 0 or cf.quantity <= 0:
                continue
            if bf.price <= 0:
                continue

            qty_delta = abs(bf.quantity - cf.quantity) / bf.quantity
            if qty_delta > quantity_tolerance_pct:
                continue

            time_delta = abs(bf.ts_ns - cf.ts_ns) / 1e9
            if time_delta > time_tolerance_seconds:
                continue

            price_div = abs(bf.price - cf.price) / bf.price
            if price_div > price_tolerance_pct:
                continue

            # Scoring: prefer closer time, then closer price
            score = time_delta + price_div * 1000
            if score < best_score:
                best_score = score
                best = FillMatch(
                    baseline=bf,
                    candidate=cf,
                    time_delta_seconds=time_delta,
                    price_divergence_pct=price_div * 100,
                )
                best_idx = i

        if best is None:
            extra_baseline.append(bf)
        else:
            matches.append(best)
            used_candidate.add(best_idx)

    extra_candidate = [
        f for i, f in enumerate(cand_for_match) if i not in used_candidate
    ]

    return MatchReport(
        baseline_fills=list(baseline),
        candidate_fills=list(candidate),
        matched=matches,
        extra_baseline=extra_baseline,
        extra_candidate=extra_candidate,
    )
