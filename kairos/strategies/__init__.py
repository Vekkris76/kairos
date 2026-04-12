"""Kairos strategies — base classes for trading strategies.

Two flavors:
- ``Strategy`` (v0.1, in kairos.strategy): synchronous, used by the
  paper-trading ``Engine`` for simple bots and backtests.
- ``LiveStrategy`` (v0.2.1+, here): Actor-shaped, used by ``LiveEngine``
  for production live trading. Provides indicator declaration helpers,
  cache reads, and order-submission shortcuts mapped to BracketManager.

Most users want ``LiveStrategy``. The v0.1 ``Strategy`` stays for
backward compatibility and lightweight prototyping.
"""

from __future__ import annotations

from kairos.strategies.live import LiveStrategy

__all__ = ["LiveStrategy"]
