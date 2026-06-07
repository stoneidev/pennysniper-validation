"""
Helper: convert local Stooq daily csv files to data/daily_cache/{TICKER}.csv format.

This is a one-time bootstrap so we can generate historical reports without
running the full yfinance fetch (which takes hours).

In production (GH Action), use fetch_universe.py instead.
"""
import sys
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
STOOQ = Path("/Users/stoni/Downloads/data/daily/us/nasdaq stocks")
OUT = REPO / "data" / "daily_cache"
OUT.mkdir(parents=True, exist_ok=True)

EXCLUDE_SUFFIX = ("W", "R", "U", "Z")
PRICE_MIN = 0.30
PRICE_MAX = 5.00
START_DATE = pd.Timestamp("2024-01-01")  # keep ~2 years of history


def is_excluded(s):
    if s.endswith(EXCLUDE_SUFFIX):
        return True
    if len(s) > 4 and s[-3:].startswith("PR"):
        return True
    return False


def main():
    csv_files = []
    for d in STOOQ.iterdir():
        if d.is_dir():
            csv_files.extend(d.glob("*.txt"))
    print(f"Found {len(csv_files)} Stooq files")

    n_written = 0
    n_skipped = 0
    for f in csv_files:
        sym = f.stem.upper().replace(".US", "")
        if is_excluded(sym):
            n_skipped += 1
            continue
        try:
            df = pd.read_csv(f)
        except Exception:
            n_skipped += 1
            continue
        if df.empty or "<DATE>" not in df.columns:
            n_skipped += 1
            continue
        df = df.rename(columns={
            "<DATE>": "Date", "<OPEN>": "Open", "<HIGH>": "High",
            "<LOW>": "Low", "<CLOSE>": "Close", "<VOL>": "Volume",
        })
        df["Date"] = pd.to_datetime(df["Date"], format="%Y%m%d")
        df = df[df["Date"] >= START_DATE].dropna(subset=["Open", "High", "Low", "Close"])
        if len(df) < 35:
            n_skipped += 1
            continue
        c = df["Close"].values
        # Must have ever traded in penny range
        if not ((c >= PRICE_MIN) & (c < PRICE_MAX)).any():
            n_skipped += 1
            continue
        df = df[["Date", "Open", "High", "Low", "Close", "Volume"]].sort_values("Date")
        df.to_csv(OUT / f"{sym}.csv", index=False)
        n_written += 1
        if n_written % 500 == 0:
            print(f"  wrote {n_written}")

    print(f"\n✓ Wrote {n_written} ticker CSVs to {OUT}")
    print(f"  Skipped {n_skipped}")


if __name__ == "__main__":
    main()
