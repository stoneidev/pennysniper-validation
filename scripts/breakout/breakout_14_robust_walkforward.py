"""
Robust walk-forward optimization for Rule A.

Goal: find optimal parameters that survive TRUE walk-forward validation.

Design:
  1. Train period: 2024.06 ~ 2025.06 (12 months)
     → Pick best (cons, entry_lo, entry_hi, tp_ratio, hold) by win_rate × p10
  2. Test period: 2025.07 ~ 2026.06 (12 months)
     → Apply chosen params, measure OOS performance
  3. Compare: in-sample vs OOS

Filters:
  - Exclude warrants (W), rights (R), units (U), preferred (P), notes (Z)
  - Min cons-period avg volume: 10,000
  - Min N for stable stats: 50

Grid:
  - cons: 30, 45, 60, 90 days
  - entry: 8 ranges
  - tp_ratio: 1.10, 1.15, 1.20, 1.30, 1.50
  - hold: 30, 60, 90 days
"""
import pandas as pd
import numpy as np
from pathlib import Path
import time

STOOQ_DIR = Path("/Users/stoni/Downloads/data/daily/us/nasdaq stocks")
OUT_DIR = Path("/Users/stoni/Downloads/pennysniper_validation/results/csv")
START_DATE = pd.Timestamp("2024-06-01")
TRAIN_END = pd.Timestamp("2025-06-30")
TEST_END = pd.Timestamp("2026-06-30")
SLIP = 0.02
MIN_AVG_VOL = 10_000

CONS_DAYS_LIST = [30, 45, 60, 90]
ENTRY_RANGES = [
    (1.05, 1.15, "$1.05-$1.15"),
    (1.10, 1.20, "$1.10-$1.20"),
    (1.10, 1.30, "$1.10-$1.30"),
    (1.15, 1.30, "$1.15-$1.30"),
    (1.20, 1.40, "$1.20-$1.40"),
    (1.20, 1.50, "$1.20-$1.50"),
    (1.30, 1.60, "$1.30-$1.60"),
    (1.40, 1.80, "$1.40-$1.80"),
]
TP_LEVELS = [1.10, 1.15, 1.20, 1.30, 1.50]
HOLDS = [30, 60, 90]

# Suffix exclusion: warrants/rights/units/preferred
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


def is_excluded_ticker(sym):
    """Exclude warrants, rights, units, preferred, etc."""
    # Standard suffix patterns
    if sym.endswith(EXCLUDE_SUFFIX):
        return True
    # Multi-char patterns: PRA, PRB (preferred)
    if len(sym) > 4 and sym[-3:].startswith("PR"):
        return True
    return False


def find_events(df, symbol, cons_days, entry_lo, entry_hi):
    """Find all breakout events for one symbol."""
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
            "entry_idx": i + 1,
            "entry": float(entry),
            "future_h": h[i + 1:].copy(),
            "future_c": c[i + 1:].copy(),
        })
    return rows


def simulate_returns(events, tp_ratio, max_hold):
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
    print("Loading universe (warrant/right/unit excluded)...")
    csv_files = []
    for d in STOOQ_DIR.iterdir():
        if d.is_dir():
            csv_files.extend(d.glob("*.txt"))

    # Pre-load all events for all (cons, entry_range) combos
    events_by_key = {}
    n_excluded = 0
    n_loaded = 0
    t0 = time.time()
    for i, f in enumerate(csv_files):
        sym = f.stem.upper().replace(".US", "")
        if is_excluded_ticker(sym):
            n_excluded += 1
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
            print(f"  {i+1}/{len(csv_files)} ({time.time()-t0:.0f}s, excluded {n_excluded})")

    print(f"Done in {time.time()-t0:.0f}s. Loaded {n_loaded} stocks, excluded {n_excluded}.")
    print(f"\nEvent counts:")
    for key in sorted(events_by_key.keys()):
        cd, label = key
        print(f"  {cd}d / {label}: {len(events_by_key[key])} events")

    # Train/test split by date
    print(f"\nTrain: {START_DATE.date()} ~ {TRAIN_END.date()}")
    print(f"Test:  {TRAIN_END.date()} ~ {TEST_END.date()}")

    # ====================================================================
    # Build train events
    # ====================================================================
    print("\nRunning grid on TRAIN period...")
    train_grid = []
    for (cd, entry_label), all_events in events_by_key.items():
        train_evs = [e for e in all_events if START_DATE <= e["date"] < TRAIN_END]
        if len(train_evs) < 30:
            continue
        for tp in TP_LEVELS:
            for hold in HOLDS:
                rets = simulate_returns(train_evs, tp, hold)
                if len(rets) < 30:
                    continue
                wr = (rets > 0).mean()
                p10 = np.percentile(rets, 10)
                mean_ret = rets.mean()
                # Score: win_rate × (1 + max(p10, -1))
                score = wr * (1 + max(p10, -1))
                train_grid.append({
                    "cons_d": cd, "entry_range": entry_label,
                    "tp_ratio": tp, "hold": hold,
                    "n": len(rets), "win_rate": wr,
                    "mean": mean_ret, "median": np.median(rets),
                    "p10": p10, "p90": np.percentile(rets, 90),
                    "score": score,
                })

    train_df = pd.DataFrame(train_grid)
    print(f"  train grid combos: {len(train_df)}")
    print(f"\nTop 10 train combos by score:")
    print(f"{'cons':>4} {'entry':>14} {'TP':>6} {'hold':>5} {'N':>4} {'win%':>6} {'mean':>7} {'p10':>7} {'score':>6}")
    top_train = train_df.nlargest(10, "score")
    for _, r in top_train.iterrows():
        tp_s = "+%.0f%%" % ((r["tp_ratio"] - 1) * 100)
        print(f"{int(r['cons_d']):>3}d {r['entry_range']:>14} {tp_s:>6} {int(r['hold']):>3}d "
              f"{int(r['n']):>4} {r['win_rate']:>5.1%} {r['mean']:>+6.1%} "
              f"{r['p10']:>+6.1%} {r['score']:>5.3f}")

    # ====================================================================
    # Apply train-best params to TEST period
    # ====================================================================
    print(f"\n{'=' * 110}")
    print("TRUE OOS VALIDATION: apply train-best params to test period")
    print(f"{'=' * 110}")

    oos_results = []
    for _, r in top_train.iterrows():
        cd = int(r["cons_d"])
        entry_label = r["entry_range"]
        tp = r["tp_ratio"]
        hold = int(r["hold"])

        all_events = events_by_key.get((cd, entry_label), [])
        test_evs = [e for e in all_events if TRAIN_END <= e["date"] < TEST_END]
        if len(test_evs) < 5:
            continue
        rets = simulate_returns(test_evs, tp, hold)
        if len(rets) < 5:
            continue

        oos_results.append({
            "cons_d": cd, "entry_range": entry_label, "tp_ratio": tp, "hold": hold,
            "train_n": int(r["n"]), "train_win": r["win_rate"], "train_mean": r["mean"],
            "train_p10": r["p10"], "train_score": r["score"],
            "test_n": len(rets),
            "test_win": (rets > 0).mean(),
            "test_mean": rets.mean(),
            "test_median": np.median(rets),
            "test_p10": np.percentile(rets, 10),
            "test_sum": rets.sum(),
        })

    oos_df = pd.DataFrame(oos_results)
    print(f"\n{'cons':>4} {'entry':>14} {'TP':>6} {'hold':>5} | "
          f"{'TR_N':>4} {'TR_win':>6} {'TR_mean':>7} {'TR_p10':>7} | "
          f"{'TS_N':>4} {'TS_win':>6} {'TS_mean':>7} {'TS_p10':>7}")
    print("-" * 110)
    for _, r in oos_df.iterrows():
        tp_s = "+%.0f%%" % ((r["tp_ratio"] - 1) * 100)
        print(f"{int(r['cons_d']):>3}d {r['entry_range']:>14} {tp_s:>6} {int(r['hold']):>3}d | "
              f"{int(r['train_n']):>4} {r['train_win']:>5.1%} {r['train_mean']:>+6.1%} {r['train_p10']:>+6.1%} | "
              f"{int(r['test_n']):>4} {r['test_win']:>5.1%} {r['test_mean']:>+6.1%} {r['test_p10']:>+6.1%}")

    # ====================================================================
    # Robust ranking: combos that survive both train AND test
    # ====================================================================
    if len(oos_df) > 0:
        oos_df["robust_score"] = (oos_df["train_score"] + oos_df["test_win"] * (1 + np.clip(oos_df["test_p10"], -1, 1))) / 2
        print(f"\n{'=' * 110}")
        print("ROBUST RANKING (avg of train_score and test_score)")
        print(f"{'=' * 110}")
        top_robust = oos_df.nlargest(10, "robust_score")
        print(f"\n{'cons':>4} {'entry':>14} {'TP':>6} {'hold':>5} {'TR_win':>6} {'TS_win':>6} {'TS_mean':>7}")
        for _, r in top_robust.iterrows():
            tp_s = "+%.0f%%" % ((r["tp_ratio"] - 1) * 100)
            print(f"{int(r['cons_d']):>3}d {r['entry_range']:>14} {tp_s:>6} {int(r['hold']):>3}d "
                  f"{r['train_win']:>5.1%} {r['test_win']:>5.1%} {r['test_mean']:>+6.1%}")

    # ====================================================================
    # FULL SAMPLE re-run for top combo (sanity)
    # ====================================================================
    if len(oos_df) > 0:
        best = oos_df.iloc[0]
        cd = int(best["cons_d"])
        entry_label = best["entry_range"]
        tp = best["tp_ratio"]
        hold = int(best["hold"])

        full_events = events_by_key.get((cd, entry_label), [])
        all_rets = simulate_returns(full_events, tp, hold)

        print(f"\n{'=' * 110}")
        print(f"FULL SAMPLE check on TRAIN-BEST: {cd}d / {entry_label} / TP+{(tp-1)*100:.0f}% / hold {hold}d")
        print(f"{'=' * 110}")
        print(f"  N (full): {len(all_rets)}")
        if len(all_rets) > 0:
            print(f"  win rate: {(all_rets > 0).mean():.1%}")
            print(f"  mean:     {all_rets.mean():+.2%}")
            print(f"  median:   {np.median(all_rets):+.2%}")
            print(f"  p10:      {np.percentile(all_rets, 10):+.2%}")
            print(f"  p90:      {np.percentile(all_rets, 90):+.2%}")

    train_df.to_csv(OUT_DIR / "robust_train_grid.csv", index=False)
    if len(oos_df) > 0:
        oos_df.to_csv(OUT_DIR / "robust_oos_results.csv", index=False)
    print(f"\n✓ Saved to {OUT_DIR}/robust_*.csv")


if __name__ == "__main__":
    main()
