"""
Run breakout strategy on FULL Stooq NASDAQ universe (4,658 stocks).

Stooq CSV format:
  <TICKER>,<PER>,<DATE>,<TIME>,<OPEN>,<HIGH>,<LOW>,<CLOSE>,<VOL>,<OPENINT>
  AAPL.US,D,19840907,000000,0.099,0.10,0.097,0.099,99242379,0

Already split-adjusted (e.g., AAPL price in 1984 reflects all later splits).

Filter to last 1 year (~2025.06 to 2026.06), then apply our breakout grid:
  - cons {30, 45, 60d} below $1.0
  - today close in [$1.05, $1.20)
  - TP {1.5, 2.0, 2.4, 3.0, 5.0}
  - horizon {30, 60, 90, 180d}
  - alloc {ALL_IN, 25%, 10%}

Compare to prior 650-stock universe (curated penny universe).
"""
import pandas as pd
import numpy as np
from pathlib import Path
import os
import time

STOOQ_DIR = Path("/Users/stoni/Downloads/data/daily/us/nasdaq stocks")
OUT_DIR = Path("/Users/stoni/Downloads/pennysniper_validation/results/csv")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Filter to last ~2 years (need 60d cons + 1y test = ~14 months minimum)
START_DATE = pd.Timestamp("2024-06-01")
SLIP = 0.02

CONS_DAYS_LIST = [30, 45, 60]
BREAKOUT_LO = 1.05
BREAKOUT_HI = 1.20
SUB_LEVEL = 1.0
TP_LEVELS = [1.5, 2.0, 2.4, 3.0, 5.0]
HORIZONS = [30, 60, 90, 180]
MIN_AVG_VOL = 10_000


def parse_stooq_csv(path: Path) -> pd.DataFrame:
    """Parse Stooq daily CSV. Returns DataFrame with date, OHLCV."""
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
    df = df[df["date"] >= START_DATE].copy()
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    if len(df) < 65:
        return None
    df = df.sort_values("date").reset_index(drop=True)
    return df[["date", "Open", "High", "Low", "Close", "Volume"]]


def find_breakout_events(df: pd.DataFrame, symbol: str, cons_days: int):
    """Apply breakout filter to one stock's data."""
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
        if not (prior < SUB_LEVEL).all() or not (prior > 0).all():
            continue
        if v[i - cons_days : i].mean() < MIN_AVG_VOL:
            continue
        if not (BREAKOUT_LO <= c[i] < BREAKOUT_HI):
            continue
        if i > 0 and c[i - 1] >= BREAKOUT_LO:
            continue
        if i + 1 >= len(c):
            continue
        entry = o[i + 1]
        if entry <= 0:
            continue

        event = {
            "symbol": symbol,
            "date": pd.Timestamp(dates[i]).strftime("%Y-%m-%d"),
            "today_close": float(c[i]),
            "next_open": float(entry),
            "consolidation_avg": float(prior.mean()),
            "consolidation_avg_vol": float(v[i - cons_days : i].mean()),
        }

        for hz in HORIZONS:
            end_idx = min(i + 1 + hz, len(c))
            future_h = h[i + 1 : end_idx]
            future_c = c[i + 1 : end_idx]
            if len(future_h) == 0:
                continue
            event[f"horizon_complete_{hz}"] = int(len(future_h) >= hz)
            event[f"max_high_{hz}"] = float(future_h.max())
            event[f"close_{hz}"] = float(future_c[-1])
            for tp in TP_LEVELS:
                hit = future_h >= tp
                if hit.any():
                    event[f"hit_tp{tp}_{hz}"] = 1
                    event[f"days_to_tp{tp}_{hz}"] = int(np.argmax(hit) + 1)
                else:
                    event[f"hit_tp{tp}_{hz}"] = 0
                    event[f"days_to_tp{tp}_{hz}"] = None
        rows.append(event)
    return rows


def main():
    # Walk all Stooq CSV files
    csv_files = []
    for d in STOOQ_DIR.iterdir():
        if d.is_dir():
            csv_files.extend(d.glob("*.txt"))
    print(f"Total Stooq files: {len(csv_files)}")

    print("\nProcessing files (this may take a few minutes)...")
    all_events = {cd: [] for cd in CONS_DAYS_LIST}

    t0 = time.time()
    for i, f in enumerate(csv_files):
        # ticker = filename without .us.txt
        sym = f.stem.upper().replace(".US", "")
        df = parse_stooq_csv(f)
        if df is None:
            continue

        # Quick filter: did this stock ever trade in penny range during last year?
        c = df["Close"].values
        if not ((c < SUB_LEVEL).any() and (c >= BREAKOUT_LO).any() and (c < BREAKOUT_HI).any()):
            continue

        for cd in CONS_DAYS_LIST:
            events = find_breakout_events(df, sym, cd)
            all_events[cd].extend(events)

        if (i + 1) % 500 == 0:
            elapsed = time.time() - t0
            rate = (i + 1) / elapsed
            eta = (len(csv_files) - (i + 1)) / rate
            n_30 = len(all_events[30])
            print(f"  {i+1}/{len(csv_files)} ({elapsed:.0f}s, ETA {eta:.0f}s) — 30d events so far: {n_30}")

    print(f"\nProcessing complete in {time.time() - t0:.0f}s")
    for cd in CONS_DAYS_LIST:
        print(f"  {cd}d cons events: {len(all_events[cd])}")

    # Save events
    for cd in CONS_DAYS_LIST:
        df = pd.DataFrame(all_events[cd])
        df.to_csv(OUT_DIR / f"stooq_breakout_{cd}d.csv", index=False)

    # ====================================================================
    # Per-trade stats grid
    # ====================================================================
    print("\n" + "=" * 100)
    print("Per-trade stats grid (Stooq full NASDAQ universe)")
    print("=" * 100)
    print(f"\n{'cons':>5} {'TP':>6} {'horizon':>8} {'N':>6} {'win%':>7} {'mean':>9} "
          f"{'median':>8} {'p10':>9} {'p90':>9} {'sum':>9}")

    grid_rows = []
    for cd in CONS_DAYS_LIST:
        ev = pd.DataFrame(all_events[cd])
        if len(ev) == 0:
            continue
        for tp in TP_LEVELS:
            for hz in HORIZONS:
                col = f"horizon_complete_{hz}"
                if col not in ev.columns:
                    continue
                sub = ev[ev[col] == 1].copy()
                if len(sub) < 3:
                    continue
                # Compute return
                rets = []
                for _, e in sub.iterrows():
                    if e[f"hit_tp{tp}_{hz}"] == 1:
                        ret = tp / e["next_open"] - 1.0 - SLIP
                    else:
                        ret = e[f"close_{hz}"] / e["next_open"] - 1.0 - SLIP
                    rets.append(ret)
                rets = np.array(rets)
                tp_s = "$%.1f" % tp
                row = {
                    "cons_d": cd, "tp": tp, "horizon": hz, "n": len(rets),
                    "win_rate": (rets > 0).mean(),
                    "mean_ret": rets.mean(),
                    "median_ret": np.median(rets),
                    "sum_ret": rets.sum(),
                    "p10": np.percentile(rets, 10),
                    "p90": np.percentile(rets, 90),
                }
                grid_rows.append(row)
                print(f"{cd:>3}d {tp_s:>5} {hz:>5}d {len(rets):>6} "
                      f"{(rets > 0).mean():>6.1%} {rets.mean():>+8.2%} "
                      f"{np.median(rets):>+7.2%} {np.percentile(rets, 10):>+8.2%} "
                      f"{np.percentile(rets, 90):>+8.2%} {rets.sum():>+8.2f}")

    grid = pd.DataFrame(grid_rows)
    grid.to_csv(OUT_DIR / "stooq_breakout_grid.csv", index=False)

    # ====================================================================
    # Top recommendations
    # ====================================================================
    print("\n" + "=" * 100)
    print("Top 10 by mean return per trade (most robust)")
    print("=" * 100)
    rank = grid.copy()
    rank["score"] = rank["mean_ret"] * np.sqrt(rank["n"])
    top = rank.nlargest(10, "score")
    print(f"\n{'cons':>5} {'TP':>6} {'horizon':>8} {'N':>6} {'win%':>7} {'mean':>9} {'p10':>9}")
    for _, r in top.iterrows():
        tp_s = "$%.1f" % r["tp"]
        print(f"{int(r['cons_d']):>3}d {tp_s:>5} {int(r['horizon']):>5}d {int(r['n']):>6} "
              f"{r['win_rate']:>6.1%} {r['mean_ret']:>+8.2%} {r['p10']:>+8.2%}")

    print("\n" + "=" * 100)
    print("Compare to prior 650-stock universe (highlights)")
    print("=" * 100)
    print("\nOur previous best (60d / $3.0 / 180d): N=21, win=91%, mean=+114%, p10=+39%")
    print("Stooq full universe (60d / $3.0 / 180d):")
    s = grid[(grid["cons_d"] == 60) & (grid["tp"] == 3.0) & (grid["horizon"] == 180)]
    if len(s) > 0:
        r = s.iloc[0]
        print(f"  N={int(r['n'])}, win={r['win_rate']:.1%}, mean={r['mean_ret']:+.2%}, p10={r['p10']:+.2%}")
    print("\nOur previous best (30d / $3.0 / 90d ALL_IN): N=34, win=74%, mean=+81%")
    print("Stooq full universe (30d / $3.0 / 90d):")
    s = grid[(grid["cons_d"] == 30) & (grid["tp"] == 3.0) & (grid["horizon"] == 90)]
    if len(s) > 0:
        r = s.iloc[0]
        print(f"  N={int(r['n'])}, win={r['win_rate']:.1%}, mean={r['mean_ret']:+.2%}, p10={r['p10']:+.2%}")

    print(f"\n✓ Saved: {OUT_DIR}/stooq_breakout_*.csv")


if __name__ == "__main__":
    main()
