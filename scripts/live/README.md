# Live Daily Breakout Scanner

GitHub Actions로 매일 자동 스캔 → 시그널 발견 시 markdown 리포트 자동 생성 → repo에 commit.

## Architecture

```
┌──────────────────────────────────┐
│ GitHub Actions (cron)            │  Daily 06:00 UTC, Tue-Sat
│ .github/workflows/daily_breakout │
│   _scan.yml                      │
└────────┬─────────────────────────┘
         ↓
┌──────────────────────────────────┐
│ 1. fetch_universe.py             │  yfinance로 NASDAQ 일봉 fetch
│    → data/daily_cache/{TICKER}.csv │
└────────┬─────────────────────────┘
         ↓
┌──────────────────────────────────┐
│ 2. quarterly_retrain.py          │  분기 1일에만 실행
│    (if 1st of Jan/Apr/Jul/Oct)   │  → config/current_rule.json
└────────┬─────────────────────────┘
         ↓
┌──────────────────────────────────┐
│ 3. daily_report.py               │  현재 룰로 시그널 탐지
│    → reports/YYYY-MM-DD.md       │  → markdown 리포트 작성
└────────┬─────────────────────────┘
         ↓
┌──────────────────────────────────┐
│ git commit + push                │  자동 commit (bot 명의)
└──────────────────────────────────┘
```

## Files

| File | Purpose |
|---|---|
| `fetch_universe.py` | NASDAQ symbol list + yfinance daily bars |
| `quarterly_retrain.py` | Re-optimize rule using prior 3 months |
| `daily_report.py` | Detect signals & write markdown report |
| `import_stooq_cache.py` | (one-time) bootstrap from local Stooq archive |
| `generate_may_reports.py` | Backfill May 2025 reports |
| `may_summary.py` | Aggregate May 2025 outcomes |

## Manual usage

```bash
# 1. Fetch universe (slow first time, ~10-30 min)
python scripts/live/fetch_universe.py

# 2. Train quarterly rule (or override with --as-of for backtest)
python scripts/live/quarterly_retrain.py --as-of 2025-04-15 --out config/rule_2025_q2.json

# 3. Generate one daily report
python scripts/live/daily_report.py --as-of 2025-05-08 --rule-file config/rule_2025_q2.json

# 4. Bulk-generate historical reports (e.g., May 2025)
python scripts/live/generate_may_reports.py
python scripts/live/may_summary.py
```

## GitHub Actions setup

The workflow at `.github/workflows/daily_breakout_scan.yml`:

1. Runs daily 06:00 UTC (Tue-Sat — covers Mon-Fri US trading days)
2. Fetches latest yfinance data into `data/daily_cache/`
3. On the 1st of each quarter, retrains the rule
4. Detects signals using current rule, writes report
5. Commits any new reports/config to the repo

### Permissions

Workflow needs `contents: write` to commit reports back. Already configured.

### Manual trigger

```bash
gh workflow run daily_breakout_scan.yml \
  -f as_of_date=2025-05-15  # optional: backtest a specific date
```

### Time / cost

- **fetch_universe**: ~10-20 min (4,000 tickers × yfinance rate limit)
- **quarterly_retrain**: ~30 sec
- **daily_report**: ~5 sec
- **Total daily run**: ~15-25 min within free GH Actions tier (2,000 min/month)

## Stooq vs yfinance trade-off

This live system uses **yfinance** because:
- Works in any environment (Stooq requires local download)
- Auto split-adjusted prices
- Free tier sufficient for daily scans

Trade-off:
- yfinance is rate-limited (~100 tickers/min)
- Less reliable than Stooq for thin penny stocks
- Some tickers may be missing or have data gaps

For larger backtests, use the local Stooq pipeline (see `scripts/breakout/`).

## Risk controls (recommended for live trading)

- **Position size**: 25% of cash per signal (max 4 simultaneous)
- **Daily loss limit**: -5% of NAV → halt for the day
- **Monthly review**: stop if 3 consecutive months net negative
- **Hard limit**: respect `hold_d` from rule, force-close at expiry
- **Warrant/right exclusion**: handled in `fetch_universe.py` (W/R/U/Z suffix)

## Reproducing past reports

The May 2025 reports (`reports/2025-05-*.md`) used:
- **Rule**: `config/rule_2025_q2.json` (trained on 2025.01-03)
- **Universe**: bootstrapped from Stooq via `import_stooq_cache.py`

Summary at `reports/_may_2025_summary.md`:
- 4 signals (CTMX, JBDI, NBP, ONDS)
- 3 hit TP +50%, 1 hit hold-expiry loss
- ₩1M with 25% allocation → ₩1.37M (+37%)
