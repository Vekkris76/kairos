"""Kairos execution — bracket orders, OCO, reconciliation, execution policies.

Public surface:
    BracketManager, Bracket, BracketSubmissionError
    Reconciler, ReconciliationReport
    ExecutionPolicy, ExecutionContext, ExecutionDecision, StaticPolicy
"""

from __future__ import annotations

from kairos.execution.bracket_manager import (
    Bracket,
    BracketManager,
    BracketSubmissionError,
)
from kairos.execution.policy import (
    ExecutionContext,
    ExecutionDecision,
    ExecutionPolicy,
    StaticPolicy,
)
from kairos.execution.reconciler import Reconciler, ReconciliationReport

__all__ = [
    "Bracket",
    "BracketManager",
    "BracketSubmissionError",
    "ExecutionContext",
    "ExecutionDecision",
    "ExecutionPolicy",
    "Reconciler",
    "ReconciliationReport",
    "StaticPolicy",
]
