"""
Realistic breakout strategy validation.

Issues with previous analysis:
  1. Selection bias: only 28 events, dominated by huge winners (DFDV +900%)
  2. Did not test "buy NEXT day at open" — must include realistic entry
  3. Did not check what fraction of "sub-$1 stocks that ever broke $1.5" we captured

Now testing:
  1. Universe-wide search: ALL days where (was below $1 last 30d AND today close >= $1.5)
     Compute realistic next-day-open entry, with various exit strategies
  2. Lower breakout threshold to $1.2 to get more sample
  3. Check if smaller breakouts (just barely above $1) work or only big gaps
"""
import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt

DAILY_CACHE = Path("price_cache")


def main():
    # Test multiple breakout thresholds
    SLIP = 0.02  # 2% round-trip slippage for penny

    breakout_levels = [1.05, 1.10, 1.20, 1.30, 1.50, 2.00]
    cons_days = 30  # 30-day consolidation

    print(f"Universe-wide search: stocks below $1 for last {cons_days}d, then close >= breakout level")
    print(f"Entry: NEXT day at open (realistic)")
    print(f"Exit: hold 30 days then close")
    print(f"Slippage: {SLIP*100:.1f}% round-trip\n")

    rows = []
    csvs = sorted(DAILY_CACHE.glob("*.csv"))
    for f in csvs:
        sym = f.stem
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
        except Exception:
            continue
        if len(df) < cons_days + 35:
            continue
        df = df.sort_index()
        c = df["Close"].values
        o = df["Open"].values
        h = df["High"].values
        v = df["Volume"].values
        dates = df.index

        for i in range(cons_days, len(c) - 35):
            prior = c[i - cons_days : i]
            if not (prior < 1.0).all() or not (prior > 0).all():
                continue
            if v[i - cons_days : i].mean() < 10000:
                continue
            # Skip if previous day was already a breakout
            if i > 0 and c[i - 1] >= 1.05:
                continue

            # For each breakout level, was today a breakout?
            for blvl in breakout_levels:
                if c[i] >= blvl:
                    # Did NOT also break higher levels (so we count cleanly)
                    pass

            # Find which is the "highest level today reached"
            today_close = c[i]
            today_high = h[i]

            # Realistic entry: next day open
            if i + 1 >= len(c):
                continue
            entry = o[i + 1]
            if entry <= 0:
                continue

            # Exits at multiple horizons
            for horizon in [10, 30, 60, 90]:
                if i + horizon >= len(c):
                    continue
                exit_close = c[i + horizon]
                future_high = h[i + 1 : i + 1 + horizon].max()

            # Just record one row per event with horizon-specific data
            row = {
                "symbol": sym,
                "date": dates[i].strftime("%Y-%m-%d"),
                "today_close": today_close,
                "today_high": today_high,
                "consolidation_avg": prior.mean(),
                "next_open": entry,
            }
            for horizon in [10, 30, 60, 90]:
                if i + horizon < len(c):
                    row[f"exit_close_{horizon}d"] = c[i + horizon]
                    row[f"max_high_{horizon}d"] = h[i + 1 : i + 1 + horizon].max() if horizon > 0 else h[i]
            rows.append(row)

    df = pd.DataFrame(rows)
    df = df.dropna(subset=["next_open"])
    print(f"Total breakout events (any close >= $1.05): {len(df)}")

    if len(df) == 0:
        return

    # Stratify by today's close level
    print("\n" + "=" * 78)
    print("Stratified by today's close level (= breakout strength)")
    print("=" * 78)
    print(f"\n{'breakout_close':<22} {'N':>5} {'win_30d':>9} {'mean_30d':>10} {'median':>9} {'p10':>9} {'p90':>9}")

    BUCKETS = [
        (1.05, 1.20, "$1.05~$1.20 (weak)"),
        (1.20, 1.50, "$1.20~$1.50"),
        (1.50, 2.00, "$1.50~$2.00"),
        (2.00, 3.00, "$2.00~$3.00"),
        (3.00, 5.00, "$3.00~$5.00 (strong)"),
        (5.00, 100, "$5.00+ (huge gap)"),
    ]
    for lo, hi, label in BUCKETS:
        sub = df[(df["today_close"] >= lo) & (df["today_close"] < hi)].copy()
        if len(sub) == 0 or "exit_close_30d" not in sub.columns:
            continue
        sub = sub.dropna(subset=["exit_close_30d"])
        if len(sub) == 0:
            continue
        sub["ret_30d"] = sub["exit_close_30d"] / sub["next_open"] - 1.0 - SLIP
        wr = (sub["ret_30d"] > 0).mean()
        mean_ret = sub["ret_30d"].mean()
        med_ret = sub["ret_30d"].median()
        p10 = sub["ret_30d"].quantile(0.10)
        p90 = sub["ret_30d"].quantile(0.90)
        print(f"{label:<22} {len(sub):>5} {wr:>8.1%} {mean_ret:>+9.2%} {med_ret:>+8.2%} "
              f"{p10:>+8.2%} {p90:>+8.2%}")

    # Same with horizon 90d
    print(f"\n{'breakout_close':<22} {'N':>5} {'win_90d':>9} {'mean_90d':>10} {'median':>9} {'p10':>9} {'p90':>9}")
    for lo, hi, label in BUCKETS:
        sub = df[(df["today_close"] >= lo) & (df["today_close"] < hi)].copy()
        if "exit_close_90d" not in sub.columns:
            continue
        sub = sub.dropna(subset=["exit_close_90d"])
        if len(sub) == 0:
            continue
        sub["ret_90d"] = sub["exit_close_90d"] / sub["next_open"] - 1.0 - SLIP
        wr = (sub["ret_90d"] > 0).mean()
        mean_ret = sub["ret_90d"].mean()
        med_ret = sub["ret_90d"].median()
        p10 = sub["ret_90d"].quantile(0.10)
        p90 = sub["ret_90d"].quantile(0.90)
        print(f"{label:<22} {len(sub):>5} {wr:>8.1%} {mean_ret:>+9.2%} {med_ret:>+8.2%} "
              f"{p10:>+8.2%} {p90:>+8.2%}")

    # Test take-profit at +50% / stop-loss at -20% for each bucket
    print("\n" + "=" * 78)
    print("Strategy: Buy next-day open, take +50% TP, -20% SL, max hold 30d")
    print("=" * 78)
    print(f"\n{'breakout_close':<22} {'N':>5} {'win%':>7} {'mean':>8} {'median':>8} {'sum':>9}")

    csv_data = {}
    for f in csvs:
        sym = f.stem
        try:
            d = pd.read_csv(f, index_col=0, parse_dates=True).sort_index()
            csv_data[sym] = d
        except Exception:
            continue

    def simulate_tp_sl(df_event, tp=0.50, sl=0.20, max_hold=30):
        rets = []
        for _, ev in df_event.iterrows():
            sym = ev["symbol"]
            date = pd.Timestamp(ev["date"])
            d = csv_data.get(sym)
            if d is None: continue
            idx = d.index.searchsorted(date)
            if idx + 1 >= len(d):
                continue
            entry = float(d["Open"].iloc[idx + 1])
            if entry <= 0: continue
            tp_p = entry * (1 + tp)
            sl_p = entry * (1 - sl)
            ret = None
            for j in range(idx + 1, min(idx + 1 + max_hold, len(d))):
                hi = float(d["High"].iloc[j])
                lo = float(d["Low"].iloc[j])
                cl = float(d["Close"].iloc[j])
                op = float(d["Open"].iloc[j])
                if j == idx + 1:
                    if lo <= sl_p:
                        ret = -sl
                        break
                    if hi >= tp_p:
                        ret = tp
                        break
                else:
                    if op <= sl_p:
                        ret = op / entry - 1.0
                        break
                    if op >= tp_p:
                        ret = op / entry - 1.0
                        break
                    if lo <= sl_p and hi >= tp_p:
                        ret = -sl  # pessimistic
                        break
                    if lo <= sl_p:
                        ret = -sl
                        break
                    if hi >= tp_p:
                        ret = tp
                        break
            if ret is None:
                ret = float(d["Close"].iloc[min(idx + max_hold, len(d) - 1)]) / entry - 1.0
            rets.append(ret - SLIP)
        return rets

    for lo, hi, label in BUCKETS:
        sub = df[(df["today_close"] >= lo) & (df["today_close"] < hi)]
        if len(sub) == 0:
            continue
        rets = simulate_tp_sl(sub)
        if not rets:
            continue
        a = np.array(rets)
        print(f"{label:<22} {len(a):>5} {(a>0).mean():>6.1%} {a.mean():>+7.2%} "
              f"{np.median(a):>+7.2%} {a.sum():>+8.2f}")

    df.to_csv("breakout_universe.csv", index=False)
    print(f"\nSaved breakout_universe.csv ({len(df)} events)")


if __name__ == "__main__":
    main()
