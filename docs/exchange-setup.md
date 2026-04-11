# Exchange Setup

## Binance Spot

### 1. Create API Keys

1. Go to [Binance API Management](https://www.binance.com/en/my/settings/api-management)
2. Click **Create API** → choose **System generated**
3. Name it "Autopilot Engine"
4. **Enable**: Spot Trading
5. **Disable**: Withdrawals, Futures, Margin (not needed)
6. Copy your **API Key** and **Secret Key**

> **Security**: Never enable withdrawal permissions. The bot only needs trading access.

### 2. Configure the Engine

```python
from autopilot import Engine

engine = Engine(
    exchange="binance",
    api_key="your_api_key_here",
    api_secret="your_api_secret_here",
    base_currency="USDC",
)
```

Or use environment variables:

```python
import os

engine = Engine(
    exchange="binance",
    api_key=os.environ["BINANCE_API_KEY"],
    api_secret=os.environ["BINANCE_API_SECRET"],
)
```

### 3. Supported Pairs

Any Binance Spot pair works. Common USDC pairs:

| Pair | Symbol |
|------|--------|
| Bitcoin | `BTCUSDC` |
| Ethereum | `ETHUSDC` |
| Solana | `SOLUSDC` |
| XRP | `XRPUSDC` |
| Dogecoin | `DOGEUSDC` |

### 4. Timeframes

| Code | Interval |
|------|----------|
| `1m` | 1 minute |
| `5m` | 5 minutes |
| `15m` | 15 minutes |
| `1h` | 1 hour |
| `4h` | 4 hours |
| `1d` | 1 day |

## Paper Trading

For development and testing — no real money:

```python
engine = Engine(
    exchange="paper",
    initial_balance=1000,  # Simulated USDC
)
```

Paper mode:
- Fills instantly at market price
- Simulates 0.1% fees
- Limit/stop orders fill when price touches
- No exchange connection needed
