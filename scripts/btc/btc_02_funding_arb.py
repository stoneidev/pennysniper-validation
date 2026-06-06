"""
BTC validation Step 2: Funding rate arbitrage backtest.

Strategy: Delta-neutral funding harvest.
  - When funding rate > threshold (e.g., > 0.01% per 8hr), open:
      LONG BTC spot + SHORT BTC perpetual (equal notional)
  - Hold while funding stays positive
  - Each 8hr funding event: short side RECEIVES funding from longs
  - Close when funding turns negative or below threshold

Returns:
  - Income: funding rate × notional × 3 events/day = annualized
  - Cost: 2× spot+perp open/close fees + funding spread

Binance fees (regular):
  - Spot taker:  0.10%
  - Spot maker:  0.10% (post 2022 BNB discount available)
  - Futures taker: 0.05%
  - Futures maker: 0.02%
  - We assume taker for both = 0.15% per round-trip per leg = 0.30% total round-trip

Conservative assumption: each entry+exit costs 0.30% total (0.15% × 2 legs).
"""
import pandas as pd
import numpy as np
from pathlib import Path

CACHE = Path("btc_cache")


def main() -> None:
    funding = pd.read_csv(CACHE / "funding_2y.csv")
    funding["timestamp"] = pd.to_datetime(funding["timestamp"], utc=True, format="ISO8601")
    funding = funding.sort_values("timestamp").reset_index(drop=True)
    funding["fundingRate"] = funding["fundingRate"].astype(float)

    print(f"Funding records: {len(funding)}")
    print(f"Date range:      {funding['timestamp'].min()} → {funding['timestamp'].max()}")
    print(f"\nFunding rate stats (per 8hr event):")
    print(f"  mean:   {funding['fundingRate'].mean():+.6%}")
    print(f"  median: {funding['fundingRate'].median():+.6%}")
    print(f"  std:    {funding['fundingRate'].std():.6%}")
    print(f"  positive events: {(funding['fundingRate']>0).sum()} / {len(funding)} = {(funding['fundingRate']>0).mean():.1%}")
    print(f"  negative events: {(funding['fundingRate']<0).sum()} / {len(funding)} = {(funding['fundingRate']<0).mean():.1%}")

    # Always-on strategy: every 8hr collect funding, regardless of direction
    # When positive: short perp earns. When negative: short perp pays.
    # If we hold delta-neutral perp short permanently, our return = sum of funding rates.
    print("\n" + "=" * 78)
    print("Strategy A: Always-on perpetual short hedge (collect ALL funding)")
    print("=" * 78)
    funding["cum_funding"] = funding["fundingRate"].cumsum()
    days = (funding["timestamp"].max() - funding["timestamp"].min()).total_seconds() / 86400
    total_funding = funding["fundingRate"].sum()
    daily_avg = total_funding / days * 100
    annual_pct = daily_avg * 365
    print(f"\nTotal funding accrued (gross): {total_funding:+.4%}")
    print(f"Days:                          {days:.0f}")
    print(f"Daily average:                 {daily_avg:+.4%}")
    print(f"Annualized:                    {annual_pct:+.2f}%")
    print(f"\nFee assumption:")
    print(f"  Setup: 0.15% × 2 legs = 0.30% (one-time)")
    print(f"  Held continuously, no rebalance fees")
    print(f"Net annualized: {annual_pct - 0.30:+.2f}% (year 1) or {annual_pct:+.2f}% (year 2+)")

    # Threshold-based: only short perp when funding > X
    print("\n" + "=" * 78)
    print("Strategy B: Threshold-based — enter only when funding > X")
    print("=" * 78)
    print("\nAssumes each entry/exit costs 0.30% (round-trip both legs)")
    print(f"\n{'threshold':<14} {'%events':>9} {'gross':>10} {'n_trades':>10} {'net':>10} {'annualized':>12}")
    for thr_bps in [0, 1, 2, 5, 10, 20, 50, 100]:
        thr = thr_bps / 10000  # bps to fraction
        in_position = funding["fundingRate"] > thr
        # Detect transitions to count trades
        prev = in_position.shift(1, fill_value=False)
        trades = ((in_position) & (~prev)).sum()
        gross = funding.loc[in_position, "fundingRate"].sum()
        net = gross - trades * 0.003
        net_annual = net / days * 365 * 100
        print(f">{thr_bps:>3}bps        {in_position.mean():>8.1%} {gross:>+9.4%} {trades:>10} {net:>+9.4%} {net_annual:>+11.2f}%")

    # Time-segmented: rolling 90-day window APY
    print("\n" + "=" * 78)
    print("Strategy C: Stability check — rolling 90-day annualized return")
    print("=" * 78)
    funding["rolling_90d"] = funding["fundingRate"].rolling(window=270).sum()  # 90 days × 3/day
    funding["rolling_90d_apy"] = funding["rolling_90d"] / 90 * 365 * 100
    print(f"\nRolling 90d APY:")
    print(f"  mean:    {funding['rolling_90d_apy'].mean():+.2f}%")
    print(f"  median:  {funding['rolling_90d_apy'].median():+.2f}%")
    print(f"  min:     {funding['rolling_90d_apy'].min():+.2f}%")
    print(f"  max:     {funding['rolling_90d_apy'].max():+.2f}%")
    print(f"  p10:     {funding['rolling_90d_apy'].quantile(0.10):+.2f}%")
    print(f"  p90:     {funding['rolling_90d_apy'].quantile(0.90):+.2f}%")
    print(f"  pct of windows positive: {(funding['rolling_90d_apy']>0).mean():.1%}")

    # Per-year breakdown
    print("\n" + "=" * 78)
    print("Strategy D: Per-year performance")
    print("=" * 78)
    funding["year"] = funding["timestamp"].dt.year
    by_year = funding.groupby("year").agg(
        n_events=("fundingRate", "size"),
        total_funding=("fundingRate", "sum"),
        positive_pct=("fundingRate", lambda x: (x > 0).mean()),
    )
    by_year["annualized"] = by_year["total_funding"] / by_year["n_events"] * 1095 * 100
    print(f"\n{'year':<8} {'n_events':>10} {'total':>10} {'pos%':>7} {'annualized':>12}")
    for yr, row in by_year.iterrows():
        print(f"{yr:<8} {int(row['n_events']):>10} {row['total_funding']:>+9.4%} {row['positive_pct']:>6.1%} {row['annualized']:>+11.2f}%")

    # Save
    funding[["timestamp", "fundingRate", "cum_funding", "rolling_90d_apy"]].to_csv(
        CACHE / "funding_analysis.csv", index=False
    )
    print(f"\nSaved {CACHE}/funding_analysis.csv")

    # Plot
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(12, 8))
    axes[0].plot(funding["timestamp"], funding["cum_funding"] * 100)
    axes[0].axhline(0, color="black", linewidth=0.5)
    axes[0].set_title("BTC/USDT Cumulative Funding Rate (Short perp earns this)")
    axes[0].set_ylabel("Cumulative %")
    axes[0].grid(alpha=0.3)

    axes[1].plot(funding["timestamp"], funding["rolling_90d_apy"])
    axes[1].axhline(0, color="black", linewidth=0.5)
    axes[1].axhline(10, color="green", linestyle="--", linewidth=0.7, label="+10% APY")
    axes[1].set_title("Rolling 90-day Annualized Return (Short perp delta-neutral)")
    axes[1].set_ylabel("Annualized %")
    axes[1].set_xlabel("Date")
    axes[1].legend()
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("btc_funding.png", dpi=120)
    plt.close(fig)
    print("Saved btc_funding.png")


if __name__ == "__main__":
    main()
