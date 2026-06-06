"""
B: BTC 1-min momentum/mean-reversion strategies.

Apply the same methodology used on penny stocks to BTC, where we have
clean 24/7 data and known low transaction costs.

Strategies tested:
  1. Time-of-day seasonality (does BTC have hour-of-day pattern?)
  2. Spike continuation: 1-hour return > X → buy, hold N min
  3. Mean reversion: 1-hour return < -X → buy, hold N min
  4. Volatility breakout: ATR breakout
  5. Daily momentum: yesterday up → today buy

Costs: Binance spot taker 0.10% per side = 0.20% round-trip
       (lower than penny stocks 3-5%)

Sample size: 2 years × 1440 min/day × 365 = ~1M bars
"""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

CACHE = Path("btc_cache")
ROUND_TRIP_FEE = 0.002  # 0.20% spot round-trip


def load_1m():
    df = pd.read_csv(CACHE / "spot_1m_2y.csv")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def main() -> None:
    print("Loading 1-minute BTC data...")
    df = load_1m()
    print(f"N bars: {len(df):,}")
    print(f"Date range: {df['timestamp'].min()} → {df['timestamp'].max()}")
    days = (df["timestamp"].max() - df["timestamp"].min()).total_seconds() / 86400
    print(f"Days: {days:.0f}")

    # Compute returns
    df["ret_1m"] = df["close"].pct_change()
    df["log_ret_1m"] = np.log(df["close"] / df["close"].shift(1))

    print(f"\nMean 1-min log return: {df['log_ret_1m'].mean():+.6f} ({df['log_ret_1m'].mean()*1440*365*100:+.2f}% annualized)")
    print(f"Std 1-min log return: {df['log_ret_1m'].std():.6f}")
    print(f"Annualized vol: {df['log_ret_1m'].std() * np.sqrt(1440*365) * 100:.1f}%")

    # ====================================================================
    # H1: Time of day seasonality
    # ====================================================================
    print("\n" + "=" * 78)
    print("H1: Hour-of-day seasonality (UTC)")
    print("=" * 78)
    df["hour"] = df["timestamp"].dt.hour
    df["dayofweek"] = df["timestamp"].dt.dayofweek
    by_hour = df.groupby("hour")["log_ret_1m"].agg(["mean", "std", "size"])
    by_hour["annualized_pct"] = by_hour["mean"] * 60 * 24 * 365 * 100
    by_hour["t_stat"] = by_hour["mean"] / (by_hour["std"] / np.sqrt(by_hour["size"]))
    print(f"\n{'hour':>5} {'mean_ret':>12} {'annual%':>10} {'t-stat':>8}")
    for h, row in by_hour.iterrows():
        sig = " *" if abs(row["t_stat"]) > 2 else ""
        print(f"{h:>5d} {row['mean']:>+11.7f} {row['annualized_pct']:>+9.3f}% {row['t_stat']:>+7.2f}{sig}")

    # Hour-of-week
    print("\n" + "=" * 78)
    print("H1b: Day-of-week seasonality (0=Mon, 6=Sun)")
    print("=" * 78)
    by_dow = df.groupby("dayofweek")["log_ret_1m"].agg(["mean", "std", "size"])
    by_dow["annualized_pct"] = by_dow["mean"] * 60 * 24 * 365 * 100
    print(f"\n{'dow':>5} {'mean_ret':>12} {'annual%':>10}")
    for d, row in by_dow.iterrows():
        print(f"{d:>5d} {row['mean']:>+11.7f} {row['annualized_pct']:>+9.3f}%")

    # ====================================================================
    # H2: 1-hour momentum continuation
    # ====================================================================
    print("\n" + "=" * 78)
    print("H2: 1-hour momentum continuation")
    print("=" * 78)
    df["ret_60m"] = df["close"].pct_change(60)  # 60-min return
    df["fwd_60m"] = df["close"].shift(-60) / df["close"] - 1.0  # forward 60-min

    # Bin by past 60-min return
    bins = [-1, -0.05, -0.02, -0.01, -0.005, 0, 0.005, 0.01, 0.02, 0.05, 1]
    labels = ["<-5%", "-5%~-2%", "-2%~-1%", "-1%~-0.5%", "-0.5%~0%",
              "0%~0.5%", "0.5%~1%", "1%~2%", "2%~5%", ">+5%"]
    df["mom_bucket"] = pd.cut(df["ret_60m"], bins=bins, labels=labels)
    bucket_stats = df.groupby("mom_bucket", observed=True)["fwd_60m"].agg(["mean", "size"])
    bucket_stats["annualized"] = bucket_stats["mean"] * 24 * 365 * 100
    print(f"\nForward 60-min return given past 60-min return:")
    print(f"\n{'past 60m':<14} {'N':>9} {'fwd_60m_mean':>14} {'annualized':>12} {'net@0.2%':>11}")
    for b, row in bucket_stats.iterrows():
        net = row["mean"] - ROUND_TRIP_FEE
        net_ann = net * 24 * 365 * 100
        print(f"{str(b):<14} {int(row['size']):>9} {row['mean']:>+13.5%} {row['annualized']:>+11.2f}% {net_ann:>+10.2f}%")

    # ====================================================================
    # H3: Time-of-day combined with momentum
    # ====================================================================
    print("\n" + "=" * 78)
    print("H3: Top hours from H1 — what's the alpha?")
    print("=" * 78)
    # Identify the 3 best and 3 worst hours
    best_hours = by_hour.nlargest(3, "mean").index.tolist()
    worst_hours = by_hour.nsmallest(3, "mean").index.tolist()
    print(f"\nBest 3 hours (UTC): {best_hours}")
    print(f"Worst 3 hours (UTC): {worst_hours}")

    # Strategy: long during best hours only, short during worst hours
    df["best_hour"] = df["hour"].isin(best_hours)
    df["worst_hour"] = df["hour"].isin(worst_hours)

    # Long at start of best hour, exit at end of best hour
    print(f"\nStrategy: long during 'best' hours, hold 1 hour each")
    # Each session = 60 bars in those hours
    # We approximate: gather log returns during those hour starts
    hour_start = df["timestamp"].dt.minute == 0
    # Returns from hour_start to next hour_start (= 60-min ahead)
    df["ret_next_hour"] = df["close"].shift(-60) / df["close"] - 1.0
    long_best = df.loc[hour_start & df["best_hour"], "ret_next_hour"].dropna()
    short_worst = -df.loc[hour_start & df["worst_hour"], "ret_next_hour"].dropna()

    n_long = len(long_best)
    n_short = len(short_worst)
    print(f"\n{'strategy':<25} {'N_trades':>9} {'mean':>10} {'win%':>7} {'gross_total':>12} {'net@0.2%':>10}")
    for label, series in [("Long best hours", long_best), ("Short worst hours", short_worst)]:
        if len(series) == 0:
            continue
        gross = series.sum()
        net = gross - len(series) * ROUND_TRIP_FEE
        net_ann = net / (days / 365) * 100
        print(f"{label:<25} {len(series):>9} {series.mean():>+9.5%} {(series>0).mean():>6.1%} {gross:>+11.4%} {net_ann:>+9.2f}%")

    # ====================================================================
    # H4: Train-test split for momentum strategy
    # ====================================================================
    print("\n" + "=" * 78)
    print("H4: OOS test of momentum continuation (train first 70%, test last 30%)")
    print("=" * 78)
    split_idx = int(len(df) * 0.7)
    train = df.iloc[:split_idx]
    test = df.iloc[split_idx:]
    print(f"Train: {train['timestamp'].min()} → {train['timestamp'].max()}")
    print(f"Test:  {test['timestamp'].min()} → {test['timestamp'].max()}")

    # Best 'mom_bucket' on train
    tr_bucket = train.groupby("mom_bucket", observed=True)["fwd_60m"].mean()
    print(f"\nTrain mean fwd_60m by past_60m bucket:")
    for b, v in tr_bucket.items():
        print(f"  {b}: {v:+.5%}")

    best_bucket_train = tr_bucket.idxmax()
    print(f"\nBest bucket on TRAIN: {best_bucket_train} (mean {tr_bucket[best_bucket_train]:+.5%})")

    # Apply to test
    test_subset = test[test["mom_bucket"] == best_bucket_train]
    test_rets = test_subset["fwd_60m"].dropna()
    if len(test_rets) > 0:
        gross = test_rets.sum()
        net = gross - len(test_rets) * ROUND_TRIP_FEE
        days_test = (test["timestamp"].max() - test["timestamp"].min()).total_seconds() / 86400
        annual = net / (days_test / 365) * 100
        print(f"\nTest results (entering when past 60m in '{best_bucket_train}' bucket):")
        print(f"  N trades: {len(test_rets):,}")
        print(f"  mean return per trade: {test_rets.mean():+.5%}")
        print(f"  win rate: {(test_rets>0).mean():.1%}")
        print(f"  gross total: {gross:+.4%}")
        print(f"  net total (0.2% fee): {net:+.4%}")
        print(f"  annualized: {annual:+.2f}%")

    # Plot 1: hourly seasonality
    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    by_hour["annualized_pct"].plot(kind="bar", ax=axes[0], color="steelblue")
    axes[0].axhline(0, color="black", linewidth=0.5)
    axes[0].set_title("BTC hourly seasonality — annualized return per hour bucket")
    axes[0].set_xlabel("Hour (UTC)")
    axes[0].set_ylabel("Annualized %")
    axes[0].grid(alpha=0.3)

    # Plot 2: momentum continuation
    bucket_stats["annualized"].plot(kind="bar", ax=axes[1], color="orange")
    axes[1].axhline(0, color="black", linewidth=0.5)
    axes[1].axhline(ROUND_TRIP_FEE * 24 * 365 * 100, color="red", linestyle="--",
                    label=f"breakeven ({ROUND_TRIP_FEE*24*365*100:.0f}% per trade if hourly)")
    axes[1].set_title("BTC 60m forward return given past 60m return (annualized)")
    axes[1].set_xlabel("Past 60-min return bucket")
    axes[1].set_ylabel("Annualized fwd return %")
    axes[1].legend()
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("btc_momentum.png", dpi=120)
    plt.close(fig)
    print("\nSaved btc_momentum.png")


if __name__ == "__main__":
    main()
