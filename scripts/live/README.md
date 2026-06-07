# Live Trading Automation

Daily scanner + quarterly rule retrainer.

## Architecture

```
┌─────────────────────────┐
│ quarterly_retrain.py    │  Every quarter (Jan/Apr/Jul/Oct 1st)
│ - Trains on prior 3mo   │  → writes config/current_rule.json
│ - Picks best by score   │
└────────┬────────────────┘
         │
         ↓
┌─────────────────────────┐
│ config/current_rule.json│  Current quarter's rule
│ {                        │
│   "cons_d": 30,          │
│   "entry_lo": 1.20,      │
│   "entry_hi": 1.50,      │
│   "tp_ratio": 1.15,      │
│   "hold_d": 30,          │
│   "valid_until": "..."   │
│ }                        │
└────────┬────────────────┘
         │
         ↓
┌─────────────────────────┐
│ daily_scanner.py        │  Every weekday after market close
│ - Reads current rule    │  → appends to logs/signals_YYYY-MM.csv
│ - Scans Stooq universe  │  → prints alert for new signals
└─────────────────────────┘
```

## Setup

```bash
# 1. Initial rule (run once)
python scripts/live/quarterly_retrain.py

# 2. Verify config created
cat config/current_rule.json

# 3. Daily scan (manual test)
python scripts/live/daily_scanner.py
```

## Cron jobs (macOS / Linux)

```cron
# Quarterly retrain (1st of Jan/Apr/Jul/Oct, 6am)
0 6 1 1,4,7,10 * cd /Users/stoni/Downloads/pennysniper_validation && /Users/stoni/Downloads/pennysniper_validation/venv/bin/python scripts/live/quarterly_retrain.py >> logs/retrain.log 2>&1

# Daily scanner (weekdays 5pm KST = ~3am UTC, after US close)
0 17 * * 1-5 cd /Users/stoni/Downloads/pennysniper_validation && /Users/stoni/Downloads/pennysniper_validation/venv/bin/python scripts/live/daily_scanner.py >> logs/scan.log 2>&1
```

## Stooq data refresh

The scripts assume Stooq data is in:
```
/Users/stoni/Downloads/data/daily/us/nasdaq stocks/{1,2,3}/*.txt
```

Refresh weekly by re-downloading from https://stooq.com/db/h/

## Trade execution

Currently the scanner only **detects and alerts**. To automate trade execution,
add an integration with your broker API (Alpaca, IBKR, Tastytrade, etc.)
that:

1. Reads `logs/signals_YYYY-MM.csv` for new entries
2. Places a market BUY order at next-day open
3. Places a limit SELL order at TP price (= entry × tp_ratio)
4. Sets a calendar reminder to force-sell after `hold_d` days if TP not hit

## Risk controls (recommended)

- Max position size: 25% of cash per trade (or 10% for safer)
- Max simultaneous positions: 4
- Daily loss limit: −5% of total NAV → halt for the day
- Monthly review: stop if 3 consecutive months net negative
- Hard limit: 90 days holding + close at any cost

## Backtest reproducibility

The exact same logic is in:
- `scripts/breakout/breakout_15_rolling_3month.py` (historical aggregate)
- `scripts/breakout/breakout_16_2026q2_forward.py` (latest window)

Re-run those after each quarter to validate the live system matches the
historical simulation.
