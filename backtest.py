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
    def __init__(self, lookback: int = 30, breakout_buffer: float = 3.0, min_trend_slope: float = 0.25, min_range: float = 18.0) -> None:
        self.lookback = lookback
        self.breakout_buffer = breakout_buffer
        self.min_trend_slope = min_trend_slope
        self.min_range = min_range

    def signal(self, candles: list[Candle]) -> Signal:
        if len(candles) < self.lookback + 10:
            return "HOLD"

        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]

        recent_closes = closes[-self.lookback - 2 : -2]
        prior_closes = closes[-self.lookback - 8 : -8]
        current = closes[-1]
        previous = closes[-2]
        current_low = lows[-1]
        current_high = highs[-1]
        recent_average = sum(recent_closes) / len(recent_closes)
        prior_average = sum(prior_closes) / len(prior_closes)
        recent_high = max(highs[-self.lookback - 2 : -2])
        recent_low = min(lows[-self.lookback - 2 : -2])
        recent_range = recent_high - recent_low
        trend_slope = recent_average - prior_average

        if recent_range < self.min_range:
            return "HOLD"

        uptrend = trend_slope > self.min_trend_slope
        downtrend = trend_slope < -self.min_trend_slope

        broke_up_recently = previous > recent_high + self.breakout_buffer
        pullback_depth_ok = current_low <= recent_high and current > recent_average
        bullish_rejection = current > candles[-1].open

        broke_down_recently = previous < recent_low - self.breakout_buffer
        pullback_depth_ok_short = current_high >= recent_low and current < recent_average
        bearish_rejection = current < candles[-1].open

        if uptrend and broke_up_recently and pullback_depth_ok and bullish_rejection:
            return "BUY"
        if downtrend and broke_down_recently and pullback_depth_ok_short and bearish_rejection:
            return "SELL"
        return "HOLD"


def generate_simulated_candles(count: int, start_price: float = 5000.0, seed: int = 581) -> list[Candle]:
    random.seed(seed)
    candles: list[Candle] = []
    price = start_price
    trend = 0.35

    for index in range(count):
        if index % 240 == 0 and index > 0:
            trend *= -1

        impulse = 0.0
        if index % 80 in {0, 1, 2, 3}:
            impulse = trend * 12
        elif index % 80 in {4, 5, 6}:
            impulse = -trend * 4

        wave = math.sin(index / 17) * 2
        noise = random.uniform(-2.5, 2.5)
        close = price + trend + impulse + wave * 0.05 + noise
        open_price = price
        high = max(open_price, close) + random.uniform(0.8, 4)
        low = min(open_price, close) - random.uniform(0.8, 4)
        candles.append(Candle(open=open_price, high=high, low=low, close=close))
        price = close

    return candles


def run_backtest(
    candles: list[Candle],
    stop_loss_points: float,
    take_profit_points: float,
    point: float,
    max_trades: int,
    lookback: int,
    max_consecutive_losses: int,
    loss_pause_candles: int,
) -> list[Trade]:
    strategy = PullbackStrategy(lookback=lookback)
    trades: list[Trade] = []
    cooldown_until = 0
    consecutive_losses = 0

    for index in range(max(lookback + 10, 30), len(candles) - 1):
        if index < cooldown_until:
            continue
        if len(trades) >= max_trades:
            break

        history = candles[: index + 1]
        signal = strategy.signal(history)
        if signal == "HOLD":
            continue

        entry = candles[index].close
        future_window = candles[index + 1 : min(index + 25, len(candles))]
        trade: Trade | None = None

        if signal == "BUY":
            sl = entry - stop_loss_points * point
            tp = entry + take_profit_points * point
            for future in future_window:
                if future.low <= sl:
                    trade = Trade(signal, entry, sl, tp, "LOSS", -stop_loss_points)
                    break
                if future.high >= tp:
                    trade = Trade(signal, entry, sl, tp, "WIN", take_profit_points)
                    break
            if trade is None and future_window:
                pnl = (future_window[-1].close - entry) / point
                trade = Trade(signal, entry, sl, tp, "TIME_EXIT", pnl)
        else:
            sl = entry + stop_loss_points * point
            tp = entry - take_profit_points * point
            for future in future_window:
                if future.high >= sl:
                    trade = Trade(signal, entry, sl, tp, "LOSS", -stop_loss_points)
                    break
                if future.low <= tp:
                    trade = Trade(signal, entry, sl, tp, "WIN", take_profit_points)
                    break
            if trade is None and future_window:
                pnl = (entry - future_window[-1].close) / point
                trade = Trade(signal, entry, sl, tp, "TIME_EXIT", pnl)

        if trade is None:
            continue

        trades.append(trade)
        if trade.pnl < 0:
            consecutive_losses += 1
        else:
            consecutive_losses = 0

        cooldown_until = index + 20
        if consecutive_losses >= max_consecutive_losses:
            cooldown_until = max(cooldown_until, index + loss_pause_candles)
            consecutive_losses = 0

    return trades


def print_report(trades: list[Trade]) -> None:
    total = len(trades)
    wins = sum(1 for trade in trades if trade.pnl > 0)
    losses = sum(1 for trade in trades if trade.pnl < 0)
    pnl = sum(trade.pnl for trade in trades)
    win_rate = (wins / total * 100) if total else 0

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for trade in trades:
        equity += trade.pnl
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)

    avg_win = sum(trade.pnl for trade in trades if trade.pnl > 0) / wins if wins else 0
    avg_loss = sum(trade.pnl for trade in trades if trade.pnl < 0) / losses if losses else 0
    gross_win = sum(trade.pnl for trade in trades if trade.pnl > 0)
    gross_loss = abs(sum(trade.pnl for trade in trades if trade.pnl < 0))
    profit_factor = gross_win / gross_loss if gross_loss else 0

    print("\nBacktest report")
    print("---------------")
    print(f"Trades:        {total}")
    print(f"Wins:          {wins}")
    print(f"Losses:        {losses}")
    print(f"Win rate:      {win_rate:.2f}%")
    print(f"PnL pts:       {pnl:.2f}")
    print(f"Max drawdown:  {max_drawdown:.2f}")
    print(f"Avg win:       {avg_win:.2f}")
    print(f"Avg loss:      {avg_loss:.2f}")
    print(f"Profit factor: {profit_factor:.2f}")

    if trades:
        print("\nLast 5 trades")
        for trade in trades[-5:]:
            print(
                f"{trade.side} entry={trade.entry:.2f} sl={trade.stop_loss:.2f} "
                f"tp={trade.take_profit:.2f} result={trade.result} pnl={trade.pnl:.2f}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a simulated backtest.")
    parser.add_argument("--candles", type=int, default=3000)
    parser.add_argument("--sl", type=float, default=300)
    parser.add_argument("--tp", type=float, default=450)
    parser.add_argument("--point", type=float, default=0.01)
    parser.add_argument("--max-trades", type=int, default=50)
    parser.add_argument("--lookback", type=int, default=30)
    parser.add_argument("--seed", type=int, default=581)
    parser.add_argument("--max-consecutive-losses", type=int, default=2)
    parser.add_argument("--loss-pause-candles", type=int, default=120)
    args = parser.parse_args()

    candles = generate_simulated_candles(args.candles, seed=args.seed)
    trades = run_backtest(
        candles,
        args.sl,
        args.tp,
        args.point,
        args.max_trades,
        args.lookback,
        args.max_consecutive_losses,
        args.loss_pause_candles,
    )
    print_report(trades)


if __name__ == "__main__":
    main()
