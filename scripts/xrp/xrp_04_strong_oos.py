"""
XRP -7% strong signal: direct OOS verification.

The grid found N=27-35 trades at -7% threshold with mean_net +2.5-3.5%
and bootstrap 95% CI fully positive.

Question: does this signal hold OOS?

Approach:
  1. Train (first 70%): verify -7% is meaningfully positive on train alone
  2. Test (last 30%): apply -7% signal directly. Report.
  3. Use multiple hold periods to check robustness
  4. Sensitivity: what if we use -5%, -7%, -10%? Does the conclusion hold?
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

CACHE = Path("xrp_cache")
FEE_RT = 0.002
SLIPPAGE_RT = 0.0005
COST = FEE_RT + SLIPPAGE_RT


def load():
    df = pd.read_csv(CACHE / "spot_1m_2y.csv")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    return df.sort_values("timestamp").reset_index(drop=True)


def find_signals_vec(df, lookback_min, threshold, cooldown_min):
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


def simulate(df, indices, hold_min):
    closes = df["close"].values
    rows = []
    for idx in indices:
        if idx + hold_min >= len(closes):
            continue
        entry = float(closes[idx])
        exit_p = float(closes[idx + hold_min])
        rows.append({
            "entry_time": df["timestamp"].iloc[idx],
            "entry": entry,
            "exit": exit_p,
            "gross_ret": exit_p / entry - 1.0,
            "net_ret": exit_p / entry - 1.0 - COST,
        })
    return pd.DataFrame(rows)


def main():
    df = load()
    days_total = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).total_seconds() / 86400
    print(f"XRP 1m: {len(df):,} bars, {days_total:.0f} days")

    split_idx = int(len(df) * 0.7)
    train = df.iloc[:split_idx].reset_index(drop=True)
    test = df.iloc[split_idx:].reset_index(drop=True)
    days_train = (train["timestamp"].iloc[-1] - train["timestamp"].iloc[0]).total_seconds() / 86400
    days_test = (test["timestamp"].iloc[-1] - test["timestamp"].iloc[0]).total_seconds() / 86400
    print(f"Train: {train['timestamp'].iloc[0].date()} → {train['timestamp'].iloc[-1].date()} ({days_train:.0f}d)")
    print(f"Test:  {test['timestamp'].iloc[0].date()} → {test['timestamp'].iloc[-1].date()} ({days_test:.0f}d)")

    LOOKBACK = 60

    # ========================================================================
    # Direct OOS for strong signals
    # ========================================================================
    print("\n" + "=" * 78)
    print("Direct OOS test: strong mean-reversion signals")
    print("=" * 78)
    print(f"\n{'thr':>6} {'hold':>5} {'TR_N':>5} {'TR_mean':>9} {'TR_apy':>8} | {'TS_N':>5} {'TS_mean':>9} {'TS_win%':>8} {'TS_apy':>8}")

    rows = []
    for threshold in [-0.03, -0.05, -0.07, -0.10]:
        for hold in [60, 120, 240, 480]:
            tr_sigs = find_signals_vec(train, LOOKBACK, threshold, hold)
            tr_trades = simulate(train, tr_sigs, hold)
            ts_sigs = find_signals_vec(test, LOOKBACK, threshold, hold)
            ts_trades = simulate(test, ts_sigs, hold)
            if len(tr_trades) < 3 or len(ts_trades) < 3:
                continue
            tr_apy = tr_trades["net_ret"].sum() / days_train * 365 * 100
            ts_apy = ts_trades["net_ret"].sum() / days_test * 365 * 100
            ts_win = (ts_trades["net_ret"] > 0).mean()
            print(
                f"{threshold:>+5.1%} {hold:>5} "
                f"{len(tr_trades):>5} {tr_trades['net_ret'].mean():>+8.3%} {tr_apy:>+7.2f}% | "
                f"{len(ts_trades):>5} {ts_trades['net_ret'].mean():>+8.3%} {ts_win:>7.1%} {ts_apy:>+7.2f}%"
            )
            rows.append({
                "threshold": threshold, "hold": hold,
                "tr_n": len(tr_trades), "tr_mean": tr_trades["net_ret"].mean(), "tr_apy": tr_apy,
                "ts_n": len(ts_trades), "ts_mean": ts_trades["net_ret"].mean(),
                "ts_win": ts_win, "ts_apy": ts_apy,
            })

    summary = pd.DataFrame(rows)
    summary.to_csv(CACHE / "strong_oos.csv", index=False)

    # ========================================================================
    # Best by OOS mean_net
    # ========================================================================
    print("\n" + "=" * 78)
    print("Sorted by OOS mean_net (cherry-picking warning):")
    print("=" * 78)
    print(summary.sort_values("ts_mean", ascending=False).head(8).to_string(index=False))

    # ========================================================================
    # Per-year for the best -7% combo
    # ========================================================================
    print("\n" + "=" * 78)
    print("Full sample per-year for thr=-7%, hold=240min")
    print("=" * 78)
    sigs = find_signals_vec(df, LOOKBACK, -0.07, 240)
    trades = simulate(df, sigs, 240)
    if len(trades) > 0:
        trades["year"] = pd.to_datetime(trades["entry_time"]).dt.year
        by_year = trades.groupby("year").agg(
            n=("net_ret", "size"),
            win_rate=("net_ret", lambda x: (x > 0).mean()),
            mean_net=("net_ret", "mean"),
            sum_net=("net_ret", "sum"),
        )
        print(f"\n{'year':<8} {'N':>5} {'win%':>7} {'mean_net':>10} {'sum_net':>9}")
        for yr, row in by_year.iterrows():
            print(f"{yr:<8} {int(row['n']):>5} {row['win_rate']:>6.1%} {row['mean_net']:>+9.4%} {row['sum_net']:>+8.4f}")

    # Plot equity curve for strongest robust combo
    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    sigs = find_signals_vec(df, LOOKBACK, -0.07, 240)
    trades = simulate(df, sigs, 240)
    trades = trades.sort_values("entry_time").reset_index(drop=True)
    trades["cum_net"] = trades["net_ret"].cumsum()
    axes[0].plot(pd.to_datetime(trades["entry_time"]), trades["cum_net"] * 100, marker="o")
    axes[0].axhline(0, color="black", linewidth=0.5)
    axes[0].set_title(f"XRP mean-reversion equity curve: thr=-7%, hold=240min, N={len(trades)}")
    axes[0].set_ylabel("Cumulative net return (%)")
    axes[0].grid(alpha=0.3)

    sigs2 = find_signals_vec(df, LOOKBACK, -0.05, 240)
    trades2 = simulate(df, sigs2, 240).sort_values("entry_time").reset_index(drop=True)
    trades2["cum_net"] = trades2["net_ret"].cumsum()
    axes[1].plot(pd.to_datetime(trades2["entry_time"]), trades2["cum_net"] * 100, marker="o", color="orange")
    axes[1].axhline(0, color="black", linewidth=0.5)
    axes[1].set_title(f"XRP mean-reversion equity curve: thr=-5%, hold=240min, N={len(trades2)}")
    axes[1].set_ylabel("Cumulative net return (%)")
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("xrp_meanrev_equity.png", dpi=120)
    plt.close(fig)
    print("\nSaved xrp_meanrev_equity.png")


if __name__ == "__main__":
    main()
