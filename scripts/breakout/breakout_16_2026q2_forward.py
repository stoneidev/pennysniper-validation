"""
Forward window analysis for 2026 Q2.

  Train: 2026-01-01 ~ 2026-03-31  → pick best rule
  Test:  2026-04-01 ~ 2026-06-30  → apply, track signals

Output: chosen rule + all 2026 Q2 signals with current results.
"""
import pandas as pd
import numpy as np
from pathlib import Path

STOOQ_DIR = Path("/Users/stoni/Downloads/data/daily/us/nasdaq stocks")
OUT_DIR = Path("/Users/stoni/Downloads/pennysniper_validation/results/csv")
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

TRAIN_START = pd.Timestamp("2026-01-01")
TRAIN_END = pd.Timestamp("2026-04-01")
TEST_START = pd.Timestamp("2026-04-01")
TEST_END = pd.Timestamp("2026-07-01")


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
            "today_close": float(c[i]),
            "entry": float(entry),
            "future_h": h[i + 1:].copy(),
            "future_l": df["Low"].values[i + 1:].copy(),
            "future_c": c[i + 1:].copy(),
            "future_dates": dates[i + 1:].copy(),
        })
    return rows


def simulate_one(ev, tp_ratio, max_hold):
    entry = ev["entry"]
    tp_price = entry * tp_ratio
    n = min(max_hold, len(ev["future_h"]))
    if n == 0:
        return None
    for j in range(n):
        if ev["future_h"][j] >= tp_price:
            return {
                "ret": tp_ratio - 1.0 - SLIP,
                "tp_hit": True,
                "days_to_exit": j + 1,
                "exit_price": tp_price,
            }
    exit_price = float(ev["future_c"][n - 1])
    return {
        "ret": exit_price / entry - 1.0 - SLIP,
        "tp_hit": False,
        "days_to_exit": n,
        "exit_price": exit_price,
    }


def main():
    print("Loading universe...")
    csv_files = []
    for d in STOOQ_DIR.iterdir():
        if d.is_dir():
            csv_files.extend(d.glob("*.txt"))

    print("Pre-computing events for all (cons, entry_range) combos...")
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
                    events_by_key.setdefault((cd, label), []).extend(events)
        if (i + 1) % 1500 == 0:
            print(f"  {i+1}/{len(csv_files)}")

    # Train grid on 2026 Q1
    print(f"\nTrain on {TRAIN_START.date()} ~ {TRAIN_END.date()}")
    train_grid = []
    for (cd, label), all_events in events_by_key.items():
        train_evs = [e for e in all_events if TRAIN_START <= e["date"] < TRAIN_END]
        if len(train_evs) < 3:
            continue
        for tp in TP_LEVELS:
            for hold in HOLDS:
                rets = []
                for ev in train_evs:
                    res = simulate_one(ev, tp, hold)
                    if res is not None:
                        rets.append(res["ret"])
                if len(rets) < 3:
                    continue
                rets = np.array(rets)
                wr = (rets > 0).mean()
                p10 = np.percentile(rets, 10)
                score = wr * (1 + max(p10, -1))
                train_grid.append({
                    "cons_d": cd, "entry_range": label,
                    "tp_ratio": tp, "hold": hold,
                    "n": len(rets), "win_rate": wr,
                    "mean": rets.mean(), "p10": p10, "score": score,
                })

    if not train_grid:
        print("No train data — cannot proceed.")
        return
    train_df = pd.DataFrame(train_grid)
    print(f"\nTop 10 train combos by score:")
    print(f"{'cons':>4} {'entry':>14} {'TP':>6} {'hold':>5} {'N':>4} {'win%':>6} {'mean':>7} {'p10':>7} {'score':>6}")
    for _, r in train_df.nlargest(10, "score").iterrows():
        tp_s = "+%.0f%%" % ((r["tp_ratio"] - 1) * 100)
        print(f"{int(r['cons_d']):>3}d {r['entry_range']:>14} {tp_s:>6} {int(r['hold']):>3}d "
              f"{int(r['n']):>4} {r['win_rate']:>5.1%} {r['mean']:>+6.1%} {r['p10']:>+6.1%} {r['score']:>5.3f}")

    # Best
    best = train_df.nlargest(1, "score").iloc[0]
    cd, label = int(best["cons_d"]), best["entry_range"]
    tp, hold = best["tp_ratio"], int(best["hold"])
    print(f"\n{'=' * 110}")
    print(f"CHOSEN RULE for 2026 Q2: {cd}d cons / {label} / TP +{(tp-1)*100:.0f}% / hold {hold}d")
    print(f"  Train period N={int(best['n'])}, win {best['win_rate']:.1%}, mean {best['mean']:+.2%}")
    print(f"{'=' * 110}")

    # Apply to 2026 Q2
    all_events = events_by_key.get((cd, label), [])
    test_evs = [e for e in all_events if TEST_START <= e["date"] < TEST_END]
    print(f"\n2026 Q2 signals: {len(test_evs)}")
    if not test_evs:
        return

    print(f"\n{'symbol':<8} {'date':<11} {'entry':>7} {'TP$':>7} {'TP_hit':>7} {'days':>5} "
          f"{'exit_price':>11} {'ret':>8} {'cur_close':>10} {'cur_ret':>8}")

    test_results = []
    for ev in sorted(test_evs, key=lambda x: x["date"]):
        res = simulate_one(ev, tp, hold)
        if res is None:
            continue
        # Current status (latest available bar)
        latest_close = float(ev["future_c"][-1]) if len(ev["future_c"]) > 0 else None
        cur_ret = (latest_close / ev["entry"] - 1) if latest_close else None
        tp_s = "✓" if res["tp_hit"] else " "
        cur_ret_s = f"{cur_ret*100:+.1f}%" if cur_ret is not None else "—"
        print(f"{ev['symbol']:<8} {ev['date'].strftime('%Y-%m-%d'):<11} ${ev['entry']:>6.2f} "
              f"${ev['entry']*tp:>6.2f} {tp_s:>7} {res['days_to_exit']:>5} "
              f"${res['exit_price']:>10.2f} {res['ret']*100:>+7.1f}% "
              f"${latest_close:>9.2f} {cur_ret_s:>8}")
        test_results.append({
            "symbol": ev["symbol"],
            "date": ev["date"].strftime("%Y-%m-%d"),
            "entry": ev["entry"],
            "tp_price": ev["entry"] * tp,
            "tp_hit": res["tp_hit"],
            "days_to_exit": res["days_to_exit"],
            "exit_price": res["exit_price"],
            "ret": res["ret"],
            "current_close": latest_close,
            "current_ret": cur_ret,
        })

    if test_results:
        rets = np.array([r["ret"] for r in test_results])
        print(f"\n2026 Q2 summary (N={len(rets)}):")
        print(f"  win rate:   {(rets > 0).mean():.1%}")
        print(f"  TP hit:     {sum(r['tp_hit'] for r in test_results)}/{len(test_results)}")
        print(f"  mean:       {rets.mean():+.2%}")
        print(f"  median:     {np.median(rets):+.2%}")
        print(f"  sum:        {rets.sum():+.4f}")
        # ₩1M sim
        cash = 1_000_000
        for r in rets:
            position = cash * 0.25
            cash = cash - position + position * (1 + r)
        print(f"\n  ₩1M with 25% allocation: ₩{cash:,.0f} ({(cash/1_000_000-1)*100:+.1f}%)")

    pd.DataFrame(test_results).to_csv(OUT_DIR / "rolling_2026q2_signals.csv", index=False)
    print(f"\n✓ Saved {OUT_DIR}/rolling_2026q2_signals.csv")


if __name__ == "__main__":
    main()
