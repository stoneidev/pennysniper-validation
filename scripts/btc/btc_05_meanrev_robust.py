"""
Robust OOS test of BTC mean-reversion signal.

Initial finding: when 60-min return < -5%, forward 60-min mean = +5.98%.
But N=14 is too small. Verify with:

  1. Wider net: use threshold sweep -2%, -3%, -4%, -5%
  2. Proper non-overlapping trades (no double-counting)
  3. Walk-forward (multiple train/test splits, not just one)
  4. Sensitivity to hold time (30, 60, 120, 240 min)
  5. Realistic costs (0.20% Binance taker round-trip, +0.05% slippage)
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

CACHE = Path("btc_cache")
FEE_RT = 0.002  # 0.20% round-trip
SLIPPAGE_RT = 0.0005  # 0.05% slippage estimate


def load():
    df = pd.read_csv(CACHE / "spot_1m_2y.csv")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def find_signals(df: pd.DataFrame, lookback_min: int, threshold: float, cooldown_min: int):
    """
    Find non-overlapping signals.
      - At each bar t, look at return from t-lookback to t.
      - If return <= threshold, mark as signal.
      - Enforce cooldown: skip new signals within cooldown_min after a triggered one.
    """
    df = df.copy()
    df["ret_lookback"] = df["close"].pct_change(lookback_min)
    last_signal = -np.inf
    signals = []
    for i in range(lookback_min, len(df)):
        if df["ret_lookback"].iloc[i] <= threshold and i - last_signal >= cooldown_min:
            signals.append(i)
            last_signal = i
    return signals


def simulate_long(df: pd.DataFrame, signal_indices: list, hold_min: int):
    """For each signal index, buy at close of signal bar, sell at close hold_min later."""
    rows = []
    for idx in signal_indices:
        if idx + hold_min >= len(df):
            continue
        entry = float(df["close"].iloc[idx])
        exit_p = float(df["close"].iloc[idx + hold_min])
        ret = exit_p / entry - 1.0
        rows.append({
            "entry_time": df["timestamp"].iloc[idx],
            "entry": entry,
            "exit": exit_p,
            "gross_ret": ret,
            "net_ret": ret - FEE_RT - SLIPPAGE_RT,
        })
    return pd.DataFrame(rows)


def main() -> None:
    print("Loading 1-min data...")
    df = load()
    days = (df["timestamp"].max() - df["timestamp"].min()).total_seconds() / 86400
    print(f"N bars: {len(df):,}, days: {days:.0f}")

    # ===================================================================
    # Test 1: Threshold + holding period grid
    # ===================================================================
    print("\n" + "=" * 78)
    print("Test 1: Mean reversion grid — full sample (in-sample warning)")
    print("=" * 78)

    LOOKBACK = 60
    print(f"Lookback: past {LOOKBACK} min return below threshold → buy")
    print(f"Cooldown: hold_min (no overlapping)")
    print(f"Cost: {FEE_RT*100:.1f}% RT fee + {SLIPPAGE_RT*100:.2f}% slippage = {(FEE_RT+SLIPPAGE_RT)*100:.2f}% total\n")

    print(f"{'thr':>6} {'hold':>5} {'N':>6} {'win%':>7} {'mean_gross':>11} {'mean_net':>10} {'sum_net':>9} {'apy':>9}")
    grid = []
    for threshold in [-0.005, -0.01, -0.015, -0.02, -0.03, -0.05]:
        for hold in [30, 60, 120, 240, 480]:
            signals = find_signals(df, LOOKBACK, threshold, hold)
            trades = simulate_long(df, signals, hold)
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

    # ===================================================================
    # Test 2: Walk-forward — pick best combo on first half, test on second
    # ===================================================================
    print("\n" + "=" * 78)
    print("Test 2: Walk-forward OOS — pick best combo on TRAIN, apply to TEST")
    print("=" * 78)

    split_idx = int(len(df) * 0.7)
    train = df.iloc[:split_idx].reset_index(drop=True)
    test = df.iloc[split_idx:].reset_index(drop=True)
    print(f"Train: {train['timestamp'].iloc[0]} → {train['timestamp'].iloc[-1]}")
    print(f"Test:  {test['timestamp'].iloc[0]} → {test['timestamp'].iloc[-1]}")
    days_train = (train["timestamp"].iloc[-1] - train["timestamp"].iloc[0]).total_seconds() / 86400
    days_test = (test["timestamp"].iloc[-1] - test["timestamp"].iloc[0]).total_seconds() / 86400

    train_grid = []
    for threshold in [-0.005, -0.01, -0.015, -0.02, -0.03]:
        for hold in [30, 60, 120, 240]:
            signals = find_signals(train, LOOKBACK, threshold, hold)
            trades = simulate_long(train, signals, hold)
            if len(trades) < 5:
                continue
            train_grid.append({"threshold": threshold, "hold": hold,
                               "n": len(trades), "mean_net": trades["net_ret"].mean(),
                               "sum_net": trades["net_ret"].sum()})
    tg = pd.DataFrame(train_grid)
    print(f"\nTrain top-5 by sum_net:")
    print(tg.nlargest(5, "sum_net").to_string(index=False))

    if len(tg) > 0:
        best = tg.nlargest(1, "sum_net").iloc[0]
        thr_b = best["threshold"]
        hold_b = int(best["hold"])
        print(f"\nBest train combo: threshold={thr_b:+.1%}, hold={hold_b}min")

        # Apply to test
        test_signals = find_signals(test, LOOKBACK, thr_b, hold_b)
        test_trades = simulate_long(test, test_signals, hold_b)
        print(f"\nTest (OOS) results:")
        print(f"  N trades: {len(test_trades)}")
        if len(test_trades) > 0:
            wr = (test_trades["net_ret"] > 0).mean()
            print(f"  win rate:    {wr:.1%}")
            print(f"  mean gross:  {test_trades['gross_ret'].mean():+.4%}")
            print(f"  mean net:    {test_trades['net_ret'].mean():+.4%}")
            print(f"  sum net:     {test_trades['net_ret'].sum():+.4f}")
            print(f"  APY:         {test_trades['net_ret'].sum() / days_test * 365 * 100:+.2f}%")

    # ===================================================================
    # Test 3: Stress test — bootstrapped confidence interval
    # ===================================================================
    print("\n" + "=" * 78)
    print("Test 3: Bootstrap on best in-sample combo")
    print("=" * 78)
    if len(grid) > 0:
        best_is = grid.nlargest(1, "sum_net").iloc[0]
        thr = best_is["threshold"]
        hold = int(best_is["hold"])
        print(f"\nBest in-sample combo: threshold={thr:+.1%}, hold={hold}min")
        signals = find_signals(df, LOOKBACK, thr, hold)
        trades = simulate_long(df, signals, hold)
        if len(trades) >= 10:
            np.random.seed(42)
            boots = []
            for _ in range(1000):
                samp = trades["net_ret"].sample(n=len(trades), replace=True)
                boots.append(samp.mean())
            ci_low = np.percentile(boots, 2.5)
            ci_high = np.percentile(boots, 97.5)
            print(f"\nN trades (in-sample): {len(trades)}")
            print(f"Mean net per trade:   {trades['net_ret'].mean():+.4%}")
            print(f"95% CI (bootstrap):   [{ci_low:+.4%}, {ci_high:+.4%}]")
            print(f"  → Even if OOS keeps mean, with {len(trades)} trades the uncertainty is wide")

    # ===================================================================
    # Test 4: Per-year breakdown
    # ===================================================================
    print("\n" + "=" * 78)
    print("Test 4: Per-year stability — best combo")
    print("=" * 78)
    if len(grid) > 0:
        best_is = grid.nlargest(1, "sum_net").iloc[0]
        thr = best_is["threshold"]
        hold = int(best_is["hold"])
        signals = find_signals(df, LOOKBACK, thr, hold)
        trades = simulate_long(df, signals, hold)
        if len(trades) > 0:
            trades["year"] = pd.to_datetime(trades["entry_time"]).dt.year
            by_year = trades.groupby("year").agg(
                n=("net_ret", "size"),
                mean_net=("net_ret", "mean"),
                sum_net=("net_ret", "sum"),
                win_rate=("net_ret", lambda x: (x > 0).mean()),
            )
            print(f"\nSignal: past 60min return <= {thr:+.1%}, hold {hold}min")
            print(f"\n{'year':<8} {'N':>6} {'win%':>7} {'mean_net':>10} {'sum_net':>9}")
            for yr, row in by_year.iterrows():
                print(f"{yr:<8} {int(row['n']):>6} {row['win_rate']:>6.1%} {row['mean_net']:>+9.4%} {row['sum_net']:>+8.4f}")

    grid.to_csv(CACHE / "meanrev_grid.csv", index=False)
    print(f"\nSaved {CACHE}/meanrev_grid.csv")


if __name__ == "__main__":
    main()
