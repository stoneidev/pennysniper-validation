"""
TRUE walk-forward expanding window validation for XRP mean reversion.

Honest production-grade simulation:
  - Monthly retraining
  - At month-end of month M, use data [start ... end of M] to pick best (thr, hold)
  - Apply that to month M+1 trades only
  - Move forward, repeat
  - Aggregate ALL OOS trades across all months
  - This is what production trading would look like

Key questions:
  1. Does the -7% signal survive when chosen ex-ante (no peeking)?
  2. How often does the chosen parameter change?
  3. Is the aggregate OOS APY positive after fees?

Also test:
  - "Naive" strategy: always trade -5% / 240min (no model selection)
  - vs adaptive (best of grid each month)
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

CACHE = Path("xrp_cache")
FEE_RT = 0.002
SLIP = 0.0005
COST = FEE_RT + SLIP


def load():
    df = pd.read_csv(CACHE / "spot_1m_2y.csv")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    return df.sort_values("timestamp").reset_index(drop=True)


def find_signals(df, lookback, threshold, cooldown, start_idx=0, end_idx=None):
    """Find non-overlapping signals in [start_idx, end_idx)."""
    if end_idx is None:
        end_idx = len(df)
    closes = df["close"].values
    rets = np.empty(len(closes))
    rets[:lookback] = np.nan
    rets[lookback:] = closes[lookback:] / closes[:-lookback] - 1.0
    candidate = np.where((rets <= threshold) & (np.arange(len(rets)) >= max(start_idx, lookback))
                         & (np.arange(len(rets)) < end_idx))[0]
    if len(candidate) == 0:
        return []
    selected = [candidate[0]]
    for idx in candidate[1:]:
        if idx - selected[-1] >= cooldown:
            selected.append(idx)
    return selected


def simulate(df, indices, hold):
    closes = df["close"].values
    n = len(closes)
    rows = []
    for idx in indices:
        if idx + hold >= n:
            continue
        entry = float(closes[idx])
        exit_p = float(closes[idx + hold])
        rows.append({
            "entry_time": df["timestamp"].iloc[idx],
            "entry_idx": idx,
            "gross_ret": exit_p / entry - 1.0,
            "net_ret": exit_p / entry - 1.0 - COST,
            "hold": hold,
        })
    return pd.DataFrame(rows)


def select_best_params(df, train_start_idx, train_end_idx, grid_thr, grid_hold,
                       lookback=60, min_n=8):
    """Pick (thr, hold) that maximizes sum_net on TRAIN slice. Require min_n trades."""
    best_score = -np.inf
    best = None
    for thr in grid_thr:
        for hold in grid_hold:
            sigs = find_signals(df, lookback, thr, hold, train_start_idx, train_end_idx)
            trades = simulate(df, sigs, hold)
            # Only keep trades whose entry is within train slice (already filtered by find_signals)
            if len(trades) < min_n:
                continue
            score = trades["net_ret"].sum()
            if score > best_score:
                best_score = score
                best = (thr, hold, len(trades), trades["net_ret"].mean(), trades["net_ret"].sum())
    return best


def main():
    print("Loading...")
    df = load()
    df["month"] = df["timestamp"].dt.to_period("M")
    months = sorted(df["month"].unique())
    print(f"Months: {months[0]} ... {months[-1]}, total {len(months)}")

    # We need at least 6 months of training data before first OOS
    INITIAL_TRAIN_MONTHS = 6
    LOOKBACK = 60

    grid_thr = [-0.02, -0.03, -0.05, -0.07, -0.10]
    grid_hold = [60, 120, 240, 480]

    # Build month-end indices
    month_end_idx = {}
    for m in months:
        end_idx = df[df["month"] == m].index.max() + 1
        month_end_idx[m] = end_idx

    # ====================================================================
    # Adaptive: each month, pick best from grid using past data only
    # ====================================================================
    print(f"\n{'=' * 78}")
    print("Adaptive walk-forward — pick best (thr, hold) each month from past data")
    print(f"{'=' * 78}")

    print(f"\n{'OOS_month':<12} {'chosen_thr':>11} {'hold':>5} {'TR_n':>5} {'TR_mean':>9} | "
          f"{'OOS_n':>5} {'OOS_mean':>10} {'OOS_sum':>10}")

    all_oos_trades = []
    chosen_params_log = []

    for i in range(INITIAL_TRAIN_MONTHS, len(months)):
        oos_month = months[i]
        train_end_idx = month_end_idx[months[i - 1]]
        oos_start_idx = train_end_idx
        oos_end_idx = month_end_idx[oos_month]

        # Select best params on training slice
        best = select_best_params(df, 0, train_end_idx, grid_thr, grid_hold,
                                  lookback=LOOKBACK, min_n=5)
        if best is None:
            print(f"{str(oos_month):<12}  no_param_found")
            continue
        thr, hold, tr_n, tr_mean, tr_sum = best

        # Apply to OOS month
        oos_sigs = find_signals(df, LOOKBACK, thr, hold, oos_start_idx, oos_end_idx)
        oos_trades = simulate(df, oos_sigs, hold)

        oos_n = len(oos_trades)
        oos_mean = oos_trades["net_ret"].mean() if oos_n > 0 else 0.0
        oos_sum = oos_trades["net_ret"].sum() if oos_n > 0 else 0.0

        print(f"{str(oos_month):<12} {thr:>+10.1%} {hold:>5} {tr_n:>5} {tr_mean:>+8.3%} | "
              f"{oos_n:>5} {oos_mean:>+9.3%} {oos_sum:>+9.4f}")

        if oos_n > 0:
            all_oos_trades.append(oos_trades.assign(oos_month=str(oos_month)))
        chosen_params_log.append({
            "oos_month": str(oos_month), "thr": thr, "hold": hold,
            "tr_n": tr_n, "tr_mean": tr_mean,
            "oos_n": oos_n, "oos_mean": oos_mean, "oos_sum": oos_sum,
        })

    chosen_log = pd.DataFrame(chosen_params_log)
    chosen_log.to_csv(CACHE / "walkforward_log.csv", index=False)

    if all_oos_trades:
        all_oos = pd.concat(all_oos_trades, ignore_index=True)
        days_oos = (df.iloc[month_end_idx[months[INITIAL_TRAIN_MONTHS - 1]]]["timestamp"]
                    - df.iloc[month_end_idx[months[-1]] - 1]["timestamp"]).total_seconds() / -86400
        # use total OOS duration
        first_oos_month = months[INITIAL_TRAIN_MONTHS]
        last_oos_month = months[-1]
        first_idx = df[df["month"] == first_oos_month].index.min()
        last_idx = df[df["month"] == last_oos_month].index.max()
        days_oos = (df.iloc[last_idx]["timestamp"] - df.iloc[first_idx]["timestamp"]).total_seconds() / 86400

        total_n = len(all_oos)
        wr = (all_oos["net_ret"] > 0).mean()
        mean_ret = all_oos["net_ret"].mean()
        total_pnl = all_oos["net_ret"].sum()
        apy = total_pnl / days_oos * 365 * 100

        print(f"\n{'=' * 78}")
        print(f"AGGREGATE TRUE OOS RESULTS (adaptive)")
        print(f"{'=' * 78}")
        print(f"  OOS period:        {first_oos_month} → {last_oos_month} ({days_oos:.0f} days)")
        print(f"  Total OOS trades:  {total_n}")
        print(f"  Win rate:          {wr:.1%}")
        print(f"  Mean net per trade: {mean_ret:+.4%}")
        print(f"  Total OOS PnL:     {total_pnl:+.4f}")
        print(f"  Annualized:        {apy:+.2f}%")

    # ====================================================================
    # Naive: always use -5% / 240min from day 1 (no parameter selection)
    # ====================================================================
    print(f"\n{'=' * 78}")
    print("NAIVE: always trade -5% / 240min from day 1, no parameter changes")
    print(f"{'=' * 78}")
    first_oos_idx = month_end_idx[months[INITIAL_TRAIN_MONTHS - 1]]
    last_idx = month_end_idx[months[-1]]
    sigs = find_signals(df, LOOKBACK, -0.05, 240, first_oos_idx, last_idx)
    naive = simulate(df, sigs, 240)
    days = (df.iloc[last_idx - 1]["timestamp"] - df.iloc[first_oos_idx]["timestamp"]).total_seconds() / 86400
    print(f"  N: {len(naive)}")
    if len(naive) > 0:
        print(f"  win rate: {(naive['net_ret']>0).mean():.1%}")
        print(f"  mean net: {naive['net_ret'].mean():+.4%}")
        print(f"  total:    {naive['net_ret'].sum():+.4f}")
        print(f"  APY:      {naive['net_ret'].sum() / days * 365 * 100:+.2f}%")

    # ====================================================================
    # Naive2: -7% / 240min
    # ====================================================================
    print(f"\nNAIVE2: always trade -7% / 240min")
    sigs2 = find_signals(df, LOOKBACK, -0.07, 240, first_oos_idx, last_idx)
    naive2 = simulate(df, sigs2, 240)
    print(f"  N: {len(naive2)}")
    if len(naive2) > 0:
        print(f"  win rate: {(naive2['net_ret']>0).mean():.1%}")
        print(f"  mean net: {naive2['net_ret'].mean():+.4%}")
        print(f"  total:    {naive2['net_ret'].sum():+.4f}")
        print(f"  APY:      {naive2['net_ret'].sum() / days * 365 * 100:+.2f}%")

    # ====================================================================
    # Plot
    # ====================================================================
    fig, axes = plt.subplots(2, 1, figsize=(13, 9))

    # Chosen parameter over time
    if len(chosen_log) > 0:
        chosen_log["param_str"] = chosen_log["thr"].apply(lambda x: f"{x:+.1%}") + "/" + chosen_log["hold"].astype(str) + "m"
        axes[0].plot(chosen_log["oos_month"], chosen_log["thr"] * 100, marker="o", label="threshold")
        axes[0].set_ylabel("Threshold %")
        axes[0].set_xlabel("OOS month")
        axes[0].set_title("Walk-forward: which threshold did the model pick each month?")
        axes[0].grid(alpha=0.3)
        axes[0].legend()
        axes[0].tick_params(axis="x", rotation=45)

    # Cumulative OOS PnL
    if all_oos_trades:
        all_oos_sorted = all_oos.sort_values("entry_time").reset_index(drop=True)
        all_oos_sorted["cum_net"] = all_oos_sorted["net_ret"].cumsum()
        axes[1].plot(all_oos_sorted["entry_time"], all_oos_sorted["cum_net"] * 100,
                     marker="o", label=f"adaptive (N={len(all_oos)})")
    if len(naive) > 0:
        naive_sorted = naive.sort_values("entry_time").reset_index(drop=True)
        naive_sorted["cum_net"] = naive_sorted["net_ret"].cumsum()
        axes[1].plot(naive_sorted["entry_time"], naive_sorted["cum_net"] * 100,
                     marker="s", label=f"naive -5%/240m (N={len(naive)})", alpha=0.7)
    if len(naive2) > 0:
        naive2_sorted = naive2.sort_values("entry_time").reset_index(drop=True)
        naive2_sorted["cum_net"] = naive2_sorted["net_ret"].cumsum()
        axes[1].plot(naive2_sorted["entry_time"], naive2_sorted["cum_net"] * 100,
                     marker="^", label=f"naive -7%/240m (N={len(naive2)})", alpha=0.7)
    axes[1].axhline(0, color="black", linewidth=0.5)
    axes[1].set_title("Cumulative OOS net P&L — true walk-forward (no future peeking)")
    axes[1].set_ylabel("Cumulative net %")
    axes[1].set_xlabel("Entry date")
    axes[1].legend()
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("xrp_true_walkforward.png", dpi=120)
    plt.close(fig)
    print("\nSaved xrp_true_walkforward.png")


if __name__ == "__main__":
    main()
