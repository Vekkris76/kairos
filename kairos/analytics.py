"""Performance Analytics — calculate trading metrics from trade history.

Provides Sharpe ratio, Sortino ratio, profit factor, and more.
Works with both live trades and backtest results.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class PerformanceMetrics:
    """Comprehensive trading performance metrics."""

    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    avg_trade: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    profit_factor: float = 0.0
    win_rate: float = 0.0
    avg_bars_held: float = 0.0
    total_commission: float = 0.0

    def __str__(self) -> str:
        return (
            f"═══ Performance Analytics ═══\n"
            f"Trades:         {self.total_trades} "
            f"(W:{self.wins} L:{self.losses})\n"
            f"Win Rate:       {self.win_rate:.1%}\n"
            f"Total PnL:      {self.total_pnl:+.2f}\n"
            f"Profit Factor:  {self.profit_factor:.2f}\n"
            f"Avg Trade:      {self.avg_trade:+.2f}\n"
            f"Avg Win:        {self.avg_win:+.2f}\n"
            f"Avg Loss:       {self.avg_loss:.2f}\n"
            f"Largest Win:    {self.largest_win:+.2f}\n"
            f"Largest Loss:   {self.largest_loss:.2f}\n"
            f"Max Drawdown:   {self.max_drawdown_pct:.2f}%\n"
            f"Sharpe Ratio:   {self.sharpe_ratio:.2f}\n"
            f"Sortino Ratio:  {self.sortino_ratio:.2f}\n"
            f"Commission:     {self.total_commission:.2f}\n"
        )


def calculate_metrics(
    trade_pnls: list[float],
    equity_curve: list[float] | None = None,
    commissions: list[float] | None = None,
    bars_held: list[int] | None = None,
) -> PerformanceMetrics:
    """Calculate performance metrics from a list of trade PnLs.

    Args:
        trade_pnls: List of PnL per trade (positive = win, negative = loss)
        equity_curve: Optional equity curve for drawdown calculation
        commissions: Optional commission per trade
        bars_held: Optional bars held per trade
    """
    m = PerformanceMetrics()

    if not trade_pnls:
        return m

    m.total_trades = len(trade_pnls)
    wins = [p for p in trade_pnls if p > 0]
    losses = [p for p in trade_pnls if p <= 0]

    m.wins = len(wins)
    m.losses = len(losses)
    m.win_rate = m.wins / m.total_trades if m.total_trades > 0 else 0

    m.total_pnl = sum(trade_pnls)
    m.gross_profit = sum(wins) if wins else 0
    m.gross_loss = abs(sum(losses)) if losses else 0

    m.avg_trade = m.total_pnl / m.total_trades
    m.avg_win = m.gross_profit / m.wins if m.wins > 0 else 0
    m.avg_loss = -m.gross_loss / m.losses if m.losses > 0 else 0
    m.largest_win = max(wins) if wins else 0
    m.largest_loss = min(losses) if losses else 0

    m.profit_factor = (
        m.gross_profit / m.gross_loss if m.gross_loss > 0 else float("inf")
    )

    # Sharpe Ratio (annualized, assuming daily trades)
    if len(trade_pnls) > 1:
        mean_return = sum(trade_pnls) / len(trade_pnls)
        std_return = math.sqrt(
            sum((p - mean_return) ** 2 for p in trade_pnls) / (len(trade_pnls) - 1)
        )
        if std_return > 0:
            m.sharpe_ratio = (mean_return / std_return) * math.sqrt(252)

    # Sortino Ratio (only downside deviation)
    if len(trade_pnls) > 1:
        mean_return = sum(trade_pnls) / len(trade_pnls)
        downside = [min(p, 0) for p in trade_pnls]
        downside_dev = math.sqrt(
            sum(d ** 2 for d in downside) / len(downside)
        )
        if downside_dev > 0:
            m.sortino_ratio = (mean_return / downside_dev) * math.sqrt(252)

    # Max Drawdown
    if equity_curve and len(equity_curve) > 1:
        peak = equity_curve[0]
        max_dd = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak * 100 if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        m.max_drawdown_pct = max_dd

    # Commissions
    if commissions:
        m.total_commission = sum(commissions)

    # Average bars held
    if bars_held:
        m.avg_bars_held = sum(bars_held) / len(bars_held)

    return m
