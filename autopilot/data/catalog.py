"""Parquet Data Catalog — persistent bar storage for backtesting.

Save and load historical bar data in Parquet format (fast, compact).

Usage:
    catalog = DataCatalog("./data")
    catalog.write_bars("BTCUSDC", "1h", bars)
    bars = catalog.read_bars("BTCUSDC", "1h", start_ms, end_ms)
    print(catalog.list_instruments())
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from autopilot.types import Bar

logger = logging.getLogger("autopilot.catalog")


class DataCatalog:
    """File-based bar data storage using Parquet format."""

    def __init__(self, path: str = "./data") -> None:
        self._root = Path(path)
        self._root.mkdir(parents=True, exist_ok=True)

    def write_bars(self, symbol: str, timeframe: str, bars: list[Bar]) -> int:
        """Write bars to Parquet file. Returns number of bars written."""
        if not bars:
            return 0

        try:
            import pyarrow as pa
            import pyarrow.parquet as pq
        except ImportError:
            # Fallback to JSON if pyarrow not installed
            return self._write_json(symbol, timeframe, bars)

        table = pa.table({
            "timestamp": [b.timestamp for b in bars],
            "open": [b.open for b in bars],
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
            "volume": [b.volume for b in bars],
        })

        path = self._bar_path(symbol, timeframe, "parquet")
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(table, str(path), compression="snappy")

        logger.info(f"Wrote {len(bars)} bars to {path}")
        return len(bars)

    def read_bars(
        self,
        symbol: str,
        timeframe: str,
        start_ms: int = 0,
        end_ms: int = 0,
    ) -> list[Bar]:
        """Read bars from Parquet (or JSON fallback)."""
        parquet_path = self._bar_path(symbol, timeframe, "parquet")
        json_path = self._bar_path(symbol, timeframe, "json")

        if parquet_path.exists():
            return self._read_parquet(symbol, timeframe, parquet_path, start_ms, end_ms)
        elif json_path.exists():
            return self._read_json(symbol, timeframe, json_path, start_ms, end_ms)

        return []

    def list_instruments(self) -> list[dict]:
        """List all available instruments with bar counts."""
        result = []
        bars_dir = self._root / "bars"
        if not bars_dir.exists():
            return result

        for symbol_dir in sorted(bars_dir.iterdir()):
            if not symbol_dir.is_dir():
                continue
            for tf_file in sorted(symbol_dir.iterdir()):
                suffix = tf_file.suffix
                if suffix not in (".parquet", ".json"):
                    continue
                timeframe = tf_file.stem
                bars = self.read_bars(symbol_dir.name, timeframe)
                if bars:
                    result.append({
                        "symbol": symbol_dir.name,
                        "timeframe": timeframe,
                        "bars": len(bars),
                        "start": bars[0].timestamp,
                        "end": bars[-1].timestamp,
                        "format": suffix[1:],
                    })
        return result

    def download_binance(
        self, symbol: str, timeframe: str, days: int = 90,
    ) -> list[Bar]:
        """Download bars from Binance and save to catalog."""
        import time as _time
        from urllib.request import urlopen

        logger.info(f"Downloading {symbol} {timeframe} ({days} days)...")
        end_ms = int(_time.time() * 1000)
        start_ms = end_ms - (days * 86400 * 1000)
        all_bars: list[Bar] = []

        while start_ms < end_ms:
            url = (
                f"https://api.binance.com/api/v3/klines"
                f"?symbol={symbol}&interval={timeframe}"
                f"&startTime={start_ms}&limit=1000"
            )
            with urlopen(url) as resp:
                klines = json.loads(resp.read())
            if not klines:
                break
            for k in klines:
                all_bars.append(Bar(
                    symbol=symbol, timeframe=timeframe,
                    timestamp=k[0],
                    open=float(k[1]), high=float(k[2]),
                    low=float(k[3]), close=float(k[4]),
                    volume=float(k[5]),
                ))
            start_ms = klines[-1][6] + 1
            _time.sleep(0.2)

        self.write_bars(symbol, timeframe, all_bars)
        logger.info(f"Downloaded and saved {len(all_bars)} bars")
        return all_bars

    # ── Internal ──────────────────────────────────────

    def _bar_path(self, symbol: str, timeframe: str, ext: str) -> Path:
        return self._root / "bars" / symbol / f"{timeframe}.{ext}"

    def _read_parquet(
        self, symbol: str, timeframe: str, path: Path,
        start_ms: int, end_ms: int,
    ) -> list[Bar]:
        import pyarrow.parquet as pq

        table = pq.read_table(str(path))
        bars = []
        ts = table.column("timestamp").to_pylist()
        opens = table.column("open").to_pylist()
        highs = table.column("high").to_pylist()
        lows = table.column("low").to_pylist()
        closes = table.column("close").to_pylist()
        volumes = table.column("volume").to_pylist()

        for i in range(len(ts)):
            if start_ms and ts[i] < start_ms:
                continue
            if end_ms and ts[i] > end_ms:
                break
            bars.append(Bar(
                symbol=symbol, timeframe=timeframe,
                timestamp=ts[i], open=opens[i], high=highs[i],
                low=lows[i], close=closes[i], volume=volumes[i],
            ))
        return bars

    def _write_json(self, symbol: str, timeframe: str, bars: list[Bar]) -> int:
        """Fallback: write bars as JSON (no pyarrow needed)."""
        path = self._bar_path(symbol, timeframe, "json")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [
            {
                "t": b.timestamp, "o": b.open, "h": b.high,
                "l": b.low, "c": b.close, "v": b.volume,
            }
            for b in bars
        ]
        path.write_text(json.dumps(data))
        logger.info(f"Wrote {len(bars)} bars to {path} (JSON)")
        return len(bars)

    def _read_json(
        self, symbol: str, timeframe: str, path: Path,
        start_ms: int, end_ms: int,
    ) -> list[Bar]:
        data = json.loads(path.read_text())
        bars = []
        for d in data:
            ts = d["t"]
            if start_ms and ts < start_ms:
                continue
            if end_ms and ts > end_ms:
                break
            bars.append(Bar(
                symbol=symbol, timeframe=timeframe,
                timestamp=ts, open=d["o"], high=d["h"],
                low=d["l"], close=d["c"], volume=d["v"],
            ))
        return bars
