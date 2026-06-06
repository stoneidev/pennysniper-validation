"""
Penny stock breakout analysis.

Hypothesis: stocks that traded below $1 for an extended period, then break
above $1.5, often continue running to $3/$4/$5.

Method:
  For each ticker in daily cache:
    For each day where close >= $1.5 AND prior N days all closed below $1:
      Mark as "breakout event"
      Track max(High) over next M days
      Track if/when price reaches $3, $4, $5

Stratifications:
  - Consolidation period: 30 / 60 / 90 days below $1
  - Tracking horizon:     30 / 60 / 90 days after breakout
  - Target levels:        $2, $3, $4, $5

Also we record returns at fixed horizons (30d, 60d, 90d close return)
to give a true expected-value picture, not just hit probabilities.

Note on scope:
  - Daily cache covers ~2 years (2024.06 ~ 2026.06).
  - "Prior N days below $1" is computed within that window.
  - Stocks that re-entered the dataset after delisting are NOT included.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt

DAILY_CACHE = Path("price_cache")

CONSOLIDATION_PERIODS = [30, 60, 90]
TRACK_HORIZONS = [30, 60, 90]
TARGETS = [2.0, 3.0, 4.0, 5.0]
BREAKOUT_LEVEL = 1.5
SUB_LEVEL = 1.0


def main():
    print(f"Loading daily caches from {DAILY_CACHE}...")
    csvs = sorted(DAILY_CACHE.glob("*.csv"))
    print(f"  files: {len(csvs)}")

    all_events = []  # one row per breakout event
    universe_days_total = 0
    n_files_used = 0

    for f in csvs:
        sym = f.stem
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
        except Exception:
            continue
        if "Close" not in df.columns or len(df) < max(CONSOLIDATION_PERIODS) + 5:
            continue
        df = df.sort_index()
        n_files_used += 1
        universe_days_total += len(df)

        c = df["Close"].values
        h = df["High"].values
        v = df["Volume"].values
        dates = df.index

        for cons_days in CONSOLIDATION_PERIODS:
            # mask: today's close >= 1.5 AND all of last cons_days closes < 1.0
            for i in range(cons_days, len(c)):
                if c[i] >= BREAKOUT_LEVEL:
                    # check prior cons_days all < SUB_LEVEL
                    prior = c[i - cons_days : i]
                    if (prior < SUB_LEVEL).all() and (prior > 0).all():
                        # also check at least some volume during consolidation (not delisted-zombie)
                        avg_vol = v[i - cons_days : i].mean()
                        if avg_vol < 10000:  # extremely thin = likely zombie
                            continue
                        # Don't double-count: only first breakout in series.
                        # Skip if previous day was also a breakout (consecutive >= 1.5)
                        if i > 0 and c[i - 1] >= BREAKOUT_LEVEL:
                            continue
                        event = {
                            "symbol": sym,
                            "date": dates[i].strftime("%Y-%m-%d"),
                            "consolidation_days": cons_days,
                            "breakout_close": float(c[i]),
                            "breakout_high": float(h[i]),
                            "consolidation_avg_close": float(prior.mean()),
                            "consolidation_avg_vol": float(avg_vol),
                        }
                        # Track future
                        for horizon in TRACK_HORIZONS:
                            future_h = h[i + 1 : i + 1 + horizon]
                            future_c = c[i + 1 : i + 1 + horizon]
                            if len(future_h) == 0:
                                continue
                            event[f"max_high_{horizon}d"] = float(future_h.max())
                            event[f"close_at_{horizon}d"] = float(future_c[-1]) if len(future_c) >= horizon else float(future_c[-1])
                            event[f"horizon_complete_{horizon}d"] = int(len(future_h) >= horizon)
                            for tgt in TARGETS:
                                # First day max_high >= tgt
                                hit = future_h >= tgt
                                if hit.any():
                                    event[f"hit_{int(tgt)}d_{horizon}"] = 1
                                    event[f"days_to_{int(tgt)}d_{horizon}"] = int(np.argmax(hit) + 1)
                                else:
                                    event[f"hit_{int(tgt)}d_{horizon}"] = 0
                                    event[f"days_to_{int(tgt)}d_{horizon}"] = None
                        all_events.append(event)

    df = pd.DataFrame(all_events)
    print(f"\nFiles used: {n_files_used}, universe days: {universe_days_total:,}")
    print(f"Total breakout events found: {len(df)}")
    if len(df) == 0:
        return

    # ====================================================================
    # Probability of reaching each target, by consolidation period and horizon
    # ====================================================================
    print("\n" + "=" * 78)
    print("Probability of HIGH reaching target, given breakout from sub-$1")
    print("=" * 78)
    for cons in CONSOLIDATION_PERIODS:
        sub = df[df["consolidation_days"] == cons]
        if len(sub) == 0:
            continue
        print(f"\n--- Consolidation: prior {cons} days all closed < ${SUB_LEVEL:.0f} ---")
        print(f"  N events: {len(sub)}")
        print(f"  unique tickers: {sub['symbol'].nunique()}")
        print(f"\n  {'horizon':<8} {'$2':>7} {'$3':>7} {'$4':>7} {'$5':>7}  | {'mean_max':>9} {'med_max':>9} {'mean_close':>11}")
        for horizon in TRACK_HORIZONS:
            row = []
            complete = sub[sub.get(f"horizon_complete_{horizon}d", 0) == 1]
            n = len(complete)
            if n == 0:
                continue
            for tgt in TARGETS:
                hit_rate = complete[f"hit_{int(tgt)}d_{horizon}"].mean()
                row.append(f"{hit_rate:>6.1%}")
            mean_max = complete[f"max_high_{horizon}d"].mean()
            med_max = complete[f"max_high_{horizon}d"].median()
            mean_close = complete[f"close_at_{horizon}d"].mean()
            mean_breakout = complete["breakout_close"].mean()
            print(f"  {horizon:>3}d (N={n:<4}) {row[0]} {row[1]} {row[2]} {row[3]}  | "
                  f"${mean_max:>7.2f} ${med_max:>7.2f} ${mean_close:>9.2f}  (breakout avg ${mean_breakout:.2f})")

    # ====================================================================
    # Buy at breakout, sell at predetermined target — expected value
    # ====================================================================
    print("\n" + "=" * 78)
    print("Realistic strategy: buy at breakout close, sell at first touch of target OR after horizon")
    print("Pessimistic: assume entry slippage 1%, exit slippage 1% (penny stock spreads)")
    print("=" * 78)
    SLIP = 0.02  # 2% round-trip total — penny stock realistic

    for cons in CONSOLIDATION_PERIODS:
        sub = df[df["consolidation_days"] == cons]
        if len(sub) == 0:
            continue
        print(f"\n--- Consolidation {cons}d, N={len(sub)} ---")
        for horizon in TRACK_HORIZONS:
            complete = sub[sub.get(f"horizon_complete_{horizon}d", 0) == 1].copy()
            if len(complete) == 0:
                continue

            print(f"\n  Horizon {horizon}d:")
            print(f"  {'target':<10} {'hit_rate':>9} {'expected_ret':>13} {'mean_if_hit':>12} {'mean_if_miss':>13}")
            for tgt in TARGETS:
                hit_col = f"hit_{int(tgt)}d_{horizon}"
                hit = complete[hit_col] == 1
                if hit.sum() == 0:
                    continue
                # If hit: assume sold at tgt (exit at target price). Return = tgt/breakout_close - 1
                ret_if_hit = (tgt / complete.loc[hit, "breakout_close"] - 1.0) - SLIP
                # If miss: held to close at horizon. Return = close/breakout - 1
                ret_if_miss = (complete.loc[~hit, f"close_at_{horizon}d"]
                              / complete.loc[~hit, "breakout_close"] - 1.0) - SLIP
                exp_ret = (hit.sum() * ret_if_hit.mean() + (~hit).sum() * ret_if_miss.mean()) / len(complete) if len(complete) else 0
                print(f"  ${tgt:<9.0f} {hit.mean():>8.1%} {exp_ret:>+12.2%} "
                      f"{ret_if_hit.mean():>+11.2%} {ret_if_miss.mean():>+12.2%}")

    # ====================================================================
    # Buy and hold to horizon (no take-profit) — reality check
    # ====================================================================
    print("\n" + "=" * 78)
    print("Buy-and-hold reality check: enter at breakout close, hold to horizon close")
    print("=" * 78)
    for cons in CONSOLIDATION_PERIODS:
        sub = df[df["consolidation_days"] == cons]
        if len(sub) == 0:
            continue
        print(f"\n--- Consolidation {cons}d ---")
        print(f"  {'horizon':<10} {'N':>5} {'win%':>7} {'mean_ret':>10} {'median_ret':>11} {'p10':>9} {'p90':>9}")
        for horizon in TRACK_HORIZONS:
            complete = sub[sub.get(f"horizon_complete_{horizon}d", 0) == 1]
            if len(complete) == 0:
                continue
            ret = complete[f"close_at_{horizon}d"] / complete["breakout_close"] - 1.0 - SLIP
            print(f"  {horizon}d{'':<7} {len(complete):>5} {(ret>0).mean():>6.1%} "
                  f"{ret.mean():>+9.2%} {ret.median():>+10.2%} "
                  f"{ret.quantile(0.10):>+8.2%} {ret.quantile(0.90):>+8.2%}")

    df.to_csv("breakout_events.csv", index=False)
    print(f"\nSaved breakout_events.csv ({len(df)} events)")

    # Quick distribution plot
    if len(df) > 0:
        cons60 = df[df["consolidation_days"] == 60]
        if len(cons60) > 0:
            ret_90d = (cons60["close_at_90d"] / cons60["breakout_close"] - 1.0).dropna()
            fig, ax = plt.subplots(figsize=(11, 5))
            ax.hist(ret_90d * 100, bins=40, edgecolor="black")
            ax.axvline(0, color="black", linewidth=0.5)
            ax.axvline(ret_90d.mean() * 100, color="red", linestyle="--",
                       label=f"mean={ret_90d.mean():.1%}")
            ax.axvline(ret_90d.median() * 100, color="orange", linestyle="--",
                       label=f"median={ret_90d.median():.1%}")
            ax.set_title(f"90d return after $1→$1.5 breakout (consolidation 60d, N={len(ret_90d)})")
            ax.set_xlabel("Return %")
            ax.legend()
            ax.grid(alpha=0.3)
            fig.tight_layout()
            fig.savefig("breakout_dist.png", dpi=120)
            plt.close(fig)
            print("Saved breakout_dist.png")


if __name__ == "__main__":
    main()
