"""DEPRECATED: autopilot-engine has been renamed to kairos-engine.

This package is now a thin alias that re-exports from `kairos`. It will
stop being maintained on 2026-10-12 (six months after the rename).

Migration:
    pip uninstall autopilot-engine
    pip install kairos-engine

In your code:
    from autopilot import Engine, Strategy   ->  from kairos import Engine, Strategy
"""

import warnings

warnings.warn(
    "The 'autopilot-engine' package has been renamed to 'kairos-engine'. "
    "Please migrate before 2026-10-12: `pip install kairos-engine` and "
    "replace `from autopilot import X` with `from kairos import X`. "
    "See https://github.com/Vekkris76/kairos for details.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export the public Kairos surface so existing code keeps working
# during the deprecation window.
from kairos import (  # noqa: E402, F401
    BacktestEngine,
    DataCatalog,
    Engine,
    Strategy,
)
from kairos import __version__ as _kairos_version  # noqa: E402

__version__ = "0.1.99"
__all__ = ["BacktestEngine", "DataCatalog", "Engine", "Strategy", "__version__"]
