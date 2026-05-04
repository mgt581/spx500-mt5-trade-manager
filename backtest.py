"""
Simple backtester for the SPX500 pullback strategy.

This uses simulated candles by default so it works on Mac without MetaTrader 5.
It is for strategy development only, not financial advice.
"""

from __future__ import annotations

import argparse
import math
import random
from dataclasses import dataclass
from typing import Literal

Signal = Literal["BUY", "SELL", "HOLD"]


@dataclass
class Candle:
    open: float
    high: float
    low: float
    close: float


@dataclass
class Trade:
    side: Signal
    entry: float
    stop_loss: float
    take_profit: float
    result: str
    pnl: float


class PullbackStrategy:
    def __init__(self, lookback: int = 20) -> None:
        self.lookback = lookback

    def signal(self, candles: list[Candle]) -> Signal:
        if len(candles) < self.lookback + 5:
            return "HOLD"

        closes = [c.close for c in candles]
        recent = closes[-self.lookback - 1 : -1]
        current = closes[-1]
        previous = closes[-2]
        average = sum(recent) / len(recent)
        recent_high = max(recent)
        recent_low = min(recent)

        if previous > recent_high and current < previous and current > average:
            return "BUY"
        if previous < recent_low and current > previous and current < average:
            return "SELL"
        return "HOLD"


def generate_simulated_candles(count: int, start_price: float = 5000.0) -> list[Candle]:
    candles: list[Candle] = []
    price = start_price

    for index in range(count):
        trend = index * 0.015
        wave = math.sin(index / 11) * 18
        noise = random.uniform(-8, 8)
        close = start_price + trend + wave + noise
        open_price = price
        high = max(open_price, close) + random.uniform(1, 7)
        low = min(open_price, close) - random.uniform(1, 7)
        candles.append(Candle(open=open_price, high=high, low=low, close=close))
        price = close

    return candles


def run_backtest(
    candles: list[Candle],
    stop_loss_points: float,
    take_profit_points: float,
    point: float,
    max_trades: int,
) -> list[Trade]:
    strategy = PullbackStrategy()
    trades: list[Trade] = []

    for index in range(30, len(candles) - 1):
        if len(trades) >= max_trades:
            break

        history = candles[: index + 1]
        signal = strategy.signal(history)
        if signal == "HOLD":
            continue

        entry = candles[index].close
        future = candles[index + 1]

        if signal == "BUY":
            sl = entry - stop_loss_points * point
            tp = entry + take_profit_points * point
            if future.low <= sl:
                trades.append(Trade(signal, entry, sl, tp, "LOSS", -stop_loss_points))
            elif future.high >= tp:
                trades.append(Trade(signal, entry, sl, tp, "WIN", take_profit_points))
            else:
                pnl = (future.close - entry) / point
                trades.append(Trade(signal, entry, sl, tp, "OPEN_CANDLE_CLOSE", pnl))
        else:
            sl = entry + stop_loss_points * point
            tp = entry - take_profit_points * point
            if future.high >= sl:
                trades.append(Trade(signal, entry, sl, tp, "LOSS", -stop_loss_points))
            elif future.low <= tp:
                trades.append(Trade(signal, entry, sl, tp, "WIN", take_profit_points))
            else:
                pnl = (entry - future.close) / point
                trades.append(Trade(signal, entry, sl, tp, "OPEN_CANDLE_CLOSE", pnl))

    return trades


def print_report(trades: list[Trade]) -> None:
    total = len(trades)
    wins = sum(1 for trade in trades if trade.pnl > 0)
    losses = sum(1 for trade in trades if trade.pnl < 0)
    pnl = sum(trade.pnl for trade in trades)
    win_rate = (wins / total * 100) if total else 0

    print("\nBacktest report")
    print("---------------")
    print(f"Trades:   {total}")
    print(f"Wins:     {wins}")
    print(f"Losses:   {losses}")
    print(f"Win rate: {win_rate:.2f}%")
    print(f"PnL pts:  {pnl:.2f}")

    if trades:
        print("\nLast 5 trades")
        for trade in trades[-5:]:
            print(
                f"{trade.side} entry={trade.entry:.2f} sl={trade.stop_loss:.2f} "
                f"tp={trade.take_profit:.2f} result={trade.result} pnl={trade.pnl:.2f}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a simulated backtest.")
    parser.add_argument("--candles", type=int, default=1000)
    parser.add_argument("--sl", type=float, default=250)
    parser.add_argument("--tp", type=float, default=500)
    parser.add_argument("--point", type=float, default=0.01)
    parser.add_argument("--max-trades", type=int, default=100)
    args = parser.parse_args()

    candles = generate_simulated_candles(args.candles)
    trades = run_backtest(candles, args.sl, args.tp, args.point, args.max_trades)
    print_report(trades)


if __name__ == "__main__":
    main()
