"""
Rolling 3-month walk-forward optimization.

Idea: every 3 months, re-optimize rule based on last 3 months → apply to next 3 months.

Windows (training period → test period):
  [2023.01-03] → [2023.04-06]
  [2023.04-06] → [2023.07-09]
  [2023.07-09] → [2023.10-12]
  [2023.10-12] → [2024.01-03]
  ...
  [2026.01-03] → [2026.04-06]

Each window:
  1. Grid search on training data: cons × entry_range × tp_ratio × hold
  2. Pick best by win_rate × (1 + p10)
  3. Apply chosen params to test period
  4. Record OOS results

Aggregate all OOS results → true rolling walk-forward performance.

Filter: warrants/rights/units excluded (W, R, U, Z suffix).
Min N for grid: 5 (low because 3 months is short).
"""
import pandas as pd
import numpy as np
from pathlib import Path
import time

STOOQ_DIR = Path("/Users/stoni/Downloads/data/daily/us/nasdaq stocks")
OUT_DIR = Path("/Users/stoni/Downloads/pennysniper_validation/results/csv")

START_DATE = pd.Timestamp("2022-06-01")  # need buffer for 60d cons before first window
SLIP = 0.02
MIN_AVG_VOL = 10_000

# Smaller grid (3 months → fewer events → can't search too much)
CONS_DAYS_LIST = [30, 45, 60]
ENTRY_RANGES = [
    (1.05, 1.15, "$1.05-$1.15"),
    (1.05, 1.20, "$1.05-$1.20"),
    (1.10, 1.30, "$1.10-$1.30"),
    (1.20, 1.50, "$1.20-$1.50"),
]
TP_LEVELS = [1.10, 1.15, 1.20, 1.30, 1.50]
HOLDS = [30, 60, 90]

EXCLUDE_SUFFIX = ("W", "R", "U", "Z")


def parse_csv(path):
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    if df.empty or "<DATE>" not in df.columns:
        return None
    df = df.rename(columns={
        "<DATE>": "date", "<OPEN>": "Open", "<HIGH>": "High",
        "<LOW>": "Low", "<CLOSE>": "Close", "<VOL>": "Volume",
    })
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df[df["date"] >= START_DATE].dropna(subset=["Open", "High", "Low", "Close"])
    if len(df) < 100:
        return None
    return df.sort_values("date").reset_index(drop=True)


def is_excluded(sym):
    if sym.endswith(EXCLUDE_SUFFIX):
        return True
    if len(sym) > 4 and sym[-3:].startswith("PR"):
        return True
    return False


def find_events(df, symbol, cons_days, entry_lo, entry_hi):
    if len(df) < cons_days + 5:
        return []
    c = df["Close"].values
    o = df["Open"].values
    h = df["High"].values
    v = df["Volume"].values
    dates = df["date"].values
    rows = []
    for i in range(cons_days, len(c) - 1):
        prior = c[i - cons_days : i]
        if not (prior < 1.0).all() or not (prior > 0).all():
            continue
        if v[i - cons_days : i].mean() < MIN_AVG_VOL:
            continue
        if not (entry_lo <= c[i] < entry_hi):
            continue
        if i > 0 and c[i - 1] >= entry_lo:
            continue
        if i + 1 >= len(c):
            continue
        entry = o[i + 1]
        if entry <= 0:
            continue
        rows.append({
            "symbol": symbol,
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
        future_h = ev["future_h"]
        future_c = ev["future_c"]
        n = min(max_hold, len(future_h))
        if n == 0:
            continue
        ret = None
        for j in range(n):
            if future_h[j] >= tp_price:
                ret = tp_ratio - 1.0 - SLIP
                break
        if ret is None:
            ret = float(future_c[n - 1]) / entry - 1.0 - SLIP
        rets.append(ret)
    return np.array(rets) if rets else np.array([])


def main():
    print("Loading universe...")
    csv_files = []
    for d in STOOQ_DIR.iterdir():
        if d.is_dir():
            csv_files.extend(d.glob("*.txt"))

    # Pre-load all events (this is expensive but done once)
    print("Pre-computing events for all (cons, entry_range) combos...")
    events_by_key = {}
    t0 = time.time()
    n_loaded = 0
    for i, f in enumerate(csv_files):
        sym = f.stem.upper().replace(".US", "")
        if is_excluded(sym):
            continue
        df = parse_csv(f)
        if df is None:
            continue
        n_loaded += 1
        c = df["Close"].values
        if not ((c < 1.0).any() and (c >= 1.05).any()):
            continue
        for cd in CONS_DAYS_LIST:
            for lo, hi, label in ENTRY_RANGES:
                events = find_events(df, sym, cd, lo, hi)
                if events:
                    events_by_key.setdefault((cd, label), []).extend(events)
        if (i + 1) % 1000 == 0:
            print(f"  {i+1}/{len(csv_files)} ({time.time()-t0:.0f}s)")

    print(f"Done in {time.time()-t0:.0f}s. Loaded {n_loaded} stocks.")
    print(f"\nTotal events per key:")
    for k in sorted(events_by_key.keys()):
        print(f"  {k}: {len(events_by_key[k])}")

    # ====================================================================
    # Build rolling 3-month windows
    # ====================================================================
    # Quarters from 2023 Q1 to 2026 Q2
    quarters = pd.date_range("2023-01-01", "2026-04-01", freq="QS").tolist()
    # Each window: train = quarter q, test = quarter q+1
    print(f"\nRolling windows: {len(quarters)-1}")

    aggregated_oos_rets = []
    chosen_params_log = []

    for i in range(len(quarters) - 1):
        train_start = quarters[i]
        train_end = quarters[i + 1]  # exclusive
        if i + 2 >= len(quarters):
            break
        test_start = quarters[i + 1]
        test_end = quarters[i + 2]

        # Grid search on train period
        train_grid = []
        for (cd, entry_label), all_events in events_by_key.items():
            train_evs = [e for e in all_events if train_start <= e["date"] < train_end]
            if len(train_evs) < 5:
                continue
            for tp in TP_LEVELS:
                for hold in HOLDS:
                    rets = simulate(train_evs, tp, hold)
                    if len(rets) < 5:
                        continue
                    wr = (rets > 0).mean()
                    p10 = np.percentile(rets, 10)
                    score = wr * (1 + max(p10, -1))
                    train_grid.append({
                        "cons_d": cd, "entry_range": entry_label,
                        "tp_ratio": tp, "hold": hold,
                        "n": len(rets), "win_rate": wr, "mean": rets.mean(),
                        "p10": p10, "score": score,
                    })
        if not train_grid:
            print(f"  Window {i+1}: no train data, skipping")
            continue

        train_df = pd.DataFrame(train_grid)
        # Best by score
        best = train_df.nlargest(1, "score").iloc[0]
        best_cd = int(best["cons_d"])
        best_label = best["entry_range"]
        best_tp = best["tp_ratio"]
        best_hold = int(best["hold"])

        # Apply to test period
        all_events = events_by_key.get((best_cd, best_label), [])
        test_evs = [e for e in all_events if test_start <= e["date"] < test_end]
        if len(test_evs) == 0:
            test_rets = np.array([])
        else:
            test_rets = simulate(test_evs, best_tp, best_hold)

        chosen_params_log.append({
            "train_period": f"{train_start.date()}_{train_end.date()}",
            "test_period": f"{test_start.date()}_{test_end.date()}",
            "cons_d": best_cd,
            "entry_range": best_label,
            "tp_ratio": best_tp,
            "hold": best_hold,
            "train_n": int(best["n"]),
            "train_win": best["win_rate"],
            "train_score": best["score"],
            "test_n": len(test_rets),
            "test_win": (test_rets > 0).mean() if len(test_rets) > 0 else None,
            "test_mean": test_rets.mean() if len(test_rets) > 0 else None,
            "test_sum": test_rets.sum() if len(test_rets) > 0 else 0.0,
        })

        for r in test_rets:
            aggregated_oos_rets.append({
                "test_period": f"{test_start.date()}_{test_end.date()}",
                "ret": r,
            })

    log_df = pd.DataFrame(chosen_params_log)
    log_df.to_csv(OUT_DIR / "rolling_3m_log.csv", index=False)

    print("\n" + "=" * 130)
    print("Rolling 3-month walk-forward results")
    print("=" * 130)
    print(f"\n{'train':<24} {'test':<24} {'cons':>4} {'entry':>14} {'TP':>6} {'hold':>5} | "
          f"{'TR_n':>4} {'TR_win':>6} | {'TS_n':>4} {'TS_win':>6} {'TS_mean':>7} {'TS_sum':>7}")
    print("-" * 130)
    for _, r in log_df.iterrows():
        tp_s = "+%.0f%%" % ((r["tp_ratio"] - 1) * 100)
        ts_win_s = f"{r['test_win']:.1%}" if r["test_win"] is not None and not pd.isna(r["test_win"]) else "—"
        ts_mean_s = f"{r['test_mean']:+.2%}" if r["test_mean"] is not None and not pd.isna(r["test_mean"]) else "—"
        ts_sum_s = f"{r['test_sum']:+.2f}" if not pd.isna(r["test_sum"]) else "—"
        print(f"{r['train_period']:<24} {r['test_period']:<24} "
              f"{r['cons_d']:>3}d {r['entry_range']:>14} {tp_s:>6} {r['hold']:>3}d | "
              f"{r['train_n']:>4} {r['train_win']:>5.1%} | "
              f"{r['test_n']:>4} {ts_win_s:>6} {ts_mean_s:>7} {ts_sum_s:>7}")

    # Aggregate
    if aggregated_oos_rets:
        agg = pd.DataFrame(aggregated_oos_rets)
        all_rets = agg["ret"].values
        print(f"\n{'=' * 130}")
        print("AGGREGATE: all OOS trades across all rolling windows")
        print(f"{'=' * 130}")
        print(f"  Total trades: {len(all_rets)}")
        print(f"  Win rate:     {(all_rets > 0).mean():.1%}")
        print(f"  Mean:         {all_rets.mean():+.2%}")
        print(f"  Median:       {np.median(all_rets):+.2%}")
        print(f"  Sum:          {all_rets.sum():+.4f}")
        print(f"  p10:          {np.percentile(all_rets, 10):+.2%}")
        print(f"  p90:          {np.percentile(all_rets, 90):+.2%}")

        # Capital sim
        # Sequential, 25% allocation
        cash = 1_000_000
        for r in all_rets:
            position = cash * 0.25
            cash = cash - position + position * (1 + r)
        print(f"\n  ₩1,000,000 sequential 25% allocation: ₩{cash:,.0f} ({(cash/1_000_000-1)*100:+.1f}%)")

        # All-in sequential (ignore overlap, just sequential compounding)
        cash = 1_000_000
        for r in all_rets:
            cash *= (1 + r)
        print(f"  ₩1,000,000 ALL-IN sequential:        ₩{cash:,.0f} ({(cash/1_000_000-1)*100:+.1f}%)")

        agg.to_csv(OUT_DIR / "rolling_3m_aggregated.csv", index=False)
    else:
        print("\nNo OOS trades collected.")


if __name__ == "__main__":
    main()
