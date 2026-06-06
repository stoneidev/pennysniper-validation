"""
Step 7: Re-simulate +100% chasing strategy using Polygon 1-minute bars.

Resolves the path ambiguity from the daily backtest (Optimistic +0.38% vs
Pessimistic -5%). For each event, walk minute-by-minute and determine
exactly which of TP / SL triggered first.

Polygon Free plan: 5 calls/minute. Sleeps 13s between calls.
API key from env var POLYGON_API_KEY (not hardcoded).
"""
import os
import sys
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path
import pandas as pd

API_KEY = os.environ.get("POLYGON_API_KEY")
if not API_KEY:
    sys.exit("ERROR: set POLYGON_API_KEY env var")

EVENTS_CSV = "chasing_trades_classified.csv"
OUT_CSV = "chasing_trades_minute.csv"
CACHE_DIR = Path("polygon_minute_cache")
CACHE_DIR.mkdir(exist_ok=True)

# Strategy parameters (same as daily test)
ENTRY_MULTIPLE = 2.0   # +100% from open
TP_MULTIPLE = 1.10     # +10% from entry
SL_MULTIPLE = 0.95     # -5% from entry

# Free plan: 5 calls/min. Use 13s spacing to stay safe.
SLEEP_BETWEEN_CALLS = 13.0


def fetch_minute_bars(symbol: str, date_str: str) -> pd.DataFrame | None:
    """Fetch 1-min bars for one (symbol, date). Cached on disk."""
    cache_file = CACHE_DIR / f"{symbol}_{date_str}.json"
    if cache_file.exists():
        with open(cache_file) as f:
            data = json.load(f)
        if data.get("results"):
            return _to_df(data["results"])
        return None

    url = (
        f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/minute/"
        f"{date_str}/{date_str}?adjusted=true&sort=asc&limit=50000"
        f"&apiKey={API_KEY}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "pennysniper-validation/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"    {symbol} {date_str}: fetch error {e}")
        return None
    # cache (even empty results, to avoid re-querying)
    with open(cache_file, "w") as f:
        json.dump(data, f)
    if data.get("results"):
        return _to_df(data["results"])
    return None


def _to_df(results: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(results)
    # t = ms epoch, convert to UTC then NY
    df["timestamp"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert("America/New_York")
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    return df[["timestamp", "open", "high", "low", "close", "volume"]].sort_values("timestamp").reset_index(drop=True)


def restrict_to_rth(df: pd.DataFrame) -> pd.DataFrame:
    """Regular trading hours: 09:30 - 16:00 ET."""
    if df is None or len(df) == 0:
        return df
    rth = df[
        (df["timestamp"].dt.time >= pd.Timestamp("09:30").time())
        & (df["timestamp"].dt.time < pd.Timestamp("16:00").time())
    ].reset_index(drop=True)
    return rth


def simulate_event(bars: pd.DataFrame) -> dict:
    """
    Walk minute-by-minute:
      1. Find first bar where high >= ENTRY_MULTIPLE * RTH_open  (=2x open).
         Entry price = ENTRY_MULTIPLE * RTH_open (assume limit at +100% line).
      2. From entry bar onward, find first bar where low <= SL or high >= TP.
         If both touched in same bar: assume SL first (pessimistic; standard backtest convention).
      3. If neither hits by close, exit at close of last RTH bar.
    """
    if bars is None or len(bars) == 0:
        return {"status": "no_data"}

    rth_open = float(bars["open"].iloc[0])
    if rth_open <= 0:
        return {"status": "bad_open"}

    entry_target = rth_open * ENTRY_MULTIPLE

    # Find entry bar: first bar where high >= entry_target
    entry_idx = None
    for i, row in enumerate(bars.itertuples(index=False)):
        if row.high >= entry_target:
            entry_idx = i
            break
    if entry_idx is None:
        return {
            "status": "no_entry",
            "rth_open": rth_open,
            "rth_high": float(bars["high"].max()),
            "rth_close": float(bars["close"].iloc[-1]),
        }

    entry_price = entry_target
    tp_price = entry_price * TP_MULTIPLE
    sl_price = entry_price * SL_MULTIPLE
    entry_time = bars["timestamp"].iloc[entry_idx]

    # Walk forward
    for j in range(entry_idx, len(bars)):
        bar = bars.iloc[j]
        # Within entry bar, the entry price is mid-bar; conservative: only check after entry_idx.
        # But limit-order semantics: filled when price crossed, then SL/TP from that moment.
        # Pessimistic convention: if same bar has low <= sl AND high >= tp, SL hits first.
        if j == entry_idx:
            # After entry, check rest of THIS bar's range against SL/TP
            # We don't know intra-minute path. Be pessimistic on first bar.
            if bar.low <= sl_price and bar.high >= tp_price:
                return _result("sl", entry_time, bar.timestamp, entry_price, sl_price, j - entry_idx)
            if bar.low <= sl_price:
                return _result("sl", entry_time, bar.timestamp, entry_price, sl_price, j - entry_idx)
            if bar.high >= tp_price:
                return _result("tp", entry_time, bar.timestamp, entry_price, tp_price, j - entry_idx)
        else:
            # Check open first (gap), then intrabar
            if bar.open <= sl_price:
                return _result("sl_gap", entry_time, bar.timestamp, entry_price, bar.open, j - entry_idx)
            if bar.open >= tp_price:
                return _result("tp_gap", entry_time, bar.timestamp, entry_price, bar.open, j - entry_idx)
            # Pessimistic: SL before TP in same bar
            if bar.low <= sl_price and bar.high >= tp_price:
                return _result("sl", entry_time, bar.timestamp, entry_price, sl_price, j - entry_idx)
            if bar.low <= sl_price:
                return _result("sl", entry_time, bar.timestamp, entry_price, sl_price, j - entry_idx)
            if bar.high >= tp_price:
                return _result("tp", entry_time, bar.timestamp, entry_price, tp_price, j - entry_idx)

    # Exit at close of last bar
    last = bars.iloc[-1]
    return _result("eod", entry_time, last.timestamp, entry_price, float(last.close), len(bars) - 1 - entry_idx)


def _result(reason, entry_time, exit_time, entry_price, exit_price, bars_held):
    ret = exit_price / entry_price - 1.0
    return {
        "status": "ok",
        "exit_reason": reason,
        "entry_time": str(entry_time),
        "exit_time": str(exit_time),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "minute_return": ret,
        "bars_held": bars_held,
    }


def main() -> None:
    events = pd.read_csv(EVENTS_CSV)
    print(f"Re-simulating {len(events)} events with 1-min Polygon data...")
    print(f"Rate limit: 5 calls/min → {SLEEP_BETWEEN_CALLS}s between fetches")
    print(f"Estimated time: ~{len(events) * SLEEP_BETWEEN_CALLS / 60:.0f} min "
          f"(less if many cache hits)\n")

    results = []
    n_fetched_now = 0
    t_start = time.time()

    for i, ev in events.iterrows():
        sym = ev["symbol"]
        date = ev["date"]
        cache_file = CACHE_DIR / f"{sym}_{date}.json"
        was_cached = cache_file.exists()

        bars = fetch_minute_bars(sym, date)
        if not was_cached:
            n_fetched_now += 1

        rth = restrict_to_rth(bars) if bars is not None else None
        sim = simulate_event(rth) if rth is not None else {"status": "no_data"}

        row = {
            "symbol": sym,
            "date": date,
            "daily_open": ev["open"],
            "daily_high": ev["high"],
            "daily_low": ev["low"],
            "daily_close": ev["close"],
            "daily_high_x_open": ev["high_x_open"],
            "daily_close_x_open": ev["close_x_open"],
            "previous_realistic_outcome": ev["realistic_outcome"],
            "previous_realistic_return": ev["realistic_return"],
            **sim,
        }
        results.append(row)

        if (i + 1) % 10 == 0 or (i + 1) == len(events):
            elapsed = time.time() - t_start
            print(f"  {i + 1}/{len(events)} | fetched_this_run={n_fetched_now} "
                  f"| elapsed={elapsed / 60:.1f}min")

        # Save progress periodically
        if (i + 1) % 20 == 0:
            pd.DataFrame(results).to_csv(OUT_CSV, index=False)

        # Sleep only if we actually hit the API
        if not was_cached and i < len(events) - 1:
            time.sleep(SLEEP_BETWEEN_CALLS)

    df = pd.DataFrame(results)
    df.to_csv(OUT_CSV, index=False)
    print(f"\nSaved {len(df)} rows to {OUT_CSV}")
    print(f"  status counts:")
    print(df["status"].value_counts().to_string())


if __name__ == "__main__":
    main()
