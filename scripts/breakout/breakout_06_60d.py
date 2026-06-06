"""
60-day consolidation version of strict breakout test.

Compare to 90d criteria (15 events, 92% win, +81% mean).
"""
import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt

DAILY_CACHE = Path("price_cache")
SLIP = 0.02

CONS_DAYS = 60  # 60d instead of 90d
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
                "symbol": sym,
                "date": dates[i].strftime("%Y-%m-%d"),
                "today_close": float(c[i]),
                "next_open": float(entry),
                "consolidation_avg": float(prior.mean()),
            }
            for hz in HORIZONS:
                end_idx = min(i + 1 + hz, len(c))
                future_h = h[i + 1 : end_idx]
                future_l = l[i + 1 : end_idx]
                future_c = c[i + 1 : end_idx]
                if len(future_h) == 0:
                    continue
                event[f"horizon_complete_{hz}"] = int(len(future_h) >= hz)
                event[f"max_high_{hz}"] = float(future_h.max())
                event[f"min_low_{hz}"] = float(future_l.min())
                event[f"close_{hz}"] = float(future_c[-1])
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
    print(f"Criteria: prior {CONS_DAYS}d below $1.0, today close in [${BREAKOUT_LO:.2f}, ${BREAKOUT_HI:.2f})\n")

    df = find_events()
    print(f"Total matched events: {len(df)}")
    if len(df) == 0:
        return
    print(f"  unique tickers: {df['symbol'].nunique()}")
    print(f"  date range: {df['date'].min()} → {df['date'].max()}")

    # Per year
    df["year"] = pd.to_datetime(df["date"]).dt.year
    print(f"\nEvents by year:")
    for yr, n in df.groupby("year").size().items():
        print(f"  {yr}: {n}")

    # Hit rate
    print(f"\n{'horizon':<10} {'N':>5} {'hit_$2.4':>10} {'med_days':>11}")
    for hz in HORIZONS:
        col = f"horizon_complete_{hz}"
        if col not in df.columns:
            continue
        sub = df[df[col] == 1]
        if len(sub) == 0:
            continue
        hit_col = f"hit_tp2.4_{hz}"
        days = sub.loc[sub[hit_col] == 1, f"days_to_tp2.4_{hz}"]
        med = days.median() if len(days) > 0 else None
        med_s = f"{med:.0f}d" if med is not None else "—"
        print(f"{hz}d{'':>5} {len(sub):>5} {sub[hit_col].mean():>9.1%} {med_s:>10}")

    # Strategy P&L: TP $2.40 or hold-to-horizon-close
    print(f"\nStrategy: buy next-open, sell @ $2.40 if hit, else hold to horizon close")
    print(f"Slippage: {SLIP*100:.1f}% RT\n")
    print(f"{'horizon':<10} {'N':>5} {'hit%':>7} {'mean_ret':>10} {'median':>9} {'sum':>9} {'win%':>7} {'p10':>9} {'p90':>9}")
    for hz in HORIZONS:
        col = f"horizon_complete_{hz}"
        if col not in df.columns:
            continue
        sub = df[df[col] == 1].copy()
        if len(sub) == 0:
            continue
        rets = []
        for _, ev in sub.iterrows():
            if ev[f"hit_tp2.4_{hz}"] == 1:
                ret = 2.4 / ev["next_open"] - 1.0
            else:
                ret = ev[f"close_{hz}"] / ev["next_open"] - 1.0
            ret -= SLIP
            rets.append(ret)
        rets = np.array(rets)
        wr = (rets > 0).mean()
        print(f"{hz}d{'':>5} {len(sub):>5} {sub[f'hit_tp2.4_{hz}'].mean():>6.1%} "
              f"{rets.mean():>+9.2%} {np.median(rets):>+8.2%} {rets.sum():>+8.2f} "
              f"{wr:>6.1%} {np.percentile(rets, 10):>+8.2%} {np.percentile(rets, 90):>+8.2%}")

    # Compare TP levels at 180d
    print(f"\nTP comparison at horizon=180d:")
    print(f"{'TP':<8} {'hit%':>8} {'mean_overall':>13} {'sum':>9} {'win%':>7}")
    hz = 180
    sub = df[df.get(f"horizon_complete_{hz}", 0) == 1].copy()
    for tp in TP_LEVELS:
        if len(sub) == 0:
            continue
        hits = sub[sub[f"hit_tp{tp}_{hz}"] == 1]
        misses = sub[sub[f"hit_tp{tp}_{hz}"] == 0]
        ret_hit = (tp / hits["next_open"] - 1.0 - SLIP) if len(hits) > 0 else pd.Series([])
        ret_miss = (misses[f"close_{hz}"] / misses["next_open"] - 1.0 - SLIP) if len(misses) > 0 else pd.Series([])
        all_rets = pd.concat([ret_hit, ret_miss])
        if len(all_rets) == 0:
            continue
        print(f"${tp:<7.1f} {sub[f'hit_tp{tp}_{hz}'].mean():>7.1%} "
              f"{all_rets.mean():>+12.2%} {all_rets.sum():>+8.2f} {(all_rets > 0).mean():>6.1%}")

    # All events with TP $2.4 outcome at 180d
    print(f"\nAll events at 180d horizon (TP $2.4 strategy):")
    hz = 180
    sub = df[df.get(f"horizon_complete_{hz}", 0) == 1].copy()
    if len(sub) > 0:
        sub["return"] = sub.apply(
            lambda r: (2.4 / r["next_open"] - 1.0 - SLIP) if r[f"hit_tp2.4_{hz}"] == 1
                      else (r[f"close_{hz}"] / r["next_open"] - 1.0 - SLIP),
            axis=1,
        )
        sub["TP?"] = sub[f"hit_tp2.4_{hz}"].map({1: "✓", 0: "✗"})
        print(sub[["symbol", "date", "today_close", "next_open", "TP?",
                   f"days_to_tp2.4_{hz}", f"max_high_{hz}", f"close_{hz}", "return"]]
              .sort_values("date").to_string(index=False))

    df.to_csv("breakout_60d_results.csv", index=False)
    print("\nSaved breakout_60d_results.csv")


if __name__ == "__main__":
    main()
