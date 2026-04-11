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
    """Order execution fill."""
    order_id: str
    trade_id: str
    symbol: str
    side: OrderSide
    price: float
    quantity: float
    commission: float
    timestamp: int


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
