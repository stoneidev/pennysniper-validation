"""XRP funding analysis + BTC comparison."""
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pathlib import Path

ROUND_TRIP_FEE = 0.003 + 0.0005  # 0.30% fee + 0.05% basis = 0.35% one-time setup


def load(path):
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
    df["fundingRate"] = df["fundingRate"].astype(float)
    return df.sort_values("timestamp").reset_index(drop=True)


btc = load("btc_cache/funding_2y.csv")
xrp = load("xrp_cache/funding_2y.csv")

print("=" * 78)
print("Funding rate comparison: BTC vs XRP (2 years)")
print("=" * 78)

print(f"\n{'metric':<28} {'BTC':>14} {'XRP':>14}")
for label, fn in [
    ("N events", lambda x: len(x)),
    ("date range start", lambda x: x['timestamp'].min().date().isoformat()),
    ("date range end", lambda x: x['timestamp'].max().date().isoformat()),
    ("mean rate (8hr)", lambda x: f"{x['fundingRate'].mean():+.6%}"),
    ("median rate (8hr)", lambda x: f"{x['fundingRate'].median():+.6%}"),
    ("std (8hr)", lambda x: f"{x['fundingRate'].std():.6%}"),
    ("max rate", lambda x: f"{x['fundingRate'].max():+.4%}"),
    ("min rate", lambda x: f"{x['fundingRate'].min():+.4%}"),
    ("positive %", lambda x: f"{(x['fundingRate']>0).mean():.1%}"),
    ("2y total funding", lambda x: f"{x['fundingRate'].sum():+.4%}"),
]:
    print(f"{label:<28} {str(fn(btc)):>14} {str(fn(xrp)):>14}")

# APY computation
print(f"\n{'strategy (always-on hedge)':<32} {'BTC APY':>10} {'XRP APY':>10}")
for label, df in [("BTC", btc), ("XRP", xrp)]:
    days = (df["timestamp"].max() - df["timestamp"].min()).total_seconds() / 86400
    gross = df["fundingRate"].sum()
    net = gross - ROUND_TRIP_FEE
    apy = net / days * 365 * 100
    pass

btc_days = (btc["timestamp"].max() - btc["timestamp"].min()).total_seconds() / 86400
xrp_days = (xrp["timestamp"].max() - xrp["timestamp"].min()).total_seconds() / 86400

btc_net_apy = (btc["fundingRate"].sum() - ROUND_TRIP_FEE) / btc_days * 365 * 100
xrp_net_apy = (xrp["fundingRate"].sum() - ROUND_TRIP_FEE) / xrp_days * 365 * 100
print(f"{'gross 2y total':<32} {btc['fundingRate'].sum():>+9.4%} {xrp['fundingRate'].sum():>+9.4%}")
print(f"{'net (after 0.35% setup)':<32} {btc['fundingRate'].sum()-ROUND_TRIP_FEE:>+9.4%} {xrp['fundingRate'].sum()-ROUND_TRIP_FEE:>+9.4%}")
print(f"{'annualized':<32} {btc_net_apy:>+9.2f}% {xrp_net_apy:>+9.2f}%")

# Per-year breakdown
print("\n" + "=" * 78)
print("Per-year breakdown — XRP")
print("=" * 78)
xrp["year"] = xrp["timestamp"].dt.year
by_year = xrp.groupby("year").agg(
    n=("fundingRate", "size"),
    total=("fundingRate", "sum"),
    pos_pct=("fundingRate", lambda x: (x>0).mean()),
    mean_rate=("fundingRate", "mean"),
)
by_year["annualized"] = by_year["total"] / by_year["n"] * 1095 * 100
print(f"\n{'year':<8} {'N':>5} {'total':>10} {'pos%':>8} {'annualized':>12}")
for yr, row in by_year.iterrows():
    print(f"{yr:<8} {int(row['n']):>5} {row['total']:>+9.4%} {row['pos_pct']:>7.1%} {row['annualized']:>+11.2f}%")

# Rolling 90d APY
print("\n" + "=" * 78)
print("Rolling 90-day annualized APY (BTC vs XRP)")
print("=" * 78)
for label, df in [("BTC", btc), ("XRP", xrp)]:
    df = df.copy()
    df["roll_90d_apy"] = df["fundingRate"].rolling(270).sum() / 90 * 365 * 100
    r = df["roll_90d_apy"].dropna()
    print(f"\n{label}: mean={r.mean():+.2f}% median={r.median():+.2f}% min={r.min():+.2f}% max={r.max():+.2f}% pct_pos={(r>0).mean():.1%}")

# Plot
fig, axes = plt.subplots(2, 1, figsize=(12, 9))
btc_cum = btc.copy()
btc_cum["cum"] = btc_cum["fundingRate"].cumsum() * 100
xrp_cum = xrp.copy()
xrp_cum["cum"] = xrp_cum["fundingRate"].cumsum() * 100
axes[0].plot(btc_cum["timestamp"], btc_cum["cum"], label="BTC")
axes[0].plot(xrp_cum["timestamp"], xrp_cum["cum"], label="XRP", linewidth=2)
axes[0].axhline(0, color="black", linewidth=0.5)
axes[0].set_title("Cumulative funding rate: BTC vs XRP (2y)")
axes[0].set_ylabel("Cumulative %")
axes[0].legend()
axes[0].grid(alpha=0.3)

btc_cum["roll"] = btc_cum["fundingRate"].rolling(270).sum() / 90 * 365 * 100
xrp_cum["roll"] = xrp_cum["fundingRate"].rolling(270).sum() / 90 * 365 * 100
axes[1].plot(btc_cum["timestamp"], btc_cum["roll"], label="BTC")
axes[1].plot(xrp_cum["timestamp"], xrp_cum["roll"], label="XRP", linewidth=2)
axes[1].axhline(0, color="black", linewidth=0.5)
axes[1].axhline(10, color="green", linestyle="--", linewidth=0.7, label="+10% APY")
axes[1].set_title("Rolling 90d annualized APY")
axes[1].set_ylabel("APY %")
axes[1].legend()
axes[1].grid(alpha=0.3)
fig.tight_layout()
fig.savefig("xrp_funding_compare.png", dpi=120)
plt.close(fig)
print("\nSaved xrp_funding_compare.png")
