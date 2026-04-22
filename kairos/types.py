"""Core data types — Bar, Order, Fill, Position."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP_MARKET = "STOP_MARKET"
    STOP_LIMIT = "STOP_LIMIT"


class OrderStatus(Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class TimeInForce(Enum):
    GTC = "GTC"  # Good til cancelled
    IOC = "IOC"  # Immediate or cancel
    FOK = "FOK"  # Fill or kill


class TradingState(Enum):
    ACTIVE = "active"
    REDUCING = "reducing"
    HALTED = "halted"


@dataclass
class Bar:
    """OHLCV bar."""
    symbol: str
    timeframe: str
    timestamp: int  # milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Instrument:
    """Exchange instrument specification."""
    symbol: str
    base: str          # e.g., "BTC"
    quote: str         # e.g., "USDC"
    min_qty: float
    max_qty: float
    qty_step: float
    min_notional: float
    price_precision: int
    qty_precision: int


@dataclass
class Order:
    """Trading order."""
    id: str
    symbol: str
    side: OrderSide
    type: OrderType
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    time_in_force: TimeInForce = TimeInForce.GTC
    status: OrderStatus = OrderStatus.PENDING
    post_only: bool = False
    reduce_only: bool = False
    # Bracket linkage
    parent_id: str | None = None
    linked_ids: list[str] = field(default_factory=list)


@dataclass
class Fill:
    """Order execution fill.

    The ``explanation`` field is a v0.2 design hook for the v0.3 "why card"
    feature (vision §6). v0.2 ships it as ``None``; v0.3 fills it with a
    structured record (indicators at entry, regime detected, win
    probability estimate, counterfactual). Strategies and actors that
    want to surface a "why" can read this field today and get an empty
    dict; tomorrow the same code lights up.
    """
    order_id: str
    trade_id: str
    symbol: str
    side: OrderSide
    price: float
    quantity: float
    commission: float
    timestamp: int
    # v0.2 design hook — see vision.md §6 (Why card)
    explanation: dict | None = None
    bracket_id: str | None = None
    strategy_name: str | None = None


@dataclass
class Position:
    """Open position (netting mode)."""
    symbol: str
    quantity: float = 0.0
    avg_entry: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.quantity > 0

    @property
    def side(self) -> str:
        return "LONG" if self.quantity > 0 else "FLAT"


@dataclass
class Balance:
    """Account balance for a currency."""
    currency: str
    free: float
    locked: float

    @property
    def total(self) -> float:
        return self.free + self.locked


@dataclass(frozen=True)
class StrategySignal:
    """A strategy's decision to act, agnostic to how it gets executed.

    Strategies publish ``StrategySignal`` instances on the engine's
    ``"strategy_signal"`` event topic. In single-tenant setups, the same
    strategy also calls its adapter directly (dual-write); a downstream
    consumer (signal dispatcher in multi-tenant setups) can translate
    the signal into per-user orders using per-user capital and keys.

    The field set was designed by the Trading Autopilot pivot-to-shared-
    engine-saas change — see that change's ``design.md`` (D1) for
    rationale.

    Actions currently understood by downstream consumers:
      - ``"buy_bracket"``  — open long with atomic SL + TP
      - ``"sell_all"``     — close full open position
      - ``"grid_entry"``   — post a single grid LIMIT order
      - ``"grid_cancel"``  — cancel a specific grid LIMIT by id
    """

    strategy: str
    symbol: str
    action: str
    pct_of_capital: float = 0.0
    sl_atr_mult: float | None = None
    tp_atr_mult: float | None = None
    price_level: float | None = None
    order_ref: str | None = None
    reason: str = ""
    ts_ns: int = 0
    # The (strategy, symbol, timeframe) tuple uniquely identifies a
    # strategy instance in the Autonomous Strategy Lifecycle. Prior to
    # v0.4.1 the timeframe was missing, which forced downstream ASL
    # gates to fall back to a (strategy, symbol) match that collapsed
    # divergent lifecycle states across timeframes. See openspec
    # archive 2026-04-22-saas-runtime-contracts D34#3.
    timeframe: str = ""
