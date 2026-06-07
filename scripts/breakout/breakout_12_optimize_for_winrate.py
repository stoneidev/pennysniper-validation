"""
Re-optimize breakout strategy for HIGH WIN RATE + LOW LOSS.

Goal change:
  - Old goal: maximize total return (high variance, big losses OK)
  - NEW goal: maximize win rate + minimize p10 loss (steady wins)

Variables to optimize:
  1. Consolidation period: 30/45/60d under $1
  2. Breakout entry range: try multiple
     - $1.05-1.20 (current)
     - $1.05-1.10 (very narrow)
     - $1.10-1.30 (wider)
     - $1.20-1.50 (higher)
     - $1.50-2.00 (even higher)
  3. Take profit: try 1.2, 1.3, 1.5, 1.7, 2.0
     (lower TP = higher hit rate, smaller wins)
  4. Stop loss: try -10%, -15%, -20%, -30% (or none)
  5. Hold period: 30, 60, 90, 180d
  6. Universe: full Stooq NASDAQ (4,658 stocks)
  7. Common stock only (exclude warrants W*)

Score for ranking:
  Primary:   win_rate (% of trades > 0)
  Secondary: p10 (worst 10% return)
  Tertiary:  median return

Output: top combos by win_rate × (1 + p10_clipped)
"""
import pandas as pd
import numpy as np
from pathlib import Path
import time

STOOQ_DIR = Path("/Users/stoni/Downloads/data/daily/us/nasdaq stocks")
OUT_DIR = Path("/Users/stoni/Downloads/pennysniper_validation/results/csv")
OUT_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = pd.Timestamp("2024-06-01")
SLIP = 0.02
MIN_AVG_VOL = 10_000

CONS_DAYS_LIST = [30, 45, 60]
ENTRY_RANGES = [
    (1.05, 1.10, "$1.05-$1.10"),
    (1.05, 1.20, "$1.05-$1.20"),
    (1.10, 1.30, "$1.10-$1.30"),
    (1.20, 1.50, "$1.20-$1.50"),
    (1.50, 2.00, "$1.50-$2.00"),
]
TP_LEVELS = [1.20, 1.30, 1.50, 1.70, 2.00, 2.40]
SL_LEVELS = [None, -0.30, -0.20, -0.15, -0.10]  # None = no SL
HOLDS = [30, 60, 90, 180]


def parse_stooq_csv(path: Path):
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
    if len(df) < 65:
        return None
    return df.sort_values("date").reset_index(drop=True)[["date", "Open", "High", "Low", "Close", "Volume"]]


def find_events(df, symbol, cons_days, entry_lo, entry_hi):
    if len(df) < cons_days + 5:
        return []
    c = df["Close"].values
    o = df["Open"].values
    h = df["High"].values
    l = df["Low"].values
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

        # Track future bars for simulation
        rows.append({
            "symbol": symbol, "i": i, "entry": entry,
            "future_h": h[i + 1:], "future_l": l[i + 1:],
            "future_c": c[i + 1:], "future_dates": dates[i + 1:],
            "today_close": float(c[i]),
        })
    return rows


def simulate(events, tp_price_ratio, sl_pct, max_hold):
    """For each event, simulate entry → TP $X (absolute price) / SL X% / time exit."""
    rets = []
    for ev in events:
        entry = ev["entry"]
        future_h = ev["future_h"]
        future_l = ev["future_l"]
        future_c = ev["future_c"]
        if len(future_h) == 0:
            continue
        n = min(max_hold, len(future_h))

        tp_price = entry * tp_price_ratio  # NOTE: now ratio, e.g. 1.5 means +50%
        sl_price = entry * (1 + sl_pct) if sl_pct is not None else None

        ret = None
        for j in range(n):
            hi = float(future_h[j])
            lo = float(future_l[j])
            if sl_price is not None and lo <= sl_price:
                # SL fires (pessimistic if both reachable)
                if hi >= tp_price:
                    ret = sl_pct  # SL first
                else:
                    ret = sl_pct
                break
            if hi >= tp_price:
                ret = tp_price_ratio - 1.0
                break
        if ret is None:
            ret = float(future_c[n - 1]) / entry - 1.0
        rets.append(ret - SLIP)
    return np.array(rets)


def main():
    print("Loading Stooq NASDAQ universe...")
    csv_files = []
    for d in STOOQ_DIR.iterdir():
        if d.is_dir():
            csv_files.extend(d.glob("*.txt"))
    print(f"Total files: {len(csv_files)}")

    # Pre-load all data once, organize by (cons_days, entry_range)
    print("Pre-computing all event candidates...")
    events_by_key = {}
    t0 = time.time()
    for i, f in enumerate(csv_files):
        sym = f.stem.upper().replace(".US", "")
        if sym.endswith("W"):  # exclude warrants
            continue
        df = parse_stooq_csv(f)
        if df is None:
            continue
        c = df["Close"].values
        if not ((c < 1.0).any() and (c >= 1.05).any()):
            continue
        for cd in CONS_DAYS_LIST:
            for lo, hi, label in ENTRY_RANGES:
                events = find_events(df, sym, cd, lo, hi)
                key = (cd, label)
                events_by_key.setdefault(key, []).extend(events)
        if (i + 1) % 1000 == 0:
            print(f"  {i+1}/{len(csv_files)} ({time.time()-t0:.0f}s)")
    print(f"Done in {time.time()-t0:.0f}s")

    # Print event counts
    print("\nEvent counts by (cons, entry_range):")
    for (cd, label), ev in sorted(events_by_key.items()):
        print(f"  {cd}d / {label}: {len(ev)} events")

    # Run grid
    print("\nRunning grid simulation...")
    grid_rows = []
    for (cd, entry_label), events in events_by_key.items():
        if len(events) < 10:
            continue
        for tp in TP_LEVELS:
            for sl in SL_LEVELS:
                for hold in HOLDS:
                    rets = simulate(events, tp, sl, hold)
                    if len(rets) < 10:
                        continue
                    sl_label = f"{sl*100:+.0f}%" if sl is not None else "none"
                    grid_rows.append({
                        "cons_d": cd,
                        "entry_range": entry_label,
                        "tp_ratio": tp,
                        "sl_pct": sl_label,
                        "hold": hold,
                        "n": len(rets),
                        "win_rate": (rets > 0).mean(),
                        "mean": rets.mean(),
                        "median": np.median(rets),
                        "sum": rets.sum(),
                        "p10": np.percentile(rets, 10),
                        "p25": np.percentile(rets, 25),
                        "p90": np.percentile(rets, 90),
                        "max_loss": rets.min(),
                    })

    grid = pd.DataFrame(grid_rows)
    grid.to_csv(OUT_DIR / "winrate_optimization_grid.csv", index=False)
    print(f"Total grid combos: {len(grid)}")

    # Filter: require N >= 30 for stats stability
    stable = grid[grid["n"] >= 30].copy()

    # Score = win_rate * (1 + p10 clipped to >= -1)
    # This rewards high win rate AND penalizes large losses
    stable["safety_score"] = stable["win_rate"] * (1 + np.clip(stable["p10"], -1, 1))
    stable["expectancy"] = stable["mean"]

    print("\n" + "=" * 110)
    print("TOP 15 BY WIN RATE (N≥30)")
    print("=" * 110)
    print(f"\n{'cons':>4} {'entry_range':>14} {'TP':>6} {'SL':>7} {'hold':>5} "
          f"{'N':>4} {'win%':>6} {'mean':>7} {'median':>7} {'p10':>7} {'p90':>7}")
    top_wr = stable.nlargest(15, "win_rate")
    for _, r in top_wr.iterrows():
        tp_s = "+%.0f%%" % ((r["tp_ratio"] - 1) * 100)
        print(f"{int(r['cons_d']):>3}d {r['entry_range']:>14} {tp_s:>6} {r['sl_pct']:>7} "
              f"{int(r['hold']):>3}d {int(r['n']):>4} {r['win_rate']:>5.1%} "
              f"{r['mean']:>+6.1%} {r['median']:>+6.1%} {r['p10']:>+6.1%} {r['p90']:>+6.1%}")

    print("\n" + "=" * 110)
    print("TOP 15 BY SAFETY SCORE (win_rate × (1 + p10))")
    print("=" * 110)
    top_safe = stable.nlargest(15, "safety_score")
    print(f"\n{'cons':>4} {'entry_range':>14} {'TP':>6} {'SL':>7} {'hold':>5} "
          f"{'N':>4} {'win%':>6} {'mean':>7} {'p10':>7} {'safety':>7}")
    for _, r in top_safe.iterrows():
        tp_s = "+%.0f%%" % ((r["tp_ratio"] - 1) * 100)
        print(f"{int(r['cons_d']):>3}d {r['entry_range']:>14} {tp_s:>6} {r['sl_pct']:>7} "
              f"{int(r['hold']):>3}d {int(r['n']):>4} {r['win_rate']:>5.1%} "
              f"{r['mean']:>+6.1%} {r['p10']:>+6.1%} {r['safety_score']:>6.3f}")

    print("\n" + "=" * 110)
    print("TOP 15 BY MEAN RETURN, FILTERED win_rate >= 70%")
    print("=" * 110)
    high_wr = stable[stable["win_rate"] >= 0.70].nlargest(15, "mean")
    if len(high_wr) > 0:
        print(f"\n{'cons':>4} {'entry_range':>14} {'TP':>6} {'SL':>7} {'hold':>5} "
              f"{'N':>4} {'win%':>6} {'mean':>7} {'p10':>7}")
        for _, r in high_wr.iterrows():
            tp_s = "+%.0f%%" % ((r["tp_ratio"] - 1) * 100)
            print(f"{int(r['cons_d']):>3}d {r['entry_range']:>14} {tp_s:>6} {r['sl_pct']:>7} "
                  f"{int(r['hold']):>3}d {int(r['n']):>4} {r['win_rate']:>5.1%} "
                  f"{r['mean']:>+6.1%} {r['p10']:>+6.1%}")
    else:
        print("\nNo combos with win_rate >= 70% found.")

    # Lowest p10 (worst-case-protection-best)
    print("\n" + "=" * 110)
    print("TOP 10 BY p10 (best 'worst case', N≥30)")
    print("=" * 110)
    top_p10 = stable.nlargest(10, "p10")
    print(f"\n{'cons':>4} {'entry_range':>14} {'TP':>6} {'SL':>7} {'hold':>5} "
          f"{'N':>4} {'win%':>6} {'mean':>7} {'p10':>7}")
    for _, r in top_p10.iterrows():
        tp_s = "+%.0f%%" % ((r["tp_ratio"] - 1) * 100)
        print(f"{int(r['cons_d']):>3}d {r['entry_range']:>14} {tp_s:>6} {r['sl_pct']:>7} "
              f"{int(r['hold']):>3}d {int(r['n']):>4} {r['win_rate']:>5.1%} "
              f"{r['mean']:>+6.1%} {r['p10']:>+6.1%}")

    print(f"\n✓ Saved {OUT_DIR}/winrate_optimization_grid.csv ({len(grid)} combos)")


if __name__ == "__main__":
    main()
