"""ParameterProvider — pluggable strategy-parameter source.

This is a §7 design hook for v0.3 differentiator §3 (continual tuning).

In v0.2: Strategies hardcode their parameters, OR accept a ``StaticProvider``
constructed from a profile JSON. The hook exists so the surface is stable.

In v0.3: A ``BayesianProvider`` will plug in here. It maintains a posterior
over each parameter and updates after every trade. A strategy never knows
the difference — it just calls ``self.params.get("rsi_threshold", 50.0)``
and gets either the static value (v0.2) or the current Bayesian posterior
mean (v0.3).

Why a Provider rather than a dict? Because the v0.3 implementation needs to
*observe* every parameter access (for shadowing) and *react* to fills. A
plain dict can't do that.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ParameterProvider(ABC):
    """Source of strategy parameters.

    Subclasses include:
        StaticProvider     — wraps a dict (default in v0.2)
        BayesianProvider   — continual tuning (lands v0.3)
        ABTestProvider     — deterministic A/B splits (future utility)
    """

    @abstractmethod
    def get(self, name: str, default: Any = None) -> Any:
        """Retrieve a parameter value by name."""

    def __getitem__(self, name: str) -> Any:
        v = self.get(name)
        if v is None:
            raise KeyError(name)
        return v


class StaticProvider(ParameterProvider):
    """Trivial baseline: returns values from a static dict.

    Default for v0.2. Loaded from profile JSONs by the LiveEngine.
    """

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self._params: dict[str, Any] = dict(params or {})

    def get(self, name: str, default: Any = None) -> Any:
        return self._params.get(name, default)

    def set(self, name: str, value: Any) -> None:
        """Allow runtime override (mostly for tests / admin tools)."""
        self._params[name] = value

    def all(self) -> dict[str, Any]:
        """Return a snapshot of all parameters (read-only)."""
        return dict(self._params)
