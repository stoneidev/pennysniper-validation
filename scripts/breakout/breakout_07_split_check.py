"""
Verify reverse split contamination in breakout events.

Checks:
  1. yfinance auto_adjust=True was used → past prices already split-adjusted
  2. Detect SUSPICIOUS overnight gaps that might indicate uncaught split
     (e.g., close $0.20 → next open $1.50 with no large volume)
  3. Cross-reference with yfinance .splits accessor (live fetch, may be slow)
  4. Sanity check: do "breakout to $1.05~$1.20" events show the
     pattern of a real catalyst (volume spike) or split artifact (no volume)?
"""
import pandas as pd
import numpy as np
from pathlib import Path
import yfinance as yf
import time
import warnings
warnings.filterwarnings("ignore")

DAILY_CACHE = Path("price_cache")


def main():
    df = pd.read_csv("breakout_60d_results.csv")
    df["date_dt"] = pd.to_datetime(df["date"])
    print(f"Checking {len(df)} breakout events for split artifacts\n")

    rows = []
    for _, ev in df.drop_duplicates(["symbol", "date"]).iterrows():
        sym = ev["symbol"]
        bdate = ev["date_dt"]
        f = DAILY_CACHE / f"{sym}.csv"
        if not f.exists():
            continue
        d = pd.read_csv(f, index_col=0, parse_dates=True).sort_index()
        idx = d.index.searchsorted(bdate)
        if idx <= 0 or idx >= len(d):
            continue

        # Day of breakout vs day before
        prev_close = float(d["Close"].iloc[idx - 1])
        today_open = float(d["Open"].iloc[idx])
        today_close = float(d["Close"].iloc[idx])
        today_high = float(d["High"].iloc[idx])
        today_low = float(d["Low"].iloc[idx])
        today_vol = float(d["Volume"].iloc[idx])
        prev_vol = float(d["Volume"].iloc[idx - 1])

        # Average volume over consolidation
        cons_vol = float(d["Volume"].iloc[max(0, idx - 60) : idx].mean())

        # Overnight gap
        gap = (today_open - prev_close) / prev_close if prev_close > 0 else 0
        # Total day move
        day_move = (today_close - prev_close) / prev_close if prev_close > 0 else 0
        # Volume ratio vs consolidation avg
        vol_ratio = today_vol / cons_vol if cons_vol > 0 else 0

        # Suspicious if: large gap AND volume NOT much elevated
        # Real catalyst: volume 5-50x. Split artifact: volume similar to consolidation.
        suspicious = (gap > 0.30) and (vol_ratio < 3.0)

        rows.append({
            "symbol": sym,
            "date": ev["date"],
            "prev_close": prev_close,
            "today_open": today_open,
            "today_close": today_close,
            "overnight_gap": gap,
            "day_move": day_move,
            "today_vol": today_vol,
            "cons_avg_vol": cons_vol,
            "vol_ratio": vol_ratio,
            "suspicious_split": suspicious,
        })

    out = pd.DataFrame(rows)
    print(f"{'sym':<8} {'date':<12} {'prev_C':>8} {'open':>8} {'close':>8} "
          f"{'gap':>8} {'vol_ratio':>10} {'flag':>10}")
    for _, r in out.sort_values("overnight_gap", ascending=False).iterrows():
        flag = " SUSPICIOUS" if r["suspicious_split"] else ""
        print(f"{r['symbol']:<8} {r['date']:<12} ${r['prev_close']:>7.2f} ${r['today_open']:>7.2f} ${r['today_close']:>7.2f} "
              f"{r['overnight_gap']*100:>+7.1f}% {r['vol_ratio']:>9.1f}x{flag}")

    suspicious = out[out["suspicious_split"]]
    print(f"\nSuspicious events (large gap + low volume): {len(suspicious)} / {len(out)}")
    if len(suspicious) > 0:
        print(suspicious[["symbol", "date", "prev_close", "today_open", "overnight_gap", "vol_ratio"]].to_string(index=False))

    # Cross-check with yfinance splits accessor for top suspicious
    print(f"\n{'=' * 78}")
    print("Cross-checking ALL events with yfinance .splits accessor (live API)")
    print(f"{'=' * 78}")
    print("Note: this fetches live from Yahoo, ~1s per ticker\n")

    split_results = []
    for _, ev in out.iterrows():
        sym = ev["symbol"]
        bdate = pd.Timestamp(ev["date"])
        try:
            t = yf.Ticker(sym)
            splits = t.splits
        except Exception as e:
            print(f"  {sym}: error fetching splits: {e}")
            continue

        # Splits within ±60 days of breakout
        if len(splits) > 0:
            window_lo = bdate - pd.Timedelta(days=60)
            window_hi = bdate + pd.Timedelta(days=60)
            # Splits index is timestamp; need to handle tz
            try:
                splits_in_window = splits[(splits.index.tz_localize(None) >= window_lo) &
                                          (splits.index.tz_localize(None) <= window_hi)]
            except Exception:
                splits_in_window = splits[(splits.index >= window_lo) & (splits.index <= window_hi)]
            if len(splits_in_window) > 0:
                for split_date, ratio in splits_in_window.items():
                    print(f"  ⚠️  {sym} on {ev['date']}: SPLIT {ratio:.4f} on {split_date.date()}")
                    split_results.append({
                        "symbol": sym, "breakout_date": ev["date"],
                        "split_date": split_date.strftime("%Y-%m-%d"), "ratio": float(ratio),
                    })
        time.sleep(0.3)

    if split_results:
        print(f"\nFound {len(split_results)} events near a split")
        sr = pd.DataFrame(split_results)
        sr.to_csv("breakout_split_check.csv", index=False)
        print(sr.to_string(index=False))
    else:
        print("\n✓ No splits found within ±60d of any breakout event.")
        print("  Combined with auto_adjust=True, the breakout signals are NOT split artifacts.")


if __name__ == "__main__":
    main()
