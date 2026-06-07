"""
Quarterly rule retraining.

Re-optimizes the breakout rule using the most recent 3-month data
and writes it to config/current_rule.json.

Usage:
  # Run on the 1st of each quarter (Jan/Apr/Jul/Oct)
  0 6 1 1,4,7,10 *  cd /path/to/repo && python scripts/live/quarterly_retrain.py
"""
import json
from pathlib import Path
import pandas as pd
import numpy as np

REPO = Path(__file__).resolve().parents[2]
STOOQ_DIR = Path("/Users/stoni/Downloads/data/daily/us/nasdaq stocks")
CONFIG = REPO / "config" / "current_rule.json"
(REPO / "config").mkdir(exist_ok=True)

START_DATE = pd.Timestamp("2024-06-01")
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


def is_excluded(s):
    if s.endswith(EXCLUDE_SUFFIX):
        return True
    if len(s) > 4 and s[-3:].startswith("PR"):
        return True
    return False


def find_events(df, sym, cons_days, entry_lo, entry_hi):
    if len(df) < cons_days + 5:
        return []
    c, o, h, v, dates = df["Close"].values, df["Open"].values, df["High"].values, df["Volume"].values, df["date"].values
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


def get_quarter_range(today=None):
    """Return (train_start, train_end, valid_until) for current rolling window."""
    today = today or pd.Timestamp.now().normalize()
    quarter = (today.month - 1) // 3
    quarter_start = pd.Timestamp(year=today.year, month=quarter * 3 + 1, day=1)
    train_start = quarter_start - pd.DateOffset(months=3)
    train_end = quarter_start
    valid_until = quarter_start + pd.DateOffset(months=3) - pd.Timedelta(days=1)
    return train_start, train_end, valid_until


def main():
    train_start, train_end, valid_until = get_quarter_range()
    print(f"Training window: {train_start.date()} ~ {train_end.date()}")
    print(f"Rule will be valid until: {valid_until.date()}")

    print("\nLoading universe...")
    csv_files = []
    for d in STOOQ_DIR.iterdir():
        if d.is_dir():
            csv_files.extend(d.glob("*.txt"))

    events_by_key = {}
    for i, f in enumerate(csv_files):
        sym = f.stem.upper().replace(".US", "")
        if is_excluded(sym):
            continue
        df = parse_csv(f)
        if df is None:
            continue
        c = df["Close"].values
        if not ((c < 1.0).any() and (c >= 1.05).any()):
            continue
        for cd in CONS_DAYS_LIST:
            for lo, hi, label in ENTRY_RANGES:
                events = find_events(df, sym, cd, lo, hi)
                if events:
                    events_by_key.setdefault((cd, label, lo, hi), []).extend(events)

    print("Running grid on training window...")
    grid = []
    for (cd, label, lo, hi), all_events in events_by_key.items():
        train_evs = [e for e in all_events if train_start <= e["date"] < train_end]
        if len(train_evs) < 3:
            continue
        for tp in TP_LEVELS:
            for hold in HOLDS:
                rets = simulate(train_evs, tp, hold)
                if len(rets) < 3:
                    continue
                wr = (rets > 0).mean()
                p10 = np.percentile(rets, 10)
                score = wr * (1 + max(p10, -1))
                grid.append({
                    "cons_d": cd, "entry_range": label,
                    "entry_lo": lo, "entry_hi": hi,
                    "tp_ratio": tp, "hold": hold,
                    "n": len(rets), "win_rate": wr,
                    "mean": float(rets.mean()), "p10": p10, "score": score,
                })

    if not grid:
        print("ERROR: insufficient training data.")
        return

    g = pd.DataFrame(grid).nlargest(10, "score")
    print("\nTop 10 candidates:")
    print(f"{'cons':>4} {'entry':>14} {'TP':>6} {'hold':>5} {'N':>4} {'win%':>6} {'p10':>7} {'score':>6}")
    for _, r in g.iterrows():
        tp_s = "+%.0f%%" % ((r["tp_ratio"] - 1) * 100)
        print(f"{int(r['cons_d']):>3}d {r['entry_range']:>14} {tp_s:>6} {int(r['hold']):>3}d "
              f"{int(r['n']):>4} {r['win_rate']:>5.1%} {r['p10']:>+6.1%} {r['score']:>5.3f}")

    best = g.iloc[0]
    rule = {
        "cons_d": int(best["cons_d"]),
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
    }

    with open(CONFIG, "w") as f:
        json.dump(rule, f, indent=2)
    print(f"\n✓ Saved {CONFIG}")
    print(f"\nNew rule: cons {rule['cons_d']}d / entry [${rule['entry_lo']:.2f}, ${rule['entry_hi']:.2f}) / "
          f"TP +{(rule['tp_ratio']-1)*100:.0f}% / hold {rule['hold_d']}d")


if __name__ == "__main__":
    main()
