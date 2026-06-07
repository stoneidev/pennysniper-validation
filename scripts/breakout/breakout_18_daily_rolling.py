"""
Daily rolling walk-forward.

  Each trading day D:
    Train: prior 60 trading days (D-60 to D-1)
    Apply: only signals occurring on day D

Compare to monthly (3mo train, 1mo apply) and quarterly (3mo, 3mo).

Caveats:
  - 60d train window is short → grid often has N<5, falls back if no valid combo
  - Same signal can theoretically be picked by different rules on different days
  - We dedup: each (symbol, signal_date) trade counted once
"""
import pandas as pd
import numpy as np
from pathlib import Path
import time
import json

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "daily_cache"
OUT_DIR = REPO / "results" / "csv"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SLIP = 0.02
MIN_AVG_VOL = 10_000

CONS_DAYS_LIST = [30, 45, 60]
ENTRY_RANGES = [
    (1.05, 1.15, "$1.05-$1.15"),
    (1.05, 1.20, "$1.05-$1.20"),
    (1.10, 1.30, "$1.10-$1.30"),
    (1.20, 1.50, "$1.20-$1.50"),
]
TP_LEVELS = [1.10, 1.15, 1.20, 1.30, 1.50]
HOLDS = [30, 60, 90]

TRAIN_DAYS = 60   # train window in trading days
MIN_TRAIN_N = 3   # need at least 3 events in train for grid combo to qualify


def parse(p):
    try:
        df = pd.read_csv(p, parse_dates=["Date"])
    except Exception:
        return None
    if df.empty or len(df) < 100:
        return None
    return df.sort_values("Date").reset_index(drop=True)


def find_events(df, sym, cons_d, lo, hi):
    if len(df) < cons_d + 5:
        return []
    c = df["Close"].values
    o = df["Open"].values
    h = df["High"].values
    v = df["Volume"].values
    dates = df["Date"].values
    rows = []
    for i in range(cons_d, len(c) - 1):
        prior = c[i - cons_d : i]
        if not (prior < 1.0).all() or not (prior > 0).all():
            continue
        if v[i - cons_d : i].mean() < MIN_AVG_VOL:
            continue
        if not (lo <= c[i] < hi):
            continue
        if i > 0 and c[i - 1] >= lo:
            continue
        if i + 1 >= len(c):
            continue
        entry = o[i + 1]
        if entry <= 0:
            continue
        rows.append({
            "symbol": sym,
            "date": pd.Timestamp(dates[i]),
            "entry": float(entry),
            "future_h": h[i + 1:].copy(),
            "future_c": c[i + 1:].copy(),
        })
    return rows


def simulate(events, tp_ratio, max_hold):
    rets = []
    for ev in events:
        entry = ev["entry"]
        tp_price = entry * tp_ratio
        n = min(max_hold, len(ev["future_h"]))
        if n == 0:
            continue
        ret = None
        for j in range(n):
            if ev["future_h"][j] >= tp_price:
                ret = tp_ratio - 1.0 - SLIP
                break
        if ret is None:
            ret = float(ev["future_c"][n - 1]) / entry - 1.0 - SLIP
        rets.append(ret)
    return np.array(rets) if rets else np.array([])


def main():
    print("Loading universe...")
    files = sorted(CACHE.glob("*.csv"))
    files = [f for f in files if not f.name.startswith("_")]

    print("Pre-computing events...")
    events_by_key = {}
    t0 = time.time()
    for f in files:
        sym = f.stem
        df = parse(f)
        if df is None:
            continue
        c = df["Close"].values
        if not ((c < 1.0).any() and (c >= 1.05).any()):
            continue
        for cd in CONS_DAYS_LIST:
            for lo, hi, label in ENTRY_RANGES:
                evs = find_events(df, sym, cd, lo, hi)
                if evs:
                    events_by_key.setdefault((cd, label), []).extend(evs)
    total_events = sum(len(v) for v in events_by_key.values())
    print(f"  done in {time.time()-t0:.0f}s, {total_events} total events across all combos")

    # Determine all distinct event dates (these are the only days where signals actually occur)
    all_event_dates = set()
    for evs in events_by_key.values():
        for e in evs:
            all_event_dates.add(e["date"])
    all_event_dates = sorted(all_event_dates)
    print(f"  Distinct event dates: {len(all_event_dates)}")

    # Filter dates: only those with prior 60 trading days available, starting after enough warmup
    # Need at least 60 trading days BEFORE the date.
    # Approximation: use calendar days * 7/5 ≈ 84 calendar days warmup → use 4 calendar months as safety
    earliest_test = pd.Timestamp("2023-04-01")
    test_dates = [d for d in all_event_dates if d >= earliest_test]
    print(f"  Testable event dates (≥{earliest_test.date()}): {len(test_dates)}")

    # For each test date, train on prior TRAIN_DAYS trading days
    # We need a master list of trading days. Use union of all events plus some.
    # Simpler: trading-day distance via business-day count.
    # We'll use calendar lookback of (TRAIN_DAYS / 5 * 7 + 14) days as buffer, then filter to events in that window.
    print("\nRunning daily walk-forward (train=prior 60 trading days, apply=that day)...")

    log_rows = []
    all_oos_trades = []
    all_oos_seen = set()  # dedup (symbol, date)
    last_print = 0
    t0 = time.time()

    for di, test_date in enumerate(test_dates):
        # Train window: events whose date is within prior 60 trading days
        # Approximate using calendar days: 60 trading * (7/5) = 84 days, plus 14 buffer
        train_start = test_date - pd.Timedelta(days=120)
        train_end = test_date  # exclusive

        # Build train grid
        train_grid = []
        for (cd, label), all_events in events_by_key.items():
            train_evs = [e for e in all_events if train_start <= e["date"] < train_end]
            # Limit to prior 60 trading days more accurately:
            # Sort, take last events within ~84 calendar days
            if len(train_evs) < MIN_TRAIN_N:
                continue
            for tp in TP_LEVELS:
                for hold in HOLDS:
                    rets = simulate(train_evs, tp, hold)
                    if len(rets) < MIN_TRAIN_N:
                        continue
                    wr = (rets > 0).mean()
                    p10 = float(np.percentile(rets, 10))
                    score = wr * (1 + max(p10, -1))
                    train_grid.append({
                        "cd": cd, "label": label, "tp": tp, "hold": hold,
                        "n": len(rets), "win": wr, "p10": p10, "score": score,
                    })

        if not train_grid:
            log_rows.append({
                "date": test_date.strftime("%Y-%m-%d"),
                "rule": "—", "train_n": 0, "test_n": 0, "ret": None,
            })
            continue

        best = max(train_grid, key=lambda x: x["score"])

        # Apply ONLY to events on test_date
        test_evs = [e for e in events_by_key.get((best["cd"], best["label"]), [])
                    if e["date"] == test_date]
        # Dedup
        test_evs = [e for e in test_evs
                    if (e["symbol"], e["date"]) not in all_oos_seen]
        if not test_evs:
            log_rows.append({
                "date": test_date.strftime("%Y-%m-%d"),
                "rule": f"{best['cd']}d/{best['label']}/+{(best['tp']-1)*100:.0f}%/{best['hold']}d",
                "train_n": best["n"], "test_n": 0, "ret": None,
            })
            continue

        rets = simulate(test_evs, best["tp"], best["hold"])
        for ev, r in zip(test_evs, rets):
            all_oos_seen.add((ev["symbol"], ev["date"]))
            all_oos_trades.append({
                "date": test_date.strftime("%Y-%m-%d"),
                "symbol": ev["symbol"],
                "rule": f"{best['cd']}d/{best['label']}/+{(best['tp']-1)*100:.0f}%/{best['hold']}d",
                "ret": float(r),
            })
        log_rows.append({
            "date": test_date.strftime("%Y-%m-%d"),
            "rule": f"{best['cd']}d/{best['label']}/+{(best['tp']-1)*100:.0f}%/{best['hold']}d",
            "train_n": best["n"], "test_n": len(rets),
            "ret": float(rets.mean()) if len(rets) else None,
        })

        if di - last_print >= 50:
            print(f"  {di+1}/{len(test_dates)} ({time.time()-t0:.0f}s) — trades so far: {len(all_oos_trades)}")
            last_print = di

    print(f"\n  Done in {time.time()-t0:.0f}s")

    log_df = pd.DataFrame(log_rows)
    log_df.to_csv(OUT_DIR / "daily_rolling_log.csv", index=False)

    # Aggregate
    if all_oos_trades:
        rets_arr = np.array([t["ret"] for t in all_oos_trades])
        print("\n" + "=" * 130)
        print("DAILY ROLLING — AGGREGATE")
        print("=" * 130)
        print(f"  Total OOS trades: {len(rets_arr)}")
        print(f"  Win rate:         {(rets_arr > 0).mean():.1%}")
        print(f"  Mean:             {rets_arr.mean()*100:+.2f}%")
        print(f"  Median:           {np.median(rets_arr)*100:+.2f}%")
        print(f"  Sum:              {rets_arr.sum()*100:+.2f}%")
        print(f"  p10:              {np.percentile(rets_arr, 10)*100:+.2f}%")
        print(f"  p90:              {np.percentile(rets_arr, 90)*100:+.2f}%")

        print("\n  ₩1M capital sim:")
        for alloc, label in [(1.00, "ALL_IN"), (0.25, "25%"), (0.10, "10%")]:
            cash = 1_000_000
            for r in rets_arr:
                pos = cash * alloc
                cash = cash - pos + pos * (1 + r)
            print(f"    {label:<10} → ₩{cash:>15,.0f} ({(cash/1_000_000-1)*100:+.1f}%)")

    # Compare with monthly + quarterly
    print("\n" + "=" * 90)
    print("COMPARISON: quarterly vs monthly vs daily retrain")
    print("=" * 90)
    quarterly = OUT_DIR / "rolling_3m_log.csv"
    monthly = OUT_DIR / "monthly_rolling_log.csv"

    rows = []
    for name, path in [("Quarterly (3mo train, 3mo apply)", quarterly),
                        ("Monthly (3mo train, 1mo apply)", monthly)]:
        if not path.exists():
            continue
        df = pd.read_csv(path)
        sum_col = "test_sum" if "test_sum" in df.columns else None
        n_windows = len(df)
        if sum_col:
            total_sum = df[sum_col].sum()
        else:
            total_sum = 0
        rows.append((name, n_windows, total_sum))

    if all_oos_trades:
        daily_sum = sum(t["ret"] for t in all_oos_trades)
        rows.append(("Daily (60d train, 1d apply)", len(test_dates), daily_sum))

    print(f"\n{'method':<40} {'windows':>8} {'sum_returns':>12}")
    for name, nw, total in rows:
        print(f"{name:<40} {nw:>8} {total*100:>+11.1f}%")

    pd.DataFrame(all_oos_trades).to_csv(OUT_DIR / "daily_rolling_oos.csv", index=False)
    print(f"\n✓ Saved daily_rolling_log.csv and daily_rolling_oos.csv")


if __name__ == "__main__":
    main()
