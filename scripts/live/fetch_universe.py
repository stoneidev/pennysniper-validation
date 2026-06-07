"""
Fetch NASDAQ daily prices via yfinance with INCREMENTAL update.

Strategy:
  - If cache exists for ticker AND last cached date >= 7d ago, fetch only
    last ~10 days and append (deduped on Date)
  - Else fetch full 250d (initial seed)
  - For tickers we've never seen, do full fetch
  - Excludes warrants/rights/units (W/R/U/Z/PR* suffix)
  - Penny universe filter: keeps tickers that traded in $0.30-$5.00 range

Expected runtime:
  - Initial seed (no cache): ~20-40 min for ~3,000 NASDAQ tickers
  - Daily incremental update: ~3-5 min for ~1,500 cached tickers + new ones
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

LOOKBACK_DAYS_FULL = 250          # initial seed lookback
LOOKBACK_DAYS_INCREMENTAL = 10    # safety overlap for daily updates
INCREMENTAL_TRIGGER_DAYS = 5      # if cache last < this many days old, do incremental
PRICE_MIN = 0.30
PRICE_MAX = 5.00

EXCLUDE_SUFFIX = ("W", "R", "U", "Z")
NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"


def fetch_nasdaq_symbols():
    print(f"Fetching NASDAQ symbol list...")
    req = urllib.request.Request(NASDAQ_LISTED_URL, headers={"User-Agent": "breakout-scanner/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8")
    df = pd.read_csv(StringIO(text), sep="|")
    df = df[df["Symbol"].notna() & ~df["Symbol"].str.contains("File", na=False)]
    df = df[df.get("Test Issue", "N") == "N"]
    df = df[df.get("ETF", "N") == "N"]
    df = df[~df["Symbol"].str.contains(r"\$|\.|=", regex=True, na=False)]
    syms = df["Symbol"].astype(str).str.upper().tolist()
    syms = [s for s in syms if not s.endswith(EXCLUDE_SUFFIX)]
    syms = [s for s in syms if not (len(s) > 4 and s[-3:].startswith("PR"))]
    print(f"  {len(syms)} candidate symbols (warrants/rights excluded)")
    return syms


def fetch_one_full(sym: str, days: int) -> pd.DataFrame | None:
    try:
        df = yf.download(
            tickers=sym,
            period=f"{days}d",
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
    if len(df) < 10:
        return None
    df = df.reset_index()
    df = df.rename(columns={df.columns[0]: "Date"})
    df["Date"] = pd.to_datetime(df["Date"])
    return df[["Date", "Open", "High", "Low", "Close", "Volume"]]


def load_existing_cache(sym: str) -> pd.DataFrame | None:
    f = CACHE / f"{sym}.csv"
    if not f.exists():
        return None
    try:
        df = pd.read_csv(f, parse_dates=["Date"])
        if df.empty:
            return None
        return df.sort_values("Date").reset_index(drop=True)
    except Exception:
        return None


def merge_and_save(sym: str, existing: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    if existing is not None and len(existing) > 0:
        merged = pd.concat([existing, new], ignore_index=True)
        merged = merged.drop_duplicates(subset=["Date"], keep="last")
        merged = merged.sort_values("Date").reset_index(drop=True)
    else:
        merged = new
    # Cap to LOOKBACK_DAYS_FULL most recent rows to keep file size bounded
    if len(merged) > LOOKBACK_DAYS_FULL + 20:
        merged = merged.tail(LOOKBACK_DAYS_FULL).reset_index(drop=True)
    cache_file = CACHE / f"{sym}.csv"
    merged.to_csv(cache_file, index=False)
    return merged


def passes_penny_filter(df: pd.DataFrame) -> bool:
    """Keep tickers that traded in penny range at any point in the cache window."""
    c = df["Close"]
    return ((c >= PRICE_MIN) & (c < PRICE_MAX)).any()


def main():
    symbols = fetch_nasdaq_symbols()
    today = pd.Timestamp.now().normalize()
    print(f"\nToday: {today.date()}")
    print(f"Cache mode: {'incremental (cache exists)' if META.exists() else 'INITIAL SEED (full 250d)'}\n")

    t0 = time.time()
    n_full = 0
    n_incremental = 0
    n_skipped_pricerange = 0
    n_failed = 0
    n_cached_unchanged = 0

    for i, sym in enumerate(symbols):
        existing = load_existing_cache(sym)

        # Decide full vs incremental
        if existing is not None and len(existing) > 0:
            last_date = existing["Date"].max()
            days_old = (today - last_date).days
            if days_old <= INCREMENTAL_TRIGGER_DAYS:
                # Cache fresh enough; fetch small overlap window
                new = fetch_one_full(sym, LOOKBACK_DAYS_INCREMENTAL)
                mode = "incremental"
            else:
                # Cache too stale; refresh full
                new = fetch_one_full(sym, LOOKBACK_DAYS_FULL)
                mode = "full_refresh"
        else:
            new = fetch_one_full(sym, LOOKBACK_DAYS_FULL)
            mode = "full"

        if new is None or len(new) == 0:
            n_failed += 1
            continue

        merged = merge_and_save(sym, existing, new)

        if not passes_penny_filter(merged):
            # Remove from cache (no longer in our universe)
            (CACHE / f"{sym}.csv").unlink(missing_ok=True)
            n_skipped_pricerange += 1
            continue

        if mode == "full":
            n_full += 1
        elif mode == "full_refresh":
            n_full += 1
        else:
            n_incremental += 1
            # Check if any new rows actually appended
            if existing is not None and len(merged) == len(existing):
                n_cached_unchanged += 1

        if (i + 1) % 200 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            remaining = (len(symbols) - (i + 1)) / max(rate, 0.1)
            print(f"  {i+1}/{len(symbols)} | full={n_full}, incr={n_incremental}, "
                  f"skip={n_skipped_pricerange}, fail={n_failed} | "
                  f"elapsed {elapsed:.0f}s, ETA {remaining:.0f}s")

    meta = {
        "last_fetch": pd.Timestamp.now().isoformat(),
        "universe_size": n_full + n_incremental,
        "n_full_fetches": n_full,
        "n_incremental": n_incremental,
        "n_skipped_pricerange": n_skipped_pricerange,
        "n_failed": n_failed,
        "n_cached_unchanged": n_cached_unchanged,
    }
    with open(META, "w") as f:
        json.dump(meta, f, indent=2)

    elapsed = time.time() - t0
    print(f"\n✓ Done in {elapsed:.0f}s ({elapsed/60:.1f} min)")
    print(f"  Full fetches:    {n_full}")
    print(f"  Incremental:     {n_incremental}")
    print(f"  Skipped (price): {n_skipped_pricerange}")
    print(f"  Failed:          {n_failed}")
    print(f"  Total cache:     {len(list(CACHE.glob('*.csv')))} CSVs")


if __name__ == "__main__":
    main()
