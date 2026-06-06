"""
Strict test: 90+ days under $1, breakout to $1.05-$1.20, exit at $2.40 take-profit.

Question: what is the probability of reaching $2.40 within various horizons?

Method:
  Universe-wide search:
    For each (symbol, day):
      - Prior 90 days all closed < $1.0
      - Today close in [1.05, 1.20]
      - Today not preceded by another breakout (no double-counting)

    For matched events:
      - Entry: NEXT day at OPEN (realistic)
      - Exit: first time HIGH >= $2.40 within horizon (= TP fired)
      - If TP not hit: exit at horizon close (held position)

    Compute hit rate, expected return, time-to-TP distribution.

Stratifications:
  - Horizons: 30, 60, 90, 180, 365 days
  - Slippage: 2% round-trip (penny stock realistic)
  - Compare to alternative TPs: $2.0, $2.4, $3.0, $5.0
"""
import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt

DAILY_CACHE = Path("price_cache")
SLIP = 0.02

CONS_DAYS = 90  # Strict: 90 days under $1
BREAKOUT_LO = 1.05
BREAKOUT_HI = 1.20
SUB_LEVEL = 1.0
HORIZONS = [30, 60, 90, 180, 365]
TP_LEVELS = [2.0, 2.4, 3.0, 5.0]


def find_events():
    rows = []
    for f in sorted(DAILY_CACHE.glob("*.csv")):
        sym = f.stem
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
        except Exception:
            continue
        if len(df) < CONS_DAYS + 5:
            continue
        df = df.sort_index()
        c = df["Close"].values
        o = df["Open"].values
        h = df["High"].values
        l = df["Low"].values
        v = df["Volume"].values
        dates = df.index

        for i in range(CONS_DAYS, len(c) - 1):
            prior = c[i - CONS_DAYS : i]
            if not (prior < SUB_LEVEL).all() or not (prior > 0).all():
                continue
            if v[i - CONS_DAYS : i].mean() < 10000:
                continue
            # Today close in breakout range
            if not (BREAKOUT_LO <= c[i] < BREAKOUT_HI):
                continue
            # Skip if previous day was already a breakout
            if i > 0 and c[i - 1] >= BREAKOUT_LO:
                continue
            # Need next-day open
            if i + 1 >= len(c):
                continue
            entry = o[i + 1]
            if entry <= 0:
                continue

            event = {
                "symbol": sym,
                "date": dates[i].strftime("%Y-%m-%d"),
                "today_close": float(c[i]),
                "next_open": float(entry),
                "consolidation_avg": float(prior.mean()),
            }
            # For each horizon, record what happened
            for hz in HORIZONS:
                end_idx = min(i + 1 + hz, len(c))
                future_h = h[i + 1 : end_idx]
                future_l = l[i + 1 : end_idx]
                future_c = c[i + 1 : end_idx]
                future_dates = dates[i + 1 : end_idx]

                if len(future_h) == 0:
                    continue
                event[f"horizon_complete_{hz}"] = int(len(future_h) >= hz)
                event[f"max_high_{hz}"] = float(future_h.max())
                event[f"min_low_{hz}"] = float(future_l.min())
                event[f"close_{hz}"] = float(future_c[-1])

                # For each TP level, find first day high >= TP
                for tp in TP_LEVELS:
                    hit = future_h >= tp
                    if hit.any():
                        first_idx = int(np.argmax(hit))
                        event[f"hit_tp{tp}_{hz}"] = 1
                        event[f"days_to_tp{tp}_{hz}"] = first_idx + 1
                    else:
                        event[f"hit_tp{tp}_{hz}"] = 0
                        event[f"days_to_tp{tp}_{hz}"] = None
            rows.append(event)
    return pd.DataFrame(rows)


def main():
    print(f"Strict criteria:")
    print(f"  - Prior {CONS_DAYS} days all closed < ${SUB_LEVEL:.0f}")
    print(f"  - Today close in [${BREAKOUT_LO:.2f}, ${BREAKOUT_HI:.2f})")
    print(f"  - Min avg volume {10000} during consolidation")
    print(f"  - Entry: NEXT-day open\n")

    df = find_events()
    print(f"Total matched events: {len(df)}")
    if len(df) == 0:
        return

    print(f"  unique tickers: {df['symbol'].nunique()}")
    print(f"  date range: {df['date'].min()} → {df['date'].max()}")

    # ====================================================================
    # Hit rate at $2.4 by horizon
    # ====================================================================
    print(f"\n{'=' * 78}")
    print(f"Hit rate of REACHING TP $2.40 (= +{(2.4/df['next_open'].mean()-1)*100:.0f}% from avg next_open)")
    print(f"{'=' * 78}")
    print(f"\n{'horizon':<10} {'N':>5} {'hit_$2.4':>10} {'med_days':>11} {'mean_days':>11}")
    for hz in HORIZONS:
        col_complete = f"horizon_complete_{hz}"
        if col_complete not in df.columns:
            continue
        sub = df[df[col_complete] == 1]
        if len(sub) == 0:
            continue
        hit_col = f"hit_tp2.4_{hz}"
        days_col = f"days_to_tp2.4_{hz}"
        hit_rate = sub[hit_col].mean()
        days = sub.loc[sub[hit_col] == 1, days_col]
        med_days = days.median() if len(days) > 0 else None
        mean_days = days.mean() if len(days) > 0 else None
        print(f"{hz}d{'':>5} {len(sub):>5} {hit_rate:>9.1%} "
              f"{med_days if med_days is None else f'{med_days:.0f}d':>10} "
              f"{mean_days if mean_days is None else f'{mean_days:.1f}d':>10}")

    # ====================================================================
    # Realistic strategy P&L: buy next-open, sell at $2.4 if hit, else hold to horizon close
    # ====================================================================
    print(f"\n{'=' * 78}")
    print(f"Strategy P&L: buy next-open, sell @ $2.40 if hit (else hold to horizon close)")
    print(f"Slippage: {SLIP*100:.1f}% round-trip")
    print(f"{'=' * 78}")
    print(f"\n{'horizon':<10} {'N':>5} {'hit%':>7} {'mean_ret':>10} {'median':>9} {'sum':>9} "
          f"{'win%':>7} {'p10':>9} {'p90':>9}")

    for hz in HORIZONS:
        col_complete = f"horizon_complete_{hz}"
        if col_complete not in df.columns:
            continue
        sub = df[df[col_complete] == 1].copy()
        if len(sub) == 0:
            continue

        # Compute return for each event
        rets = []
        for _, ev in sub.iterrows():
            if ev[f"hit_tp2.4_{hz}"] == 1:
                # exited at $2.4
                ret = 2.4 / ev["next_open"] - 1.0
            else:
                ret = ev[f"close_{hz}"] / ev["next_open"] - 1.0
            ret -= SLIP
            rets.append(ret)
        rets = np.array(rets)

        sub["ret"] = rets
        wr = (rets > 0).mean()
        print(f"{hz}d{'':>5} {len(sub):>5} {sub[f'hit_tp2.4_{hz}'].mean():>6.1%} "
              f"{rets.mean():>+9.2%} {np.median(rets):>+8.2%} {rets.sum():>+8.2f} "
              f"{wr:>6.1%} {np.percentile(rets, 10):>+8.2%} {np.percentile(rets, 90):>+8.2%}")

    # ====================================================================
    # Compare to other TP levels (best TP for this signal?)
    # ====================================================================
    print(f"\n{'=' * 78}")
    print(f"TP comparison at horizon=180d")
    print(f"{'=' * 78}")
    print(f"\n{'TP':<8} {'hit%':>8} {'mean_if_hit':>12} {'mean_overall':>13} {'sum':>9} {'win%':>7}")
    hz = 180
    sub = df[df.get(f"horizon_complete_{hz}", 0) == 1].copy()
    for tp in TP_LEVELS:
        if len(sub) == 0:
            continue
        hits = sub[sub[f"hit_tp{tp}_{hz}"] == 1]
        misses = sub[sub[f"hit_tp{tp}_{hz}"] == 0]
        # When hit, exit at TP. When miss, exit at horizon close
        ret_hit = (tp / hits["next_open"] - 1.0 - SLIP) if len(hits) > 0 else pd.Series([])
        ret_miss = (misses[f"close_{hz}"] / misses["next_open"] - 1.0 - SLIP) if len(misses) > 0 else pd.Series([])
        all_rets = pd.concat([ret_hit, ret_miss])
        if len(all_rets) == 0:
            continue
        print(f"${tp:<7.1f} {sub[f'hit_tp{tp}_{hz}'].mean():>7.1%} "
              f"{ret_hit.mean() if len(ret_hit) else 0:>+11.2%} "
              f"{all_rets.mean():>+12.2%} "
              f"{all_rets.sum():>+8.2f} "
              f"{(all_rets > 0).mean():>6.1%}")

    # ====================================================================
    # Show event details
    # ====================================================================
    print(f"\n{'=' * 78}")
    print(f"All events with TP $2.4 outcome at 180d horizon")
    print(f"{'=' * 78}")
    hz = 180
    sub = df[df.get(f"horizon_complete_{hz}", 0) == 1].copy()
    if len(sub) > 0:
        sub["return_at_2.4_or_close"] = sub.apply(
            lambda r: (2.4 / r["next_open"] - 1.0 - SLIP) if r[f"hit_tp2.4_{hz}"] == 1
                      else (r[f"close_{hz}"] / r["next_open"] - 1.0 - SLIP),
            axis=1,
        )
        cols = ["symbol", "date", "today_close", "next_open",
                f"hit_tp2.4_{hz}", f"days_to_tp2.4_{hz}",
                f"max_high_{hz}", f"close_{hz}", "return_at_2.4_or_close"]
        print(sub[cols].sort_values("date").to_string(index=False))

    df.to_csv("breakout_strict_90d.csv", index=False)
    print(f"\nSaved breakout_strict_90d.csv")

    # ====================================================================
    # Plot
    # ====================================================================
    if len(df) > 0:
        hz = 180
        sub = df[df.get(f"horizon_complete_{hz}", 0) == 1].copy()
        if len(sub) > 0:
            fig, axes = plt.subplots(1, 2, figsize=(13, 5))

            # Distribution of max_high in 180d
            axes[0].hist(sub[f"max_high_{hz}"], bins=20, edgecolor="black", color="steelblue")
            axes[0].axvline(2.4, color="red", linestyle="--", label="TP=$2.40")
            axes[0].axvline(sub[f"max_high_{hz}"].mean(), color="orange", linestyle="--",
                          label=f"mean=${sub[f'max_high_{hz}'].mean():.2f}")
            axes[0].set_title(f"Max high reached within 180d (N={len(sub)})")
            axes[0].set_xlabel("Max high $")
            axes[0].set_ylabel("# events")
            axes[0].legend()
            axes[0].grid(alpha=0.3)

            # Days to TP $2.4
            tp_days = sub[sub[f"hit_tp2.4_{hz}"] == 1][f"days_to_tp2.4_{hz}"]
            if len(tp_days) > 0:
                axes[1].hist(tp_days, bins=20, edgecolor="black", color="green")
                axes[1].axvline(tp_days.median(), color="red", linestyle="--",
                              label=f"median={tp_days.median():.0f}d")
                axes[1].set_title(f"Days to reach $2.40 (N={len(tp_days)} hits)")
                axes[1].set_xlabel("Days")
                axes[1].set_ylabel("# events")
                axes[1].legend()
                axes[1].grid(alpha=0.3)
            fig.tight_layout()
            fig.savefig("breakout_strict_90d.png", dpi=120)
            plt.close(fig)
            print("Saved breakout_strict_90d.png")


if __name__ == "__main__":
    main()
