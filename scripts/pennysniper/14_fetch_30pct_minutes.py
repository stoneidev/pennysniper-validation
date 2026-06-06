"""
Step 14: Fetch 1-min Polygon bars for 100 sampled +30% events.
Reuses cache directory polygon_minute_cache/ — same format as before.
Free plan rate limit: 5 calls/min → 13s sleep.
"""
import os
import sys
import json
import time
import urllib.request
from pathlib import Path
import pandas as pd

API_KEY = os.environ.get("POLYGON_API_KEY")
if not API_KEY:
    sys.exit("ERROR: set POLYGON_API_KEY env var")

CANDIDATES_CSV = "events_30pct_candidates.csv"
CACHE_DIR = Path("polygon_minute_cache")
CACHE_DIR.mkdir(exist_ok=True)

SLEEP_S = 13.0


def fetch_minute_bars(symbol: str, date: str) -> bool:
    cache = CACHE_DIR / f"{symbol}_{date}.json"
    if cache.exists():
        return True
    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/minute/"
        f"{date}/{date}?adjusted=true&sort=asc&limit=50000&apiKey={API_KEY}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pennysniper/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"    {symbol} {date}: error {e}")
        return False
    with open(cache, "w") as fp:
        json.dump(data, fp)
    return True


def main() -> None:
    cands = pd.read_csv(CANDIDATES_CSV)
    print(f"Fetching {len(cands)} new minute bars (rate limit 5/min)...")
    print(f"Estimated time: ~{len(cands) * SLEEP_S / 60:.0f} min\n")

    t0 = time.time()
    fetched = 0
    for i, row in cands.iterrows():
        was_cached = (CACHE_DIR / f"{row['symbol']}_{row['date']}.json").exists()
        ok = fetch_minute_bars(row["symbol"], row["date"])
        if ok and not was_cached:
            fetched += 1
        if (i + 1) % 10 == 0 or (i + 1) == len(cands):
            print(f"  {i + 1}/{len(cands)} | new fetches={fetched} | elapsed={(time.time()-t0)/60:.1f}min")
        if ok and not was_cached and i < len(cands) - 1:
            time.sleep(SLEEP_S)

    print(f"\nDone. Fetched {fetched} new files into {CACHE_DIR}/")


if __name__ == "__main__":
    main()
