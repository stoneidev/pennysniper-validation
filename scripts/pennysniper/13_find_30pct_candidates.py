"""
Step 13: Find +30% intraday candidate events from daily cache.

We already have daily OHLCV cached for 274 penny tickers. Find days where:
  - high/open >= 1.30  (intraday move at least +30%)
  - high/open <  2.00  (NOT already in our +100% set — those are cached for minutes)
  - Open in penny range ($1-$10)
  - Dollar volume >= $500K

Then sample 100 randomly (mixed dates) to fetch minute data.

Combined with existing 100 +100% events, total minute-resolved set will be ~200,
with sufficient +30%-but-not-+100% coverage.
"""
import pandas as pd
import numpy as np
from pathlib import Path

CACHE_DIR = Path("price_cache")
EXISTING_MINUTE_CACHE = Path("polygon_minute_cache")
OUT_CSV = "events_30pct_candidates.csv"

PRICE_MIN = 1.0
PRICE_MAX = 10.0
MIN_HX = 1.30  # +30% intraday
MAX_HX = 2.00  # exclude +100% (already cached for minutes)
MIN_DOLLAR_VOL = 500_000

rows = []
for csv_file in CACHE_DIR.glob("*.csv"):
    sym = csv_file.stem
    try:
        df = pd.read_csv(csv_file, index_col=0, parse_dates=True)
    except Exception:
        continue
    if len(df) < 5 or "Open" not in df.columns:
        continue

    o = df["Open"]
    h = df["High"]
    l = df["Low"]
    c = df["Close"]
    v = df["Volume"]

    valid = o > 0
    hx = h / o.where(valid)
    lx = l / o.where(valid)
    cx = c / o.where(valid)
    dv = c * v

    mask = (
        valid
        & (hx >= MIN_HX)
        & (hx < MAX_HX)
        & (o.between(PRICE_MIN, PRICE_MAX))
        & (dv >= MIN_DOLLAR_VOL)
    )

    for ts in df.index[mask]:
        rows.append({
            "symbol": sym,
            "date": ts.strftime("%Y-%m-%d"),
            "open": float(o.loc[ts]),
            "high": float(h.loc[ts]),
            "low": float(l.loc[ts]),
            "close": float(c.loc[ts]),
            "high_x_open": float(hx.loc[ts]),
            "low_x_open": float(lx.loc[ts]),
            "close_x_open": float(cx.loc[ts]),
            "dollar_vol": float(dv.loc[ts]),
        })

candidates = pd.DataFrame(rows)
print(f"Total +30%-but-<+100% candidate days: {len(candidates)}")
print(f"Unique tickers:                       {candidates['symbol'].nunique()}")
print(f"Date range:                           {candidates['date'].min()} → {candidates['date'].max()}")
print(f"Median dollar volume:                 ${candidates['dollar_vol'].median():,.0f}")
print(f"Median high/open:                     {candidates['high_x_open'].median():.2f}")

# Mark which ones already have minute data cached
candidates["minute_cached"] = candidates.apply(
    lambda r: (EXISTING_MINUTE_CACHE / f"{r['symbol']}_{r['date']}.json").exists(),
    axis=1,
)
print(f"Already have minute data:             {candidates['minute_cached'].sum()}")

# Sample 100 to fetch (chronologically spread)
need_fetch = candidates[~candidates["minute_cached"]].copy()
need_fetch = need_fetch.sort_values("date")
# Stratified sample: take every Nth row to spread across time
n_target = 100
if len(need_fetch) > n_target:
    step = len(need_fetch) // n_target
    sampled = need_fetch.iloc[::step].head(n_target).copy()
else:
    sampled = need_fetch.copy()

sampled.to_csv(OUT_CSV, index=False)
print(f"\nSaved {len(sampled)} events to fetch in {OUT_CSV}")
print(f"  date range: {sampled['date'].min()} → {sampled['date'].max()}")
print(f"  median high/open: {sampled['high_x_open'].median():.2f}")
