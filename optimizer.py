"""
Ultra-fast mini optimizer for the SPX500 pullback strategy.

Purpose:
- Finish quickly on a MacBook Air.
- Show progress so Terminal does not look frozen.
- Test a few safer settings before paper/demo trading.

This uses the simulated backtester, so the next milestone is real CSV data.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

from backtest import generate_simulated_candles, run_backtest


@dataclass
class Result:
    sl: int
    tp: int
    lookback: int
    max_losses: int
    pause: int
    session_filter: bool
    seeds_tested: int
    total_trades: int
    avg_pnl: float
    min_pnl: float
    max_pnl: float
    avg_win_rate: float
    avg_profit_factor: float
    worst_drawdown: float


def metrics(trades) -> tuple[float, float, float, float]:
    if not trades:
        return 0.0, 0.0, 0.0, 0.0

    pnl = sum(t.pnl for t in trades)
    wins = sum(1 for t in trades if t.pnl > 0)
    win_rate = wins / len(trades) * 100
    gross_win = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    profit_factor = gross_win / gross_loss if gross_loss else 99.0

    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for trade in trades:
        equity += trade.pnl
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)

    return pnl, win_rate, profit_factor, max_drawdown


def main() -> None:
    seeds = [581, 999]
    candles_count = 12000
    point = 0.01
    max_trades = 50
    max_total_loss_points = 900

    stop_losses = [300]
    take_profits = [450, 500]
    lookbacks = [18, 24]
    max_consecutive_losses_options = [2]
    pause_options = [120]
    session_filter_options = [False, True]

    results: list[Result] = []
    combinations = list(
        product(
            stop_losses,
            take_profits,
            lookbacks,
            max_consecutive_losses_options,
            pause_options,
            session_filter_options,
        )
    )
    total_jobs = len(combinations) * len(seeds)
    job_number = 0

    print(f"Testing {len(combinations)} parameter sets across {len(seeds)} seeds ({total_jobs} jobs)...", flush=True)

    for sl, tp, lookback, max_losses, pause, session_filter in combinations:
        pnls: list[float] = []
        win_rates: list[float] = []
        profit_factors: list[float] = []
        drawdowns: list[float] = []
        total_trades = 0

        for seed in seeds:
            job_number += 1
            print(
                f"Job {job_number}/{total_jobs}: SL={sl} TP={tp} lookback={lookback} "
                f"session={session_filter} seed={seed}",
                flush=True,
            )
            candles = generate_simulated_candles(candles_count, seed=seed)
            trades = run_backtest(
                candles=candles,
                stop_loss_points=sl,
                take_profit_points=tp,
                point=point,
                max_trades=max_trades,
                lookback=lookback,
                max_consecutive_losses=max_losses,
                loss_pause_candles=pause,
                max_total_loss_points=max_total_loss_points,
                min_ema_distance=2.0,
                max_ema_crosses=6,
                min_recent_range=12.0,
                min_atr=1.0,
                max_atr=25.0,
                min_body_ratio=0.20,
                min_ema_slope=0.01,
                enable_session_filter=session_filter,
            )
            pnl, win_rate, profit_factor, drawdown = metrics(trades)
            pnls.append(pnl)
            win_rates.append(win_rate)
            profit_factors.append(profit_factor)
            drawdowns.append(drawdown)
            total_trades += len(trades)

        results.append(
            Result(
                sl=sl,
                tp=tp,
                lookback=lookback,
                max_losses=max_losses,
                pause=pause,
                session_filter=session_filter,
                seeds_tested=len(seeds),
                total_trades=total_trades,
                avg_pnl=sum(pnls) / len(pnls),
                min_pnl=min(pnls),
                max_pnl=max(pnls),
                avg_win_rate=sum(win_rates) / len(win_rates),
                avg_profit_factor=sum(profit_factors) / len(profit_factors),
                worst_drawdown=min(drawdowns),
            )
        )

    results.sort(key=lambda r: (r.min_pnl, r.avg_profit_factor, r.avg_pnl, r.total_trades), reverse=True)

    print("\nTop robust settings")
    print("-------------------")
    for r in results:
        print(
            f"SL={r.sl} TP={r.tp} lookback={r.lookback} max_losses={r.max_losses} "
            f"pause={r.pause} session={r.session_filter} | "
            f"trades={r.total_trades} avg_pnl={r.avg_pnl:.0f} min_pnl={r.min_pnl:.0f} "
            f"max_pnl={r.max_pnl:.0f} avg_wr={r.avg_win_rate:.1f}% "
            f"avg_pf={r.avg_profit_factor:.2f} worst_dd={r.worst_drawdown:.0f}"
        )

    print("\nRule: prefer settings with positive/least-bad min_pnl, avg_profit_factor > 1.2, and enough trades to matter.")
    print("This is still simulated data. Real CSV market data comes next before paper trading confidence.")


if __name__ == "__main__":
    main()
