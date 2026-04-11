# Autopilot Engine — Architecture

## Design Principles

1. **Simple over complex** — If it takes more than 10 lines to make a strategy, we failed
2. **Python-first** — No Rust, no Cython. Pure Python. Anyone can contribute
3. **Multi-strategy native** — Run N strategies simultaneously. Not an afterthought
4. **Crypto-focused** — We do crypto spot extremely well. Not stocks, not forex, not derivatives
5. **MIT licensed** — No restrictions. Fork it, sell it, do whatever

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Autopilot Engine                      │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │Strategy A│  │Strategy B│  │Strategy C│  ...         │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘             │
│       │              │              │                   │
│  ┌────▼──────────────▼──────────────▼────┐             │
│  │           Strategy Runner              │             │
│  │  (calls on_bar for each strategy)      │             │
│  └────────────────┬──────────────────────┘             │
│                   │                                     │
│  ┌────────────────▼──────────────────────┐             │
│  │           Event Bus                    │             │
│  │  (bars, fills, positions, signals)     │             │
│  └───┬────────┬───────────┬──────────────┘             │
│      │        │           │                             │
│  ┌───▼──┐ ┌──▼────┐ ┌───▼──────┐ ┌──────────┐        │
│  │ Data │ │Orders │ │Positions │ │   Risk   │        │
│  │ Feed │ │Manager│ │ Tracker  │ │Validator │        │
│  └───┬──┘ └──┬────┘ └──────────┘ └──────────┘        │
│      │       │                                         │
│  ┌───▼───────▼─────────────────────┐                  │
│  │      Exchange Adapter            │                  │
│  │  (Binance / Paper / Custom)      │                  │
│  └──────────────────────────────────┘                  │
└─────────────────────────────────────────────────────────┘
```

## Components

### 1. Engine (`autopilot/engine.py`)

The main entry point. Creates all components, manages lifecycle.

```python
engine = Engine(exchange="binance", api_key="...", api_secret="...")
engine.add(MyStrategy, symbol="BTCUSDC", timeframe="1h")
engine.add(MyStrategy, symbol="ETHUSDC", timeframe="15m")
engine.run()  # Blocks until stopped
```

Responsibilities:
- Initialize exchange adapter, data feed, order manager
- Register strategies and their subscriptions
- Run the main event loop
- Handle graceful shutdown (SIGTERM/SIGINT)

### 2. Strategy (`autopilot/strategy.py`)

Base class for all trading strategies. Users override `setup()` and `on_bar()`.

```python
class Strategy:
    # Indicator helpers
    def add_ema(period, name="") -> None
    def add_rsi(period=14) -> None
    def add_atr(period=14) -> None
    def add_bollinger(period=20, std=2.0) -> None
    def add_macd(fast=12, slow=26, signal=9) -> None

    # Indicator accessors (auto-scaled, no quirks)
    def ema(name) -> float
    def fast_ema() -> float
    def slow_ema() -> float
    def rsi() -> float          # Always 0-100
    def atr() -> float
    def bollinger() -> dict     # {upper, middle, lower}
    def macd() -> dict          # {macd, signal, histogram}

    # Order methods (with built-in validation)
    def buy(pct) -> bool                    # Market buy X% of balance
    def sell_all() -> bool                  # Market sell entire position
    def buy_limit(price, pct) -> str        # Limit buy, returns order_id
    def sell_limit(price, qty) -> str       # Limit sell
    def buy_bracket(pct, sl_atr, tp_atr) -> bool  # Entry + SL + TP
    def cancel(order_id) -> bool

    # Portfolio
    def free_balance(currency="USDC") -> float
    def has_position() -> bool
    def position_qty() -> float
    def position_pnl() -> float
    def position_pnl_pct() -> float

    # Lifecycle (override these)
    def setup(self) -> None       # Declare indicators
    def on_bar(self, bar) -> None # Called every bar
    def on_fill(self, fill) -> None  # Called on order fill
    def on_stop(self) -> None     # Cleanup
```

### 3. Exchange Adapter (`autopilot/exchanges/`)

Abstraction layer over exchange APIs. Interface:

```python
class ExchangeAdapter:
    async def connect() -> None
    async def disconnect() -> None

    # Market data
    async def subscribe_bars(symbol, timeframe) -> None
    async def get_historical_bars(symbol, timeframe, start, end) -> list[Bar]

    # Orders
    async def submit_order(order: Order) -> OrderResult
    async def cancel_order(order_id: str) -> bool
    async def get_open_orders() -> list[Order]

    # Account
    async def get_balances() -> dict[str, Balance]
    async def get_positions() -> list[Position]

    # Instrument info
    async def get_instrument(symbol) -> Instrument
```

Implementations:
- `BinanceAdapter` — Real Binance Spot (CCXT + WebSocket)
- `PaperAdapter` — Simulated exchange for testing
- Custom adapters via the interface

### 4. Order Manager (`autopilot/orders/manager.py`)

Handles order lifecycle: created → submitted → accepted → filled/cancelled.

- Tracks all orders by ID
- Manages bracket orders (OCO: SL cancels when TP fills, vice versa)
- Handles partial fills
- Detects duplicate fills (by trade_id)
- Emits events: OrderSubmitted, OrderFilled, OrderCancelled, OrderRejected

### 5. Data Feed (`autopilot/data/feed.py`)

Manages bar subscriptions and delivers data to strategies.

- Subscribes to exchange WebSocket streams
- Aggregates ticks into OHLCV bars
- Maintains a rolling cache of recent bars per symbol/timeframe
- Delivers bars to all subscribed strategies simultaneously

### 6. Position Tracker (`autopilot/orders/position.py`)

Tracks open positions per instrument (netting mode).

- Calculates average entry price across multiple fills
- Calculates realized PnL on partial/full closes
- Calculates unrealized PnL from last market price
- Emits events: PositionOpened, PositionChanged, PositionClosed

### 7. Risk Validator (`autopilot/risk/validator.py`)

Pre-trade validation before every order submission:

- Free balance sufficient
- Quantity within instrument min/max
- Notional above minimum
- Order rate within throttle limits
- Trading state allows new orders (not HALTED)

### 8. Indicators (`autopilot/indicators/`)

Pure Python implementations. Each indicator:
- Has `update(value)` method
- Has `value` property (current value)
- Has `initialized` property (enough data received)
- Is stateful (maintains internal buffers)

### 9. Backtest Engine (`autopilot/backtest/`)

Replays historical bars through the same engine:

```python
from autopilot import BacktestEngine

bt = BacktestEngine(initial_balance=1000)
bt.load_data("BTCUSDC", "1h", start="2025-01-01", end="2025-12-31")
bt.add(MyStrategy, symbol="BTCUSDC", timeframe="1h")
results = bt.run()

print(results.total_pnl)
print(results.win_rate)
print(results.max_drawdown)
results.plot()  # Equity curve
```

## Data Types

### Bar
```python
@dataclass
class Bar:
    symbol: str
    timeframe: str
    timestamp: int      # milliseconds
    open: float
    high: float
    low: float
    close: float
    volume: float
```

### Order
```python
@dataclass
class Order:
    id: str
    symbol: str
    side: OrderSide     # BUY / SELL
    type: OrderType     # MARKET / LIMIT / STOP_MARKET / STOP_LIMIT
    quantity: float
    price: float | None
    stop_price: float | None
    time_in_force: str  # GTC / IOC / FOK
    status: OrderStatus # PENDING / SUBMITTED / FILLED / CANCELLED
    post_only: bool
    reduce_only: bool
```

### Fill
```python
@dataclass
class Fill:
    order_id: str
    trade_id: str
    symbol: str
    side: OrderSide
    price: float
    quantity: float
    commission: float
    timestamp: int
```

### Position
```python
@dataclass
class Position:
    symbol: str
    side: PositionSide   # LONG / FLAT
    quantity: float
    avg_entry: float
    unrealized_pnl: float
    realized_pnl: float
```

## Event System

Components communicate via an async event bus:

```
BarReceived → Strategy.on_bar() → engine.buy()
    → RiskValidator.check() → ExchangeAdapter.submit_order()
        → OrderSubmitted → OrderFilled → PositionTracker.update()
            → Strategy.on_fill()
```

Events:
- `BarReceived(bar)` — new bar from data feed
- `OrderSubmitted(order)` — order sent to exchange
- `OrderFilled(fill)` — order executed
- `OrderCancelled(order_id)` — order cancelled
- `OrderRejected(order_id, reason)` — order rejected
- `PositionOpened(position)` — new position
- `PositionClosed(position, pnl)` — position closed
- `RiskAlert(state, message)` — risk state change

## Configuration

Minimal config via constructor arguments + optional YAML:

```yaml
# autopilot.yaml (optional)
exchange: binance
base_currency: USDC
risk:
  max_drawdown_pct: 15
  max_daily_loss_pct: 3
  max_orders_per_minute: 30
logging:
  level: INFO
  file: autopilot.log
```

## Directory Structure

```
autopilot/
├── __init__.py          # Public API: Engine, Strategy, BacktestEngine
├── engine.py            # Main engine + event loop
├── strategy.py          # Strategy base class
├── config.py            # Configuration loading
├── events.py            # Event types + bus
├── types.py             # Bar, Order, Fill, Position dataclasses
├── exchanges/
│   ├── __init__.py
│   ├── base.py          # ExchangeAdapter interface
│   ├── binance.py       # Binance Spot (CCXT + WS)
│   └── paper.py         # Paper trading simulator
├── orders/
│   ├── __init__.py
│   ├── manager.py       # Order lifecycle management
│   └── position.py      # Position tracking + PnL
├── data/
│   ├── __init__.py
│   ├── feed.py          # Bar subscriptions + delivery
│   ├── cache.py         # In-memory bar cache
│   └── catalog.py       # Parquet data storage
├── indicators/
│   ├── __init__.py
│   ├── ema.py
│   ├── rsi.py
│   ├── atr.py
│   ├── bollinger.py
│   ├── macd.py
│   ├── sma.py
│   ├── stochastic.py
│   ├── vwap.py
│   ├── obv.py
│   ├── donchian.py
│   ├── roc.py
│   ├── adx.py
│   ├── hma.py
│   ├── regression.py
│   └── aroon.py
├── risk/
│   ├── __init__.py
│   ├── validator.py     # Pre-trade checks
│   └── protection.py    # Drawdown/daily loss states
└── backtest/
    ├── __init__.py
    ├── engine.py        # Backtest runner
    ├── simulator.py     # Simulated fill engine
    └── results.py       # Performance metrics + plots
```
