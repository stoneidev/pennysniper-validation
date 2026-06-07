"""
Monthly rolling walk-forward.

  Each month M:
    Train: prior 3 months [M-3, M-2, M-1]
    Apply: month M

  Example for May 2026: train on 2026.02 ~ 2026.04, apply to 2026.05.

Compare against quarterly retrain (same train period, applied to whole quarter).

Aggregate all OOS trades, compute total P&L with ₩1M sequential 25% alloc.
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

START_BUFFER = pd.Timestamp("2022-06-01")
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
    print("Loading universe from data/daily_cache/...")
    files = sorted(CACHE.glob("*.csv"))
    files = [f for f in files if not f.name.startswith("_")]

    print("Pre-computing events for each (cons, entry_range) combo...")
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
    print(f"  done in {time.time()-t0:.0f}s, {sum(len(v) for v in events_by_key.values())} total events")

    # Generate monthly windows from 2023.04 to 2026.05
    months = pd.date_range("2023-04-01", "2026-06-01", freq="MS").tolist()
    print(f"\nMonthly windows: {len(months)-1}")

    log_rows = []
    all_oos = []

    for i in range(len(months) - 1):
        # Test month: months[i] to months[i+1]
        test_start = months[i]
        test_end = months[i + 1]
        # Train: prior 3 months
        train_start = test_start - pd.DateOffset(months=3)
        train_end = test_start

        # Grid search on train
        train_grid = []
        for (cd, label), all_events in events_by_key.items():
            train_evs = [e for e in all_events if train_start <= e["date"] < train_end]
            if len(train_evs) < 5:
                continue
            for tp in TP_LEVELS:
                for hold in HOLDS:
                    rets = simulate(train_evs, tp, hold)
                    if len(rets) < 5:
                        continue
                    wr = (rets > 0).mean()
                    p10 = float(np.percentile(rets, 10))
                    score = wr * (1 + max(p10, -1))
                    train_grid.append({
                        "cd": cd, "label": label, "tp": tp, "hold": hold,
                        "n": len(rets), "win": wr, "mean": float(rets.mean()),
                        "p10": p10, "score": score,
                    })
        if not train_grid:
            log_rows.append({
                "test_month": test_start.strftime("%Y-%m"),
                "train_period": f"{train_start.date()}_{train_end.date()}",
                "rule": "—",
                "train_n": 0,
                "test_n": 0,
                "test_win": None,
                "test_mean": None,
                "test_sum": 0.0,
            })
            continue

        best = sorted(train_grid, key=lambda x: x["score"], reverse=True)[0]

        # Apply to test month
        test_evs = [e for e in events_by_key.get((best["cd"], best["label"]), [])
                    if test_start <= e["date"] < test_end]
        test_rets = simulate(test_evs, best["tp"], best["hold"])

        rule_str = (f"{best['cd']}d / {best['label']} / "
                    f"+{(best['tp']-1)*100:.0f}% / {best['hold']}d")
        log_rows.append({
            "test_month": test_start.strftime("%Y-%m"),
            "train_period": f"{train_start.date()}_{train_end.date()}",
            "rule": rule_str,
            "train_n": best["n"],
            "train_win": best["win"],
            "test_n": len(test_rets),
            "test_win": (test_rets > 0).mean() if len(test_rets) else None,
            "test_mean": test_rets.mean() if len(test_rets) else None,
            "test_sum": float(test_rets.sum()) if len(test_rets) else 0.0,
        })
        for r in test_rets:
            all_oos.append({"month": test_start.strftime("%Y-%m"), "ret": float(r)})

    log_df = pd.DataFrame(log_rows)
    log_df.to_csv(OUT_DIR / "monthly_rolling_log.csv", index=False)

    print("\n" + "=" * 130)
    print("MONTHLY ROLLING WALK-FORWARD RESULTS (3mo train → 1mo apply)")
    print("=" * 130)
    print(f"\n{'month':<10} {'train':<24} {'rule':<32} {'TR_n':>5} {'TS_n':>5} {'TS_win':>7} {'TS_mean':>9} {'TS_sum':>9}")
    print("-" * 130)
    for _, r in log_df.iterrows():
        ts_win = f"{r['test_win']:.0%}" if r["test_win"] is not None and not pd.isna(r["test_win"]) else "—"
        ts_mean = f"{r['test_mean']*100:+.1f}%" if r["test_mean"] is not None and not pd.isna(r["test_mean"]) else "—"
        print(f"{r['test_month']:<10} {r['train_period']:<24} {r['rule']:<32} "
              f"{int(r['train_n']):>5} {int(r['test_n']):>5} {ts_win:>7} {ts_mean:>8} {r['test_sum']:>+8.2f}")

    if all_oos:
        rets_arr = np.array([o["ret"] for o in all_oos])
        print("\n" + "=" * 130)
        print("AGGREGATE ALL OOS TRADES")
        print("=" * 130)
        print(f"  Total trades: {len(rets_arr)}")
        print(f"  Win rate:     {(rets_arr > 0).mean():.1%}")
        print(f"  Mean:         {rets_arr.mean()*100:+.2f}%")
        print(f"  Median:       {np.median(rets_arr)*100:+.2f}%")
        print(f"  Sum:          {rets_arr.sum()*100:+.2f}%")
        print(f"  p10:          {np.percentile(rets_arr, 10)*100:+.2f}%")
        print(f"  p90:          {np.percentile(rets_arr, 90)*100:+.2f}%")

        # Capital sims
        print("\n  ₩1,000,000 capital sim:")
        for alloc, label in [(1.00, "ALL_IN"), (0.25, "25%"), (0.10, "10%")]:
            cash = 1_000_000
            for r in rets_arr:
                pos = cash * alloc
                cash = cash - pos + pos * (1 + r)
            ret_pct = (cash / 1_000_000 - 1) * 100
            print(f"    {label:<10} → ₩{cash:>15,.0f} ({ret_pct:+.1f}%)")

    # Compare with quarterly: load earlier rolling_3m_log.csv if exists
    quarterly = OUT_DIR / "rolling_3m_log.csv"
    if quarterly.exists():
        q_log = pd.read_csv(quarterly)
        q_total = q_log["test_sum"].sum() if "test_sum" in q_log.columns else 0
        m_total = log_df["test_sum"].sum()
        print("\n" + "=" * 60)
        print("QUARTERLY vs MONTHLY (sum of per-trade returns)")
        print("=" * 60)
        print(f"  Quarterly retrain (every 3 months): sum {q_total:+.2f}, {len(q_log)} windows")
        print(f"  Monthly retrain (every 1 month):    sum {m_total:+.2f}, {len(log_df)} windows")

    pd.DataFrame(all_oos).to_csv(OUT_DIR / "monthly_rolling_oos.csv", index=False)
    print(f"\n✓ Saved {OUT_DIR}/monthly_rolling_log.csv and monthly_rolling_oos.csv")


if __name__ == "__main__":
    main()
