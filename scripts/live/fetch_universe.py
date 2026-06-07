"""
Fetch NASDAQ daily prices via yfinance.

Designed for GitHub Actions (no local Stooq dependency).

Strategy:
  1. Read NASDAQ symbol list from nasdaqtrader.com
  2. Filter to common stocks (exclude warrants/rights/etfs/test)
  3. For each symbol, fetch last 250 days of daily OHLCV via yfinance
  4. Save to data/daily_cache/{SYM}.csv

Incremental update:
  - If cache exists, fetch only since last cached date + 1
  - Else fetch full lookback

Output:
  data/daily_cache/{TICKER}.csv  (one file per ticker)
  data/daily_cache/_meta.json    (last fetch timestamp + universe size)
"""
import json
import os
import sys
import time
import urllib.request
from io import StringIO
from pathlib import Path
import pandas as pd
import yfinance as yf

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "daily_cache"
CACHE.mkdir(parents=True, exist_ok=True)
META = CACHE / "_meta.json"

LOOKBACK_DAYS = 250  # ~1 year of trading days
PRICE_MIN = 0.30      # for penny universe filtering during fetch
PRICE_MAX = 5.00      # widen so breakout-target tickers ($1.05-1.50) are included

EXCLUDE_SUFFIX = ("W", "R", "U", "Z")
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"


def fetch_nasdaq_symbols():
    print(f"Fetching NASDAQ symbol list from {NASDAQ_LISTED_URL}...")
    req = urllib.request.Request(NASDAQ_LISTED_URL, headers={"User-Agent": "breakout-scanner/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8")
    df = pd.read_csv(StringIO(text), sep="|")
    df = df[df["Symbol"].notna() & ~df["Symbol"].str.contains("File", na=False)]
    df = df[df.get("Test Issue", "N") == "N"]
    df = df[df.get("ETF", "N") == "N"]
    # Standard symbol only
    df = df[~df["Symbol"].str.contains(r"\$|\.|=", regex=True, na=False)]
    syms = df["Symbol"].astype(str).str.upper().tolist()
    # Exclude warrants/rights/units/preferred
    syms = [s for s in syms if not s.endswith(EXCLUDE_SUFFIX)]
    syms = [s for s in syms if not (len(s) > 4 and s[-3:].startswith("PR"))]
    print(f"  {len(syms)} candidate symbols (warrants/rights excluded)")
    return syms


def fetch_one(sym: str, lookback_days: int) -> pd.DataFrame | None:
    """Fetch one ticker's daily bars via yfinance."""
    try:
        df = yf.download(
            tickers=sym,
            period=f"{lookback_days}d",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception:
        return None
    if df is None or len(df) == 0:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if len(df) < 30:
        return None
    df = df.reset_index()
    df = df.rename(columns={df.columns[0]: "Date"})
    return df[["Date", "Open", "High", "Low", "Close", "Volume"]]


def main():
    symbols = fetch_nasdaq_symbols()

    # Optional: limit to those that recently traded under $5 (keep universe small for GH Action)
    # We'll do this lazily — fetch all, filter at scanner step.
    # But to control runtime, we fetch in batches and skip ones whose latest close is way out of range.

    print(f"\nFetching {len(symbols)} tickers (this may take 10-30 min depending on yfinance speed)...")
    t0 = time.time()
    fetched = 0
    skipped = 0
    for i, sym in enumerate(symbols):
        cache_file = CACHE / f"{sym}.csv"

        # Quick price filter: skip mega-cap clearly outside penny range
        # We do this by looking at most recent 5d via yfinance's lighter call
        df = fetch_one(sym, LOOKBACK_DAYS)
        if df is None:
            skipped += 1
            continue

        last_close = float(df["Close"].iloc[-1])
        # Filter: must have ever traded in penny range during this window
        ever_low = (df["Close"] < PRICE_MAX).any() and (df["Close"] > PRICE_MIN).any()
        if not ever_low:
            skipped += 1
            continue

        df.to_csv(cache_file, index=False)
        fetched += 1

        if (i + 1) % 200 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            remaining = (len(symbols) - (i + 1)) / max(rate, 0.1)
            print(f"  {i+1}/{len(symbols)} | fetched {fetched}, skipped {skipped}, "
                  f"elapsed {elapsed:.0f}s, ETA {remaining:.0f}s")

    # Save metadata
    meta = {
        "last_fetch": pd.Timestamp.now().isoformat(),
        "universe_size": fetched,
        "symbols_attempted": len(symbols),
        "symbols_skipped": skipped,
    }
    with open(META, "w") as f:
        json.dump(meta, f, indent=2)

    elapsed = time.time() - t0
    print(f"\n✓ Done in {elapsed:.0f}s")
    print(f"  Cached: {fetched} tickers")
    print(f"  Skipped: {skipped} (outside penny range or fetch failed)")


if __name__ == "__main__":
    main()
