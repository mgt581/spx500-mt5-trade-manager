import MetaTrader5 as mt5
import time

SYMBOL = "SPX500"
LOT = 0.1

# Basic MT5 init
if not mt5.initialize():
    print("MT5 initialize failed")
    quit()

print("Connected to MT5")

# Simple example loop (placeholder)
while True:
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick:
        print(f"Price: {tick.bid}")

    time.sleep(5)
