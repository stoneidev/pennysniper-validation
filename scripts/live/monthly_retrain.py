"""
Monthly rule retraining (Option A — wide grid + strict filter).

Re-optimizes the breakout rule using the most recent 3-month period
ending at the prior month boundary, then applies to the current month.

Selection rule (Option A, validated on 8.5y backtest):
  - candidate must satisfy: train win_rate ≥ 80% AND mean ≥ 0 AND N ≥ 5
  - tiebreaker: maximize  mean_return × sqrt(N)
  - if no candidate passes → no rule written (system trades nothing this month)

Wide grid:
  - cons_days:   30 / 45 / 60
  - sub_levels:  $1.0 / $1.5 / $2.0  (consolidation top — auto-adapts to market level)
  - entry_ranges: 10 bands from $1.05 to $5.00
  - tp_ratio:    1.10 / 1.15 / 1.20 / 1.30 / 1.50
  - hold:        30 / 60 / 90

Reads:  data/daily_cache/{TICKER}.csv  (from fetch_universe.py)
Writes: config/current_rule.json
"""
import json
import sys
from pathlib import Path
import argparse
import pandas as pd
import numpy as np

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "daily_cache"
CONFIG = REPO / "config" / "current_rule.json"
CONFIG.parent.mkdir(exist_ok=True)

SLIP = 0.02
MIN_AVG_VOL = 10_000

# Selection filter
MIN_TRAIN_N = 5
MIN_WINRATE = 0.80
MIN_MEAN = 0.0

CONS_DAYS_LIST = [30, 45, 60]
SUB_LEVELS = [1.0, 1.5, 2.0]   # consolidation top
ENTRY_RANGES = [
    # low zone
    (1.05, 1.15, "$1.05-$1.15"),
    (1.05, 1.20, "$1.05-$1.20"),
    (1.10, 1.30, "$1.10-$1.30"),
    (1.20, 1.50, "$1.20-$1.50"),
    # mid zone (mania-friendly)
    (1.50, 1.80, "$1.50-$1.80"),
    (1.50, 2.00, "$1.50-$2.00"),
    (2.00, 2.50, "$2.00-$2.50"),
    (2.00, 3.00, "$2.00-$3.00"),
    # high zone
    (3.00, 4.00, "$3.00-$4.00"),
    (3.00, 5.00, "$3.00-$5.00"),
]
TP_LEVELS = [1.10, 1.15, 1.20, 1.30, 1.50]
HOLDS = [30, 60, 90]


def parse_csv(path):
    try:
        df = pd.read_csv(path, parse_dates=["Date"])
    except Exception:
        return None
    if df.empty or len(df) < 65:
        return None
    return df.sort_values("Date").reset_index(drop=True)


def find_events(df, sym, cons_days, sub_level, entry_lo, entry_hi):
    """
    Find events where:
      - prior cons_days closes < sub_level (consolidation under top)
      - today close in [entry_lo, entry_hi)
      - prev close < entry_lo (= today is the first breakout above entry_lo)
      - cons-period avg volume >= MIN_AVG_VOL
    """
    if len(df) < cons_days + 5:
        return []
    c = df["Close"].values
    o = df["Open"].values
    h = df["High"].values
    v = df["Volume"].values
    dates = df["Date"].values
    rows = []
    for i in range(cons_days, len(c) - 1):
        prior = c[i - cons_days : i]
        if not (prior < sub_level).all() or not (prior > 0).all():
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


def get_month_window(today=None):
    """Return (train_start, train_end, valid_until) for the month containing 'today'.
       Train = prior 3 months. Apply = current calendar month."""
    today = today or pd.Timestamp.now().normalize()
    month_start = pd.Timestamp(year=today.year, month=today.month, day=1)
    train_start = month_start - pd.DateOffset(months=3)
    train_end = month_start
    valid_until = month_start + pd.DateOffset(months=1) - pd.Timedelta(days=1)
    return train_start, train_end, valid_until


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", type=str, default=None,
                        help="Override 'today' date (YYYY-MM-DD) to retrain for a past quarter")
    parser.add_argument("--out", type=str, default=str(CONFIG),
                        help="Output path for rule json")
    args = parser.parse_args()

    today = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp.now()
    out_path = Path(args.out)

    train_start, train_end, valid_until = get_month_window(today)
    print(f"Today / as-of: {today.date()}")
    print(f"Training window: {train_start.date()} ~ {train_end.date()}")
    print(f"Rule will be valid until: {valid_until.date()}")

    csv_files = sorted(CACHE.glob("*.csv"))
    csv_files = [f for f in csv_files if not f.name.startswith("_")]
    print(f"\nUniverse: {len(csv_files)} cached tickers")
    if len(csv_files) == 0:
        print("ERROR: no cached price data. Run fetch_universe.py first.")
        sys.exit(1)

    # Build events for every (cons, sub, entry_range) combo
    events_by_key = {}
    for f in csv_files:
        sym = f.stem
        df = parse_csv(f)
        if df is None:
            continue
        # quick bail-out: only stocks with ANY traded sub-$5 history
        c = df["Close"].values
        if not (c < 5.0).any():
            continue
        for cd in CONS_DAYS_LIST:
            for sub in SUB_LEVELS:
                for lo, hi, label in ENTRY_RANGES:
                    if lo < sub:        # entry must be above consolidation top
                        continue
                    if hi > 5.0:
                        continue
                    events = find_events(df, sym, cd, sub, lo, hi)
                    if events:
                        events_by_key.setdefault((cd, sub, label, lo, hi), []).extend(events)

    # Strict-filter grid search on training window
    candidates = []
    for (cd, sub, label, lo, hi), all_events in events_by_key.items():
        train_evs = [e for e in all_events if train_start <= e["date"] < train_end]
        if len(train_evs) < MIN_TRAIN_N:
            continue
        for tp in TP_LEVELS:
            for hold in HOLDS:
                rets = simulate(train_evs, tp, hold)
                if len(rets) < MIN_TRAIN_N:
                    continue
                wr = (rets > 0).mean()
                mean_ret = float(rets.mean())
                # STRICT FILTER (Option A)
                if wr < MIN_WINRATE:
                    continue
                if mean_ret < MIN_MEAN:
                    continue
                p10 = float(np.percentile(rets, 10))
                score = mean_ret * np.sqrt(len(rets))
                candidates.append({
                    "cons_d": cd, "sub_level": sub, "entry_range": label,
                    "entry_lo": lo, "entry_hi": hi,
                    "tp_ratio": tp, "hold": hold,
                    "n": len(rets), "win_rate": wr,
                    "mean": mean_ret, "p10": p10, "score": score,
                })

    if not candidates:
        # No combo passes the strict filter → don't write a rule.
        # Live system will skip trading until next month's retrain finds a passing combo.
        print("\nNo qualifying candidate (win_rate ≥ 80% AND mean ≥ 0 AND N ≥ 5).")
        print("This month: SKIP trading (capital preservation).")
        rule = {
            "skip_trading": True,
            "reason": "no candidate passed strict filter",
            "valid_from": train_end.strftime("%Y-%m-%d"),
            "valid_until": valid_until.strftime("%Y-%m-%d"),
            "trained_on_period": f"{train_start.date()}_{train_end.date()}",
            "generated_at": pd.Timestamp.now().isoformat(),
        }
        out_path.parent.mkdir(exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(rule, f, indent=2)
        print(f"✓ Saved skip-marker to {out_path}")
        return

    g = pd.DataFrame(candidates).nlargest(10, "score")
    print(f"\nTop 10 candidates (filter passed: win≥{MIN_WINRATE*100:.0f}%, mean≥{MIN_MEAN*100:.0f}%, N≥{MIN_TRAIN_N}):")
    print(f"{'cons':>4} {'sub':>5} {'entry':>14} {'TP':>6} {'hold':>5} {'N':>4} {'win%':>6} {'mean':>7} {'p10':>7}")
    for _, r in g.iterrows():
        tp_s = "+%.0f%%" % ((r["tp_ratio"] - 1) * 100)
        print(f"{int(r['cons_d']):>3}d ${r['sub_level']:>3.1f} {r['entry_range']:>14} {tp_s:>6} {int(r['hold']):>3}d "
              f"{int(r['n']):>4} {r['win_rate']:>5.1%} {r['mean']*100:>+6.1f}% {r['p10']:>+6.1%}")

    best = g.iloc[0]
    rule = {
        "cons_d": int(best["cons_d"]),
        "sub_level": float(best["sub_level"]),
        "entry_lo": float(best["entry_lo"]),
        "entry_hi": float(best["entry_hi"]),
        "tp_ratio": float(best["tp_ratio"]),
        "hold_d": int(best["hold"]),
        "valid_from": train_end.strftime("%Y-%m-%d"),
        "valid_until": valid_until.strftime("%Y-%m-%d"),
        "trained_on_period": f"{train_start.date()}_{train_end.date()}",
        "train_n": int(best["n"]),
        "train_win_rate": float(best["win_rate"]),
        "train_mean_return": float(best["mean"]),
        "train_p10": float(best["p10"]),
        "generated_at": pd.Timestamp.now().isoformat(),
    }

    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(rule, f, indent=2)
    print(f"\n✓ Saved {out_path}")
    print(f"\nNew rule: cons {rule['cons_d']}d / sub ${rule['sub_level']:.1f} / "
          f"entry [${rule['entry_lo']:.2f}, ${rule['entry_hi']:.2f}) / "
          f"TP +{(rule['tp_ratio']-1)*100:.0f}% / hold {rule['hold_d']}d")


if __name__ == "__main__":
    main()
