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
    def __init__(
        self,
        lookback: int = 24,
        breakout_buffer: float = 2.0,
        min_impulse: float = 7.5,
        min_ema_distance: float = 4.0,
        max_ema_crosses: int = 4,
        min_recent_range: float = 18.0,
    ) -> None:
        self.lookback = lookback
        self.breakout_buffer = breakout_buffer
        self.min_impulse = min_impulse
        self.min_ema_distance = min_ema_distance
        self.max_ema_crosses = max_ema_crosses
        self.min_recent_range = min_recent_range

    @staticmethod
    def ema(values: list[float], period: int) -> float:
        if not values:
            return 0.0
        multiplier = 2 / (period + 1)
        ema_value = values[0]
        for value in values[1:]:
            ema_value = (value - ema_value) * multiplier + ema_value
        return ema_value

    @staticmethod
    def count_ema_crosses(closes: list[float], ema_value: float) -> int:
        crosses = 0
        previous_side = 0
        for close in closes:
            side = 1 if close > ema_value else -1 if close < ema_value else 0
            if previous_side and side and side != previous_side:
                crosses += 1
            if side:
                previous_side = side
        return crosses

    def signal(self, candles: list[Candle]) -> Signal:
        if len(candles) < max(self.lookback + 10, 80):
            return "HOLD"

        closes = [c.close for c in candles]
        highs = [c.high for c in candles]
        lows = [c.low for c in candles]

        current = candles[-1]
        previous = candles[-2]
        recent_high = max(highs[-self.lookback - 3 : -3])
        recent_low = min(lows[-self.lookback - 3 : -3])
        recent_range = recent_high - recent_low

        ema_fast = self.ema(closes[-50:], 10)
        ema_slow = self.ema(closes[-80:], 30)
        ema_distance = abs(ema_fast - ema_slow)
        impulse = abs(previous.close - candles[-6].close)
        crosses = self.count_ema_crosses(closes[-30:], ema_slow)

        # Chop / no-trade zone: avoid flat or messy markets.
        if ema_distance < self.min_ema_distance:
            return "HOLD"
        if crosses > self.max_ema_crosses:
            return "HOLD"
        if recent_range < self.min_recent_range:
            return "HOLD"
        if impulse < self.min_impulse:
            return "HOLD"

        buy_breakout = previous.close > recent_high + self.breakout_buffer
        buy_pullback = current.low <= recent_high and current.close > recent_high and current.close > current.open
        buy_trend = ema_fast > ema_slow and current.close > ema_fast

        sell_breakout = previous.close < recent_low - self.breakout_buffer
        sell_pullback = current.high >= recent_low and current.close < recent_low and current.close < current.open
        sell_trend = ema_fast < ema_slow and current.close < ema_fast

        if buy_trend and buy_breakout and buy_pullback:
            return "BUY"
        if sell_trend and sell_breakout and sell_pullback:
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

    for index in range(max(lookback + 10, 80), len(candles) - 1):
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
        consecutive_losses = consecutive_losses + 1 if trade.pnl < 0 else 0
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
    parser.add_argument("--lookback", type=int, default=24)
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
