# SPX500 MT5 Trade Manager

Simple, safe starter trading bot for MetaTrader 5 (MT5).

## ⚠️ Safety
By default the bot runs in **dry run mode** (no real trades).

## 1) Get the project

```bash
git clone https://github.com/mgt581/spx500-mt5-trade-manager.git
cd spx500-mt5-trade-manager
```

## 2) Install requirements

```bash
pip install -r requirements.txt
```

## 3) Configure

Copy the example env file:

```bash
cp .env.example .env
```

Edit `.env` if needed (symbol name, risk, etc).

## 4) Run the bot

```bash
python bot.py
```

You should see:

- Connected to MT5
- Signals (BUY / SELL / HOLD)
- No real trades if BOT_DRY_RUN=true

## 5) Demo trading

When ready:

- Log into a **demo account** in MT5
- Set:

```
BOT_DRY_RUN=false
```

Then run again.

## Notes

- Make sure your MT5 terminal is open and logged in
- Symbol name must match your broker (e.g. SPX500, US500)
- Always test on demo first
