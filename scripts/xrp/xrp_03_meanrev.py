"""
XRP mean reversion validation — same methodology as BTC.

XRP has higher volatility than BTC, so mean reversion signals may be larger
and more frequent. We test the same threshold × hold grid + walk-forward OOS.

Vectorized for speed (BTC version was Python loop and took 6+ min).
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

CACHE = Path("xrp_cache")
FEE_RT = 0.002
SLIPPAGE_RT = 0.0005


def load():
    df = pd.read_csv(CACHE / "spot_1m_2y.csv")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def find_signals_vec(df, lookback_min, threshold, cooldown_min):
    """Vectorized: find non-overlapping signal indices."""
    closes = df["close"].values
    rets = np.empty(len(closes))
    rets[:lookback_min] = np.nan
    rets[lookback_min:] = closes[lookback_min:] / closes[:-lookback_min] - 1.0
    candidate = np.where(rets <= threshold)[0]
    if len(candidate) == 0:
        return []
    selected = [candidate[0]]
    for idx in candidate[1:]:
        if idx - selected[-1] >= cooldown_min:
            selected.append(idx)
    return selected


def simulate_long(df, indices, hold_min):
    closes = df["close"].values
    rows = []
    for idx in indices:
        if idx + hold_min >= len(closes):
            continue
        entry = float(closes[idx])
        exit_p = float(closes[idx + hold_min])
        ret = exit_p / entry - 1.0
        rows.append({
            "entry_time": df["timestamp"].iloc[idx],
            "entry": entry,
            "exit": exit_p,
            "gross_ret": ret,
            "net_ret": ret - FEE_RT - SLIPPAGE_RT,
        })
    return pd.DataFrame(rows)


def main():
    print("Loading XRP 1-min data...")
    df = load()
    days = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).total_seconds() / 86400
    print(f"N bars: {len(df):,}, days: {days:.0f}")

    # Compute volatility for context
    df["log_ret"] = np.log(df["close"] / df["close"].shift(1))
    print(f"Mean 1-min log return:  {df['log_ret'].mean():+.6f}")
    print(f"Std 1-min log return:   {df['log_ret'].std():.6f}")
    print(f"Annualized vol (XRP):   {df['log_ret'].std() * np.sqrt(1440 * 365) * 100:.1f}%")

    LOOKBACK = 60
    print(f"\n{'thr':>6} {'hold':>5} {'N':>6} {'win%':>7} {'mean_gross':>11} {'mean_net':>10} {'sum_net':>9} {'apy':>9}")
    grid = []
    for threshold in [-0.005, -0.01, -0.015, -0.02, -0.03, -0.05, -0.07, -0.10]:
        for hold in [30, 60, 120, 240, 480]:
            sigs = find_signals_vec(df, LOOKBACK, threshold, hold)
            trades = simulate_long(df, sigs, hold)
            if len(trades) < 3:
                continue
            wr = (trades["net_ret"] > 0).mean()
            mg = trades["gross_ret"].mean()
            mn = trades["net_ret"].mean()
            sn = trades["net_ret"].sum()
            apy = sn / days * 365 * 100
            grid.append({"threshold": threshold, "hold": hold, "n": len(trades),
                         "win_rate": wr, "mean_gross": mg, "mean_net": mn, "sum_net": sn, "apy": apy})
            print(f"{threshold:>+5.1%} {hold:>5} {len(trades):>6} {wr:>6.1%} "
                  f"{mg:>+10.4%} {mn:>+9.4%} {sn:>+8.4f} {apy:>+8.2f}%")

    grid = pd.DataFrame(grid)

    # Walk-forward OOS
    print("\n" + "=" * 78)
    print("Walk-forward OOS — pick best on TRAIN, apply to TEST")
    print("=" * 78)
    split_idx = int(len(df) * 0.7)
    train = df.iloc[:split_idx].reset_index(drop=True)
    test = df.iloc[split_idx:].reset_index(drop=True)
    days_test = (test["timestamp"].iloc[-1] - test["timestamp"].iloc[0]).total_seconds() / 86400

    train_grid = []
    for threshold in [-0.005, -0.01, -0.015, -0.02, -0.03, -0.05, -0.07, -0.10]:
        for hold in [30, 60, 120, 240, 480]:
            sigs = find_signals_vec(train, LOOKBACK, threshold, hold)
            trades = simulate_long(train, sigs, hold)
            if len(trades) < 5:
                continue
            train_grid.append({"threshold": threshold, "hold": hold, "n": len(trades),
                               "mean_net": trades["net_ret"].mean(),
                               "sum_net": trades["net_ret"].sum()})
    tg = pd.DataFrame(train_grid)
    print(f"\nTrain top-5 by sum_net:")
    print(tg.nlargest(5, "sum_net").to_string(index=False))

    if len(tg) > 0:
        best = tg.nlargest(1, "sum_net").iloc[0]
        thr_b = best["threshold"]
        hold_b = int(best["hold"])
        print(f"\nBest train combo: threshold={thr_b:+.1%}, hold={hold_b}min")
        sigs_test = find_signals_vec(test, LOOKBACK, thr_b, hold_b)
        test_trades = simulate_long(test, sigs_test, hold_b)
        if len(test_trades) > 0:
            wr = (test_trades["net_ret"] > 0).mean()
            apy = test_trades["net_ret"].sum() / days_test * 365 * 100
            print(f"\nTest (OOS) results:")
            print(f"  N trades: {len(test_trades)}")
            print(f"  win rate:    {wr:.1%}")
            print(f"  mean gross:  {test_trades['gross_ret'].mean():+.4%}")
            print(f"  mean net:    {test_trades['net_ret'].mean():+.4%}")
            print(f"  sum net:     {test_trades['net_ret'].sum():+.4f}")
            print(f"  APY:         {apy:+.2f}%")
        else:
            print("  No test trades.")

    # Per-year breakdown for best combo
    print("\n" + "=" * 78)
    print("Per-year breakdown — best in-sample combo")
    print("=" * 78)
    if len(grid) > 0:
        best_is = grid.nlargest(1, "sum_net").iloc[0]
        thr = best_is["threshold"]
        hold = int(best_is["hold"])
        sigs = find_signals_vec(df, LOOKBACK, thr, hold)
        trades = simulate_long(df, sigs, hold)
        if len(trades) > 0:
            trades["year"] = pd.to_datetime(trades["entry_time"]).dt.year
            by_year = trades.groupby("year").agg(
                n=("net_ret", "size"),
                mean_net=("net_ret", "mean"),
                sum_net=("net_ret", "sum"),
                win_rate=("net_ret", lambda x: (x > 0).mean()),
            )
            print(f"\nSignal: past 60min ret <= {thr:+.1%}, hold {hold}min")
            print(f"{'year':<8} {'N':>6} {'win%':>7} {'mean_net':>10} {'sum_net':>9}")
            for yr, row in by_year.iterrows():
                print(f"{yr:<8} {int(row['n']):>6} {row['win_rate']:>6.1%} {row['mean_net']:>+9.4%} {row['sum_net']:>+8.4f}")

    # Bootstrap CI on second-best (more robust due to higher N)
    print("\n" + "=" * 78)
    print("Bootstrap confidence interval — top combos by N (more robust)")
    print("=" * 78)
    # Use combos with N>=30 for stability
    stable = grid[grid["n"] >= 30].copy()
    if len(stable) > 0:
        for _, row in stable.nlargest(3, "mean_net").iterrows():
            thr = row["threshold"]
            hold = int(row["hold"])
            sigs = find_signals_vec(df, LOOKBACK, thr, hold)
            trades = simulate_long(df, sigs, hold)
            if len(trades) < 10:
                continue
            np.random.seed(42)
            boots = [trades["net_ret"].sample(n=len(trades), replace=True).mean() for _ in range(1000)]
            ci_low = np.percentile(boots, 2.5)
            ci_high = np.percentile(boots, 97.5)
            print(f"\n  thr={thr:+.1%} hold={hold}min N={len(trades)}")
            print(f"    mean net: {trades['net_ret'].mean():+.4%}")
            print(f"    95% CI:   [{ci_low:+.4%}, {ci_high:+.4%}]")
            mean_apy = trades["net_ret"].mean() * (1440 / hold) * 365 * 100 / (len(trades) / (days * (1440/hold/100)))
            apy = trades["net_ret"].sum() / days * 365 * 100
            print(f"    Realized APY: {apy:+.2f}%")

    grid.to_csv(CACHE / "meanrev_grid.csv", index=False)


if __name__ == "__main__":
    main()
