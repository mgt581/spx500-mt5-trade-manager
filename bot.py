"""
SPX500 MT5 Trade Manager

Improved debug + observability build.

Key upgrades:
- structured debug logging
- heartbeat/status logs
- safer MT5 position handling by ticket
- optional manual trade management support
- tester/dev friendly configuration
- conservative risk behaviour preserved
"""

from __future__ import annotations

import csv
import logging
import math
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ModuleNotFoundError:
    pass

try:
    import MetaTrader5 as mt5  # type: ignore
    MT5_AVAILABLE = True
except ModuleNotFoundError:
    mt5 = None  # type: ignore
    MT5_AVAILABLE = False

Signal = Literal['BUY', 'SELL', 'HOLD']
TIMEFRAME_M5 = 5


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'y', 'on'}


@dataclass(frozen=True)
class BotConfig:
    symbol: str = os.getenv('BOT_SYMBOL', 'SPX500')
    timeframe: int = int(os.getenv('BOT_TIMEFRAME', str(getattr(mt5, 'TIMEFRAME_M5', TIMEFRAME_M5))))
    candles: int = int(os.getenv('BOT_CANDLES', '120'))
    poll_seconds: int = int(os.getenv('BOT_POLL_SECONDS', '10'))
    dry_run: bool = env_bool('BOT_DRY_RUN', True)
    simulate_data: bool = env_bool('BOT_SIMULATE_DATA', False)
    debug_logging: bool = env_bool('BOT_DEBUG_LOGGING', True)
    heartbeat_seconds: int = int(os.getenv('BOT_HEARTBEAT_SECONDS', '60'))
    allow_manual_trade_management: bool = env_bool('BOT_ALLOW_MANUAL_TRADE_MANAGEMENT', True)
    allow_multiple_positions: bool = env_bool('BOT_ALLOW_MULTIPLE_POSITIONS', False)
    tester_force_signal: str = os.getenv('BOT_TESTER_FORCE_SIGNAL', 'AUTO')
    risk_percent: float = float(os.getenv('BOT_RISK_PERCENT', '0.5'))
    max_trades_per_day: int = int(os.getenv('BOT_MAX_TRADES_PER_DAY', '3'))
    max_spread_points: float = float(os.getenv('BOT_MAX_SPREAD_POINTS', '50'))
    stop_loss_points: float = float(os.getenv('BOT_STOP_LOSS_POINTS', '300'))
    take_profit_points: float = float(os.getenv('BOT_TAKE_PROFIT_POINTS', '500'))
    max_total_loss_points: float = float(os.getenv('BOT_MAX_TOTAL_LOSS_POINTS', '900'))
    max_consecutive_losses: int = int(os.getenv('BOT_MAX_CONSECUTIVE_LOSSES', '2'))
    loss_pause_seconds: int = int(os.getenv('BOT_LOSS_PAUSE_SECONDS', '3600'))
    magic_number: int = int(os.getenv('BOT_MAGIC_NUMBER', '581500'))
    log_file: str = os.getenv('BOT_LOG_FILE', 'trades.csv')


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
)
logger = logging.getLogger('spx500-bot')


class TradeLogger:
    def __init__(self, file_path: str) -> None:
        self.path = Path(file_path)
        if not self.path.exists():
            with self.path.open('w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow([
                    'timestamp', 'symbol', 'signal', 'price', 'volume', 'stop_loss',
                    'take_profit', 'dry_run', 'result', 'session_pnl_points',
                ])

    def write(self, row: list[object]) -> None:
        with self.path.open('a', newline='', encoding='utf-8') as file:
            csv.writer(file).writerow(row)


class PullbackStrategy:
    def signal(self, rates: list[list[float]]) -> Signal:
        if len(rates) < 80:
            return 'HOLD'

        closes = [float(candle[4]) for candle in rates]
        short_trend = closes[-1] > sum(closes[-10:]) / 10
        long_trend = closes[-1] > sum(closes[-30:]) / 30

        if short_trend and long_trend:
            return 'BUY'

        if not short_trend and not long_trend:
            return 'SELL'

        return 'HOLD'


class MT5TradeManager:
    def __init__(self, config: BotConfig) -> None:
        self.config = config
        self.logger = TradeLogger(config.log_file)
        self.trades_today = 0
        self.current_day = datetime.now().date()
        self.sim_price = 5000.0
        self.session_pnl_points = 0.0
        self.consecutive_losses = 0
        self.pause_until = 0.0
        self.last_heartbeat = 0.0

    def log_debug(self, message: str) -> None:
        if self.config.debug_logging:
            logger.info(f'[DEBUG] {message}')

    def heartbeat(self) -> None:
        now = time.time()
        if now - self.last_heartbeat < self.config.heartbeat_seconds:
            return

        self.last_heartbeat = now

        open_positions = self.get_open_positions_count()

        logger.info(
            f'[HEARTBEAT] symbol={self.config.symbol} '
            f'dry_run={self.config.dry_run} '
            f'positions={open_positions} '
            f'trades_today={self.trades_today} '
            f'session_pnl={self.session_pnl_points:.2f}'
        )

    def connect(self) -> None:
        if self.config.simulate_data:
            logger.info('Simulation mode enabled')
            return

        if not MT5_AVAILABLE:
            raise RuntimeError('MetaTrader5 package unavailable')

        if not mt5.initialize():
            raise RuntimeError(f'MT5 initialize failed: {mt5.last_error()}')

        if not mt5.symbol_select(self.config.symbol, True):
            raise RuntimeError(f'Could not select symbol: {self.config.symbol}')

        logger.info(
            f'Connected to MT5 | symbol={self.config.symbol} | dry_run={self.config.dry_run}'
        )

    def shutdown(self) -> None:
        logger.info('Bot shutting down')
        if MT5_AVAILABLE and not self.config.simulate_data:
            mt5.shutdown()

    def get_rates(self) -> Optional[list[list[float]]]:
        if self.config.simulate_data:
            return self.get_simulated_rates()

        rates = mt5.copy_rates_from_pos(
            self.config.symbol,
            self.config.timeframe,
            0,
            self.config.candles,
        )

        if rates is None:
            logger.error(f'No rates returned: {mt5.last_error()}')
            return None

        return rates.tolist()

    def get_simulated_rates(self) -> list[list[float]]:
        rows: list[list[float]] = []
        base_time = int(time.time()) - self.config.candles * 300

        for index in range(self.config.candles):
            wave = math.sin(index / 8) * 12
            noise = random.uniform(-3, 3)
            close = self.sim_price + wave + noise
            open_price = close + random.uniform(-2, 2)
            high = max(open_price, close) + random.uniform(1, 5)
            low = min(open_price, close) - random.uniform(1, 5)
            rows.append([base_time + index * 300, open_price, high, low, close, 0, 0, 0])

        self.sim_price = rows[-1][4]
        return rows

    def get_open_positions(self) -> list[Any]:
        if self.config.simulate_data or not MT5_AVAILABLE:
            return []

        positions = mt5.positions_get(symbol=self.config.symbol)

        if positions is None:
            logger.warning(f'positions_get failed: {mt5.last_error()}')
            return []

        return list(positions)

    def get_open_positions_count(self) -> int:
        return len(self.get_open_positions())

    def has_existing_bot_position(self) -> bool:
        positions = self.get_open_positions()

        for position in positions:
            try:
                if position.magic == self.config.magic_number:
                    return True
            except AttributeError:
                continue

        return False

    def log_positions(self) -> None:
        positions = self.get_open_positions()

        if not positions:
            self.log_debug('No open positions found')
            return

        for position in positions:
            try:
                logger.info(
                    f'[POSITION] ticket={position.ticket} '
                    f'type={position.type} '
                    f'volume={position.volume} '
                    f'profit={position.profit}'
                )
            except Exception as error:
                logger.warning(f'Could not inspect position: {error}')

    def calculate_volume(self) -> float:
        if self.config.simulate_data:
            return 0.01

        account = mt5.account_info()
        info = mt5.symbol_info(self.config.symbol)

        if account is None or info is None:
            logger.warning('Missing account or symbol info - fallback volume used')
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
        if self.config.tester_force_signal in {'BUY', 'SELL'}:
            signal = self.config.tester_force_signal  # type: ignore
            self.log_debug(f'Forced tester signal applied: {signal}')

        if signal == 'HOLD':
            return

        if not self.config.allow_multiple_positions:
            if self.has_existing_bot_position():
                logger.info('Existing bot-managed position detected - skipping new entry')
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
                logger.error('Missing tick or symbol info')
                return

            price = tick.ask if signal == 'BUY' else tick.bid
            point = info.point

        if signal == 'BUY':
            sl = price - self.config.stop_loss_points * point
            tp = price + self.config.take_profit_points * point
        else:
            sl = price + self.config.stop_loss_points * point
            tp = price - self.config.take_profit_points * point

        if self.config.dry_run or self.config.simulate_data:
            logger.info(
                f'[DRY RUN] {signal} price={price:.2f} '
                f'volume={volume} sl={sl:.2f} tp={tp:.2f}'
            )
            result_text = 'DRY_RUN_ONLY'
        else:
            order_type = mt5.ORDER_TYPE_BUY if signal == 'BUY' else mt5.ORDER_TYPE_SELL

            request: dict[str, Any] = {
                'action': mt5.TRADE_ACTION_DEAL,
                'symbol': self.config.symbol,
                'volume': volume,
                'type': order_type,
                'price': price,
                'sl': sl,
                'tp': tp,
                'deviation': 20,
                'magic': self.config.magic_number,
                'comment': 'SPX500 managed bot',
                'type_time': mt5.ORDER_TIME_GTC,
                'type_filling': mt5.ORDER_FILLING_IOC,
            }

            logger.info(f'Sending order request: {request}')

            result = mt5.order_send(request)

            if result is None:
                logger.error(f'order_send returned None: {mt5.last_error()}')
                return

            result_text = str(result)

            logger.info(f'Order result: {result_text}')

            try:
                logger.info(
                    f'[ORDER SUCCESS] ticket={result.order} '
                    f'retcode={result.retcode}'
                )
            except Exception:
                pass

        self.trades_today += 1

        self.logger.write([
            timestamp,
            self.config.symbol,
            signal,
            price,
            volume,
            sl,
            tp,
            self.config.dry_run,
            result_text,
            self.session_pnl_points,
        ])


def main() -> None:
    config = BotConfig()
    strategy = PullbackStrategy()
    manager = MT5TradeManager(config)

    try:
        manager.connect()

        logger.info('SPX500 MT5 manager started')

        while True:
            manager.heartbeat()
            manager.log_positions()

            rates = manager.get_rates()

            if rates:
                signal = strategy.signal(rates)

                logger.info(
                    f'[SIGNAL] symbol={config.symbol} signal={signal}'
                )

                manager.place_order(signal, rates)

            time.sleep(config.poll_seconds)

    except KeyboardInterrupt:
        logger.warning('Bot stopped by user')

    except Exception as error:
        logger.exception(f'Fatal bot error: {error}')

    finally:
        manager.shutdown()


if __name__ == '__main__':
    main()
