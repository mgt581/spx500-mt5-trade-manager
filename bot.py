"""
SPX500 MT5 Trade Manager

Default mode is DRY_RUN=True so the bot will NOT place real trades unless you
explicitly change the config. Use a demo account first.

Note for Mac users:
The official MetaTrader5 Python package is Windows-only. On Mac, run this bot
in simulated dry-run mode, or run live/demo MT5 execution from Windows/VPS.
"""

from __future__ import annotations

import csv
import math
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

try:
    import MetaTrader5 as mt5  # type: ignore
    MT5_AVAILABLE = True
except ModuleNotFoundError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False

Signal = Literal["BUY", "SELL", "HOLD"]
TIMEFRAME_M5 = 5


@dataclass(frozen=True)
class BotConfig:
    symbol: str = os.getenv("BOT_SYMBOL", "SPX500")
    timeframe: int = int(os.getenv("BOT_TIMEFRAME", str(getattr(mt5, "TIMEFRAME_M5", TIMEFRAME_M5))))
    candles: int = int(os.getenv("BOT_CANDLES", "120"))
    poll_seconds: int = int(os.getenv("BOT_POLL_SECONDS", "10"))
    dry_run: bool = os.getenv("BOT_DRY_RUN", "true").lower() == "true"
    simulate_data: bool = os.getenv("BOT_SIMULATE_DATA", "false").lower() == "true"
    risk_percent: float = float(os.getenv("BOT_RISK_PERCENT", "1.0"))
    max_trades_per_day: int = int(os.getenv("BOT_MAX_TRADES_PER_DAY", "3"))
    max_spread_points: float = float(os.getenv("BOT_MAX_SPREAD_POINTS", "50"))
    stop_loss_points: float = float(os.getenv("BOT_STOP_LOSS_POINTS", "250"))
    take_profit_points: float = float(os.getenv("BOT_TAKE_PROFIT_POINTS", "500"))
    magic_number: int = int(os.getenv("BOT_MAGIC_NUMBER", "581500"))
    log_file: str = os.getenv("BOT_LOG_FILE", "trades.csv")


class TradeLogger:
    def __init__(self, file_path: str) -> None:
        self.path = Path(file_path)
        if not self.path.exists():
            with self.path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow([
                    "timestamp",
                    "symbol",
                    "signal",
                    "price",
                    "volume",
                    "stop_loss",
                    "take_profit",
                    "dry_run",
                    "result",
                ])

    def write(self, row: list[object]) -> None:
        with self.path.open("a", newline="", encoding="utf-8") as file:
            csv.writer(file).writerow(row)


class PullbackStrategy:
    def __init__(self, lookback: int = 20) -> None:
        self.lookback = lookback

    def signal(self, rates: list[list[float]]) -> Signal:
        if len(rates) < self.lookback + 5:
            return "HOLD"

        closes = [float(candle[4]) for candle in rates]
        recent = closes[-self.lookback - 1 : -1]
        current = closes[-1]
        previous = closes[-2]
        average = sum(recent) / len(recent)
        recent_high = max(recent)
        recent_low = min(recent)

        broke_up = previous > recent_high
        pulled_back_uptrend = current < previous and current > average

        broke_down = previous < recent_low
        pulled_back_downtrend = current > previous and current < average

        if broke_up and pulled_back_uptrend:
            return "BUY"
        if broke_down and pulled_back_downtrend:
            return "SELL"
        return "HOLD"


class MT5TradeManager:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.logger = TradeLogger(config.log_file)
        self.trades_today = 0
        self.current_day = datetime.now().date()
        self.sim_price = 5000.0

    def connect(self) -> None:
        if self.config.simulate_data:
            print(f"Simulation mode | symbol={self.config.symbol} | dry_run={self.config.dry_run}")
            return

        if not MT5_AVAILABLE:
            raise RuntimeError(
                "MetaTrader5 Python package is not available on this machine. "
                "On Mac, set BOT_SIMULATE_DATA=true in .env for dry-run testing, "
                "or run MT5 execution on Windows/VPS."
            )

        if not mt5.initialize():
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        if not mt5.symbol_select(self.config.symbol, True):
            raise RuntimeError(f"Could not select symbol: {self.config.symbol}")
        print(f"Connected to MT5 | symbol={self.config.symbol} | dry_run={self.config.dry_run}")

    def shutdown(self) -> None:
        if MT5_AVAILABLE and not self.config.simulate_data:
            mt5.shutdown()

    def reset_daily_count_if_needed(self) -> None:
        today = datetime.now().date()
        if today != self.current_day:
            self.current_day = today
            self.trades_today = 0

    def get_rates(self) -> Optional[list[list[float]]]:
        if self.config.simulate_data:
            return self.get_simulated_rates()

        rates = mt5.copy_rates_from_pos(self.config.symbol, self.config.timeframe, 0, self.config.candles)
        if rates is None:
            print(f"No rates returned: {mt5.last_error()}")
            return None
        return rates.tolist()

    def get_simulated_rates(self) -> list[list[float]]:
        rows: list[list[float]] = []
        base_time = int(time.time()) - self.config.candles * 300
        for index in range(self.config.candles):
            wave = math.sin(index / 8) * 12
            noise = random.uniform(-3, 3)
            close = self.sim_price + wave + noise + index * 0.05
            open_price = close + random.uniform(-2, 2)
            high = max(open_price, close) + random.uniform(1, 5)
            low = min(open_price, close) - random.uniform(1, 5)
            rows.append([base_time + index * 300, open_price, high, low, close, 0, 0, 0])
        self.sim_price = rows[-1][4]
        return rows

    def spread_is_ok(self) -> bool:
        if self.config.simulate_data:
            return True

        tick = mt5.symbol_info_tick(self.config.symbol)
        info = mt5.symbol_info(self.config.symbol)
        if tick is None or info is None:
            return False
        spread_points = (tick.ask - tick.bid) / info.point
        if spread_points > self.config.max_spread_points:
            print(f"Spread too high: {spread_points:.1f} points")
            return False
        return True

    def calculate_volume(self) -> float:
        if self.config.simulate_data:
            return 0.01

        account = mt5.account_info()
        info = mt5.symbol_info(self.config.symbol)
        if account is None or info is None:
            return 0.01

        risk_cash = account.balance * (self.config.risk_percent / 100)
        estimated_loss_per_lot = max(self.config.stop_loss_points * info.point * 100, 1)
        volume = risk_cash / estimated_loss_per_lot

        min_volume = info.volume_min or 0.01
        max_volume = info.volume_max or 1.0
        step = info.volume_step or 0.01

        volume = max(min_volume, min(volume, max_volume))
        volume = round(volume / step) * step
        return round(volume, 2)

    def place_order(self, signal: Signal, rates: list[list[float]]) -> None:
        if signal == "HOLD":
            return

        self.reset_daily_count_if_needed()
        if self.trades_today >= self.config.max_trades_per_day:
            print("Daily trade limit reached")
            return
        if not self.spread_is_ok():
            return

        volume = self.calculate_volume()
        timestamp = datetime.now(timezone.utc).isoformat()

        if self.config.simulate_data:
            price = float(rates[-1][4])
            point = 0.01
        else:
            tick = mt5.symbol_info_tick(self.config.symbol)
            info = mt5.symbol_info(self.config.symbol)
            if tick is None or info is None:
                print("Missing tick or symbol info")
                return
            price = tick.ask if signal == "BUY" else tick.bid
            point = info.point

        if signal == "BUY":
            sl = price - self.config.stop_loss_points * point
            tp = price + self.config.take_profit_points * point
        else:
            sl = price + self.config.stop_loss_points * point
            tp = price - self.config.take_profit_points * point

        if self.config.dry_run or self.config.simulate_data:
            result_text = "DRY_RUN_ONLY" if self.config.dry_run else "SIMULATION_ONLY"
            print(f"{result_text} {signal}: price={price:.2f}, volume={volume}, sl={sl:.2f}, tp={tp:.2f}")
        else:
            order_type = mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL
            request: dict[str, Any] = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": self.config.symbol,
                "volume": volume,
                "type": order_type,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": 20,
                "magic": self.config.magic_number,
                "comment": "SPX500 pullback bot",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            result_text = str(result)
            print(f"LIVE ORDER RESULT: {result_text}")

        self.trades_today += 1
        self.logger.write([timestamp, self.config.symbol, signal, price, volume, sl, tp, self.config.dry_run, result_text])


def main() -> None:
    config = BotConfig()
    strategy = PullbackStrategy()
    manager = MT5TradeManager(config)

    try:
        manager.connect()
        while True:
            rates = manager.get_rates()
            if rates:
                signal = strategy.signal(rates)
                print(f"{datetime.now().strftime('%H:%M:%S')} signal={signal}")
                manager.place_order(signal, rates)
            time.sleep(config.poll_seconds)
    except KeyboardInterrupt:
        print("Bot stopped by user")
    finally:
        manager.shutdown()


if __name__ == "__main__":
    main()
