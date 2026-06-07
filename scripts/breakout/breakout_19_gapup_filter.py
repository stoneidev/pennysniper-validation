"""
Gap-up filter analysis.

For every historical breakout signal:
  - Compute gap_up = next_day_open / signal_day_close
    (this is the "execution gap" — how much you pay vs the close that triggered)
  - Also compute close-on-signal-day gap = signal_close / prev_close
    (how much price moved on signal day itself)

Compare:
  - Distribution of gap_up for TP-winners vs losers
  - Find threshold X such that filtering "gap_up > X" removes losers without removing winners

Apply to all (cd, label, tp, hold) combos used in our monthly walk-forward,
then re-run the rolling backtest with filter applied.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import time

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
        # Gap metrics
        signal_close = c[i]
        prev_close = c[i - 1]
        execution_gap = entry / signal_close - 1.0  # next-day open vs signal close
        signal_day_gap = signal_close / prev_close - 1.0  # signal close vs prev close
        rows.append({
            "symbol": sym,
            "date": pd.Timestamp(dates[i]),
            "entry": float(entry),
            "signal_close": float(signal_close),
            "prev_close": float(prev_close),
            "execution_gap": float(execution_gap),
            "signal_day_gap": float(signal_day_gap),
            "future_h": h[i + 1:].copy(),
            "future_c": c[i + 1:].copy(),
        })
    return rows


def simulate(events, tp_ratio, max_hold):
    rows = []
    for ev in events:
        entry = ev["entry"]
        tp_price = entry * tp_ratio
        n = min(max_hold, len(ev["future_h"]))
        if n == 0:
            continue
        ret = None
        tp_hit = False
        for j in range(n):
            if ev["future_h"][j] >= tp_price:
                ret = tp_ratio - 1.0 - SLIP
                tp_hit = True
                break
        if ret is None:
            ret = float(ev["future_c"][n - 1]) / entry - 1.0 - SLIP
        rows.append({
            "symbol": ev["symbol"],
            "date": ev["date"],
            "execution_gap": ev["execution_gap"],
            "signal_day_gap": ev["signal_day_gap"],
            "ret": ret,
            "tp_hit": tp_hit,
        })
    return rows


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
    print(f"  done in {time.time()-t0:.0f}s")

    # Collect ALL trades (using a "default" rule: TP +30%, hold 60d, all entry ranges combined)
    # to characterize the universe of signals.
    print("\nCollecting all trades for distribution analysis...")
    all_trades = []
    for (cd, label), events in events_by_key.items():
        # Use TP +30%, 60d hold as canonical
        for ev in events:
            entry = ev["entry"]
            tp_price = entry * 1.30
            n = min(60, len(ev["future_h"]))
            if n == 0:
                continue
            ret = None
            tp_hit = False
            for j in range(n):
                if ev["future_h"][j] >= tp_price:
                    ret = 0.30 - SLIP
                    tp_hit = True
                    break
            if ret is None:
                ret = float(ev["future_c"][n - 1]) / entry - 1.0 - SLIP
            all_trades.append({
                "execution_gap": ev["execution_gap"],
                "ret": ret,
                "tp_hit": tp_hit,
            })

    df = pd.DataFrame(all_trades)
    df["winner"] = df["ret"] > 0
    print(f"\nTotal trades collected: {len(df)}")

    # Distribution of execution_gap
    print("\n" + "=" * 80)
    print("Execution gap (next_day_open / signal_close - 1) distribution:")
    print("=" * 80)
    print(f"  All trades:")
    print(f"    p10={df['execution_gap'].quantile(0.10)*100:+.1f}%, "
          f"p50={df['execution_gap'].quantile(0.50)*100:+.1f}%, "
          f"p90={df['execution_gap'].quantile(0.90)*100:+.1f}%")
    print(f"    p95={df['execution_gap'].quantile(0.95)*100:+.1f}%, "
          f"p99={df['execution_gap'].quantile(0.99)*100:+.1f}%, "
          f"max={df['execution_gap'].max()*100:+.1f}%")
    print(f"\n  Winners (TP hit + held to close > 0):")
    w = df[df["winner"]]
    print(f"    p10={w['execution_gap'].quantile(0.10)*100:+.1f}%, "
          f"p50={w['execution_gap'].quantile(0.50)*100:+.1f}%, "
          f"p90={w['execution_gap'].quantile(0.90)*100:+.1f}%")
    print(f"    p95={w['execution_gap'].quantile(0.95)*100:+.1f}%, "
          f"max={w['execution_gap'].max()*100:+.1f}%")
    print(f"\n  Losers:")
    l = df[~df["winner"]]
    print(f"    p10={l['execution_gap'].quantile(0.10)*100:+.1f}%, "
          f"p50={l['execution_gap'].quantile(0.50)*100:+.1f}%, "
          f"p90={l['execution_gap'].quantile(0.90)*100:+.1f}%")
    print(f"    p95={l['execution_gap'].quantile(0.95)*100:+.1f}%, "
          f"max={l['execution_gap'].max()*100:+.1f}%")

    # Threshold sweep
    print("\n" + "=" * 80)
    print("Threshold sweep: filter out trades with execution_gap > X")
    print("=" * 80)
    print(f"\n{'threshold':>10} {'kept':>5} {'win%':>6} {'mean':>8} {'lost_winners':>12} {'lost_losers':>12}")
    for thr in [0.05, 0.10, 0.15, 0.20, 0.30, 0.50, 0.75, 1.00, 2.00]:
        kept = df[df["execution_gap"] <= thr]
        removed = df[df["execution_gap"] > thr]
        if len(kept) == 0:
            continue
        wr = kept["winner"].mean()
        mean = kept["ret"].mean()
        lost_w = removed["winner"].sum()  # winners removed
        lost_l = (~removed["winner"]).sum()  # losers removed
        print(f"   >{thr*100:>4.0f}% {len(kept):>5} {wr:>5.1%} {mean*100:>+7.2f}% "
              f"{lost_w:>11d} {lost_l:>11d}")

    print(f"\n  Baseline (no filter): N={len(df)}, win={df['winner'].mean():.1%}, mean={df['ret'].mean()*100:+.2f}%")

    df.to_csv(OUT_DIR / "gapup_analysis.csv", index=False)

    # ====================================================================
    # Re-run monthly walk-forward WITH gap-up filter
    # ====================================================================
    print("\n" + "=" * 80)
    print("Re-run monthly walk-forward with gap-up filter applied at SIGNAL TIME")
    print("=" * 80)

    months = pd.date_range("2023-04-01", "2026-06-01", freq="MS").tolist()

    def run_with_filter(gap_thr):
        log = []
        all_oos = []
        for i in range(len(months) - 1):
            test_start = months[i]
            test_end = months[i + 1]
            train_start = test_start - pd.DateOffset(months=3)
            train_end = test_start

            train_grid = []
            for (cd, label), all_events in events_by_key.items():
                # Train events filtered by gap-up
                train_evs = [e for e in all_events
                            if train_start <= e["date"] < train_end
                            and e["execution_gap"] <= gap_thr]
                if len(train_evs) < 5:
                    continue
                for tp in TP_LEVELS:
                    for hold in HOLDS:
                        sims = simulate(train_evs, tp, hold)
                        if len(sims) < 5:
                            continue
                        rets = np.array([s["ret"] for s in sims])
                        wr = (rets > 0).mean()
                        p10 = float(np.percentile(rets, 10))
                        score = wr * (1 + max(p10, -1))
                        train_grid.append({
                            "cd": cd, "label": label, "tp": tp, "hold": hold,
                            "n": len(rets), "win": wr, "p10": p10, "score": score,
                        })
            if not train_grid:
                continue
            best = max(train_grid, key=lambda x: x["score"])
            test_evs = [e for e in events_by_key.get((best["cd"], best["label"]), [])
                        if test_start <= e["date"] < test_end
                        and e["execution_gap"] <= gap_thr]
            if not test_evs:
                continue
            sims = simulate(test_evs, best["tp"], best["hold"])
            for s in sims:
                all_oos.append(s["ret"])
        return all_oos

    print(f"\n{'gap_thr':>10} {'n_trades':>9} {'win%':>6} {'mean':>8} {'sum':>10} "
          f"{'₩1M (25%)':>14}")

    # Baseline (no filter): use very high threshold
    for gap_thr in [10.0, 1.00, 0.75, 0.50, 0.30, 0.20, 0.15, 0.10, 0.05]:
        rets = np.array(run_with_filter(gap_thr))
        if len(rets) == 0:
            continue
        wr = (rets > 0).mean()
        mean = rets.mean()
        s = rets.sum()
        cash = 1_000_000
        for r in rets:
            pos = cash * 0.25
            cash = cash - pos + pos * (1 + r)
        label = "no filter" if gap_thr >= 5 else f">+{gap_thr*100:.0f}%"
        print(f"{label:>10} {len(rets):>9} {wr:>5.1%} {mean*100:>+7.2f}% "
              f"{s*100:>+9.1f}% ₩{cash:>12,.0f}")


if __name__ == "__main__":
    main()
