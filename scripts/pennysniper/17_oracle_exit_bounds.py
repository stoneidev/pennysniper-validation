"""
Step 17: Oracle exit policy — what's the THEORETICAL UPPER BOUND for RL?

For each ≤10-min +30% trigger event:
  - Buy at +30% (RTH_open * 1.30)
  - Compute BEST possible exit:
      max return = (max_close_after_entry - entry) / entry
      where max is taken over all bars from entry to RTH close
  - Compute WORST possible exit (held to RTH close)
  - Compute best fixed (TP, SL) policy in a grid

Interpretation:
  - Oracle return = upper bound any policy (including RL) can achieve
  - If oracle * (1 - haircut) < 3% cost → RL cannot save this strategy
  - 'haircut' represents the gap between oracle (perfect foresight) and
    realistic policy (must decide in real time without future info)

Empirically, even good RL captures roughly 30-60% of oracle in stationary
environments. In non-stationary financial data, often <20%.
"""
import json
from pathlib import Path
import pandas as pd
import numpy as np

CACHE_DIR = Path("polygon_minute_cache")
ENTRY_MULT = 1.30
TRIGGER_CUTOFF = 10  # minutes


def load_bars(symbol, date):
    f = CACHE_DIR / f"{symbol}_{date}.json"
    if not f.exists():
        return None
    with open(f) as fp:
        d = json.load(fp)
    if not d.get("results"):
        return None
    df = pd.DataFrame(d["results"])
    df["timestamp"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert("America/New_York")
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df[["timestamp", "open", "high", "low", "close", "volume"]].sort_values("timestamp").reset_index(drop=True)
    rth = df[
        (df["timestamp"].dt.time >= pd.Timestamp("09:30").time())
        & (df["timestamp"].dt.time < pd.Timestamp("16:00").time())
    ].reset_index(drop=True)
    return rth if len(rth) > 0 else None


def analyze_event(bars):
    if bars is None or len(bars) < 2:
        return None
    rth_open = float(bars["open"].iloc[0])
    if rth_open <= 0:
        return None
    entry_target = rth_open * ENTRY_MULT

    entry_idx = None
    for i, row in enumerate(bars.itertuples(index=False)):
        if row.high >= entry_target:
            entry_idx = i
            break
    if entry_idx is None or entry_idx > TRIGGER_CUTOFF:
        return None
    if entry_idx == 0 and bars["low"].iloc[0] >= entry_target:
        return None

    entry = entry_target
    after = bars.iloc[entry_idx:]  # from entry bar onwards

    rth_high = float(after["high"].max())
    rth_low_after_entry = float(after["low"].min())
    rth_close = float(bars["close"].iloc[-1])
    daily_max_x_open = float(bars["high"].max() / rth_open)

    # Oracle exits
    oracle_best_exit = rth_high  # sell at highest moment after entry
    oracle_worst_exit = rth_low_after_entry  # sell at lowest moment after entry
    eod_exit = rth_close  # held to close

    return {
        "entry": entry,
        "rth_high_after_entry": rth_high,
        "rth_low_after_entry": rth_low_after_entry,
        "rth_close": rth_close,
        "oracle_best_return": oracle_best_exit / entry - 1.0,
        "oracle_worst_return": oracle_worst_exit / entry - 1.0,
        "eod_return": eod_exit / entry - 1.0,
        "trigger_min": entry_idx,
        "daily_max_x_open": daily_max_x_open,
        "reached_100pct": int(daily_max_x_open >= 2.0),
    }


def simulate_with_tpsl(bars, tp_pct, sl_pct):
    """Simulate with given TP/SL pair. Returns (return, exit_reason) or None."""
    if bars is None or len(bars) < 2:
        return None
    rth_open = float(bars["open"].iloc[0])
    if rth_open <= 0:
        return None
    entry_target = rth_open * ENTRY_MULT

    entry_idx = None
    for i, row in enumerate(bars.itertuples(index=False)):
        if row.high >= entry_target:
            entry_idx = i
            break
    if entry_idx is None or entry_idx > TRIGGER_CUTOFF:
        return None
    if entry_idx == 0 and bars["low"].iloc[0] >= entry_target:
        return None

    entry = entry_target
    tp = entry * (1 + tp_pct)
    sl = entry * (1 - sl_pct)

    for j in range(entry_idx, len(bars)):
        bar = bars.iloc[j]
        if j == entry_idx:
            if bar.low <= sl:
                return -sl_pct
            if bar.high >= tp:
                return tp_pct
        else:
            if bar.open <= sl:
                return bar.open / entry - 1.0
            if bar.open >= tp:
                return bar.open / entry - 1.0
            if bar.low <= sl and bar.high >= tp:
                return -sl_pct
            if bar.low <= sl:
                return -sl_pct
            if bar.high >= tp:
                return tp_pct
    # held to close
    return float(bars["close"].iloc[-1]) / entry - 1.0


def main():
    files = sorted(CACHE_DIR.glob("*.json"))
    print(f"Cached files: {len(files)}\n")

    rows = []
    for f in files:
        stem = f.stem
        if "_" not in stem:
            continue
        sym, date = stem.rsplit("_", 1)
        bars = load_bars(sym, date)
        a = analyze_event(bars)
        if a is None:
            continue
        a["symbol"] = sym
        a["date"] = date
        rows.append(a)

    df = pd.DataFrame(rows)
    print(f"Events with ≤{TRIGGER_CUTOFF}min trigger: {len(df)}")
    print(f"  reached +100% on day: {df['reached_100pct'].sum()}")
    print(f"  did NOT reach +100%:  {(df['reached_100pct']==0).sum()}\n")

    print("=" * 78)
    print("(1) UPPER BOUND: Oracle perfect-exit (sell at highest after entry)")
    print("=" * 78)
    print(f"\n{'group':<28} {'N':>5} {'mean_oracle':>12} {'median':>9} {'min':>9} {'10th_pct':>10}")
    for label, sub in [
        ("ALL events", df),
        ("reached +100% (peek)", df[df["reached_100pct"] == 1]),
        ("only +30%~+99% (clean)", df[df["reached_100pct"] == 0]),
    ]:
        if len(sub) == 0:
            continue
        ob = sub["oracle_best_return"]
        print(f"{label:<28} {len(sub):>5} {ob.mean():>+11.2%} {ob.median():>+8.2%} {ob.min():>+8.2%} {ob.quantile(0.1):>+9.2%}")

    print("\n" + "=" * 78)
    print("(2) LOWER BOUND: Oracle worst-exit (sell at lowest after entry)")
    print("=" * 78)
    print(f"\n{'group':<28} {'N':>5} {'mean_worst':>12} {'median':>9}")
    for label, sub in [
        ("ALL events", df),
        ("reached +100% (peek)", df[df["reached_100pct"] == 1]),
        ("only +30%~+99% (clean)", df[df["reached_100pct"] == 0]),
    ]:
        if len(sub) == 0:
            continue
        ow = sub["oracle_worst_return"]
        print(f"{label:<28} {len(sub):>5} {ow.mean():>+11.2%} {ow.median():>+8.2%}")

    print("\n" + "=" * 78)
    print("(3) MEDIAN OUTCOME: Held to close (no TP/SL)")
    print("=" * 78)
    print(f"\n{'group':<28} {'N':>5} {'mean_eod':>10} {'median':>9}")
    for label, sub in [
        ("ALL events", df),
        ("reached +100% (peek)", df[df["reached_100pct"] == 1]),
        ("only +30%~+99% (clean)", df[df["reached_100pct"] == 0]),
    ]:
        if len(sub) == 0:
            continue
        e = sub["eod_return"]
        print(f"{label:<28} {len(sub):>5} {e.mean():>+9.2%} {e.median():>+8.2%}")

    # ========================================================================
    # (4) Grid search over fixed TP/SL pairs
    # ========================================================================
    print("\n" + "=" * 78)
    print("(4) Grid search: best fixed (TP, SL) pair")
    print("=" * 78)
    tp_grid = [0.05, 0.07, 0.10, 0.15, 0.20, 0.30, 0.50]
    sl_grid = [0.03, 0.05, 0.07, 0.10, 0.15]

    grid_results = []
    for tp in tp_grid:
        for sl in sl_grid:
            rets_all = []
            rets_clean = []
            for f in files:
                stem = f.stem
                if "_" not in stem:
                    continue
                sym, date = stem.rsplit("_", 1)
                bars = load_bars(sym, date)
                r = simulate_with_tpsl(bars, tp, sl)
                if r is None:
                    continue
                # determine if reached +100%
                if bars is not None and len(bars) > 0:
                    rth_open = float(bars["open"].iloc[0])
                    daily_max = float(bars["high"].max())
                    is_clean = (daily_max / rth_open) < 2.0
                else:
                    is_clean = False
                rets_all.append(r)
                if is_clean:
                    rets_clean.append(r)

            ra = np.array(rets_all)
            rc = np.array(rets_clean) if rets_clean else None
            grid_results.append({
                "tp": tp,
                "sl": sl,
                "n_all": len(ra),
                "mean_all": ra.mean(),
                "winrate_all": (ra > 0).mean(),
                "n_clean": len(rc) if rc is not None else 0,
                "mean_clean": rc.mean() if rc is not None else np.nan,
                "winrate_clean": (rc > 0).mean() if rc is not None else np.nan,
            })

    g = pd.DataFrame(grid_results)
    print(f"\n--- ALL events (with peek-ahead) ---")
    print(f"{'TP':>6} {'SL':>6} {'N':>4} {'win%':>6} {'mean':>8} {'net@3%':>8} {'net@5%':>8}")
    g_all_sorted = g.sort_values("mean_all", ascending=False).head(8)
    for _, r in g_all_sorted.iterrows():
        print(f"{r['tp']:>+6.0%} {-r['sl']:>+6.0%} {r['n_all']:>4} "
              f"{r['winrate_all']:>5.0%} {r['mean_all']:>+7.2%} "
              f"{r['mean_all']-0.03:>+7.2%} {r['mean_all']-0.05:>+7.2%}")

    print(f"\n--- CLEAN subset (no +100% peek-ahead) ---")
    print(f"{'TP':>6} {'SL':>6} {'N':>4} {'win%':>6} {'mean':>8} {'net@3%':>8} {'net@5%':>8}")
    g_clean_sorted = g.sort_values("mean_clean", ascending=False).head(8)
    for _, r in g_clean_sorted.iterrows():
        wr = r['winrate_clean']
        print(f"{r['tp']:>+6.0%} {-r['sl']:>+6.0%} {r['n_clean']:>4} "
              f"{wr:>5.0%} {r['mean_clean']:>+7.2%} "
              f"{r['mean_clean']-0.03:>+7.2%} {r['mean_clean']-0.05:>+7.2%}")

    g.to_csv("tpsl_grid_results.csv", index=False)

    # ========================================================================
    # (5) Final verdict
    # ========================================================================
    print("\n" + "=" * 78)
    print("VERDICT: Can RL save this strategy?")
    print("=" * 78)

    clean = df[df["reached_100pct"] == 0]
    if len(clean) >= 3:
        oracle_clean = clean["oracle_best_return"].mean()
        # Realistic RL captures ~30% of oracle in stationary settings
        for capture in [0.3, 0.5, 0.7, 1.0]:
            rl_alpha = oracle_clean * capture
            net_3 = rl_alpha - 0.03
            net_5 = rl_alpha - 0.05
            label = "Perfect Oracle (impossible)" if capture == 1.0 else f"RL captures {capture:.0%} of oracle"
            print(f"  {label:<35}: gross={rl_alpha:+.2%}  net@3%={net_3:+.2%}  net@5%={net_5:+.2%}")
        print(f"\n  (clean subset oracle mean = {oracle_clean:+.2%})")
        print(f"  (clean subset N = {len(clean)})")


if __name__ == "__main__":
    main()
