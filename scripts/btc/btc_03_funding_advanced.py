"""
A: Advanced funding strategies.

Refinements over btc_02:
  1. Multi-coin: BTC, ETH, SOL, BNB — portfolio approach
  2. Hysteresis: enter when funding > X, EXIT only when funding < Y (Y < X)
     This avoids churn on every sign flip
  3. Realistic fee model:
     - Spot leg: 0.10% taker each side (0.20% round-trip)
     - Perp leg: 0.05% taker each side (0.10% round-trip)
     - Total round-trip: 0.30%
  4. Basis cost (slippage between spot vs perp price): 0.05% per round-trip
  5. Per-coin and combined portfolio analysis

Expected funding rates differ across coins:
  - BTC: lowest funding (most efficient)
  - ETH: slightly higher
  - SOL/BNB/altcoins: typically higher (less efficient market)
"""
import json
import time
import urllib.request
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

CACHE = Path("btc_cache")
CACHE.mkdir(exist_ok=True)

COINS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
ROUND_TRIP_FEE = 0.003  # 0.30%
BASIS_COST = 0.0005     # 0.05% per RT


def fetch_funding(symbol: str, days: int = 730) -> pd.DataFrame:
    target = CACHE / f"funding_{symbol}_{days}d.csv"
    if target.exists():
        df = pd.read_csv(target)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, format="ISO8601")
        df["fundingRate"] = df["fundingRate"].astype(float)
        return df
    end = int(datetime.utcnow().timestamp() * 1000)
    start = int((datetime.utcnow() - timedelta(days=days)).timestamp() * 1000)
    out = []
    cur = start
    print(f"  fetching {symbol}...")
    while cur < end:
        url = (
            f"https://fapi.binance.com/fapi/v1/fundingRate"
            f"?symbol={symbol}&startTime={cur}&endTime={end}&limit=1000"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "btc-val/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            print(f"    err: {e}")
            time.sleep(5)
            continue
        if not data:
            break
        out.extend(data)
        cur = data[-1]["fundingTime"] + 1
        time.sleep(0.05)
    df = pd.DataFrame(out)
    df["fundingRate"] = df["fundingRate"].astype(float)
    df["timestamp"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    df.to_csv(target, index=False)
    return df


def simulate_strategy(funding: pd.DataFrame, enter_thr: float, exit_thr: float,
                     fee_rt: float = ROUND_TRIP_FEE, basis: float = BASIS_COST) -> dict:
    """Hysteresis-based: enter when funding > enter_thr, exit when funding < exit_thr."""
    f = funding["fundingRate"].values
    in_pos = False
    accrued = 0.0
    n_trades = 0
    pos_history = []
    pnl_history = []
    cum = 0.0
    for i, rate in enumerate(f):
        if not in_pos and rate > enter_thr:
            in_pos = True
            n_trades += 1
            cum -= (fee_rt + basis)  # entry cost
        elif in_pos and rate < exit_thr:
            in_pos = False
            # exit cost already counted in next entry's fee_rt? No — fee_rt is RT.
            # We charged fee_rt at entry as RT. So no exit cost here.
            pass
        if in_pos:
            cum += rate
            accrued += rate
        pos_history.append(in_pos)
        pnl_history.append(cum)
    in_market = sum(pos_history) / len(pos_history)
    days = (funding["timestamp"].iloc[-1] - funding["timestamp"].iloc[0]).total_seconds() / 86400
    annualized = cum / days * 365
    return {
        "n_trades": n_trades,
        "in_market_pct": in_market,
        "gross_funding": accrued,
        "total_fees": n_trades * (fee_rt + basis),
        "net_pnl": cum,
        "annualized": annualized,
        "pnl_series": pnl_history,
    }


def main() -> None:
    # Fetch all coins
    print("Fetching funding data for all coins...")
    coin_data = {}
    for sym in COINS:
        df = fetch_funding(sym)
        coin_data[sym] = df
        print(f"  {sym}: {len(df)} records, mean rate {df['fundingRate'].mean():+.6%}")

    # Per-coin stats
    print("\n" + "=" * 78)
    print("Per-coin funding rate statistics (per 8hr)")
    print("=" * 78)
    print(f"\n{'coin':<10} {'mean':>11} {'median':>11} {'std':>11} {'pos_pct':>9} {'2y_total':>11}")
    for sym, df in coin_data.items():
        days = (df["timestamp"].max() - df["timestamp"].min()).total_seconds() / 86400
        print(
            f"{sym:<10} "
            f"{df['fundingRate'].mean():>+10.6%} "
            f"{df['fundingRate'].median():>+10.6%} "
            f"{df['fundingRate'].std():>10.6%} "
            f"{(df['fundingRate']>0).mean():>8.1%} "
            f"{df['fundingRate'].sum():>+10.4%}"
        )

    # Strategy comparison: always-on vs hysteresis
    print("\n" + "=" * 78)
    print("Strategy: Always-on perpetual short hedge (collect ALL funding)")
    print("=" * 78)
    print("\nNet annualized after one-time setup fee (0.30% + 0.05% basis):")
    print(f"\n{'coin':<10} {'gross':>10} {'net_setup':>11} {'annualized':>12}")
    for sym, df in coin_data.items():
        days = (df["timestamp"].max() - df["timestamp"].min()).total_seconds() / 86400
        gross = df["fundingRate"].sum()
        net = gross - (ROUND_TRIP_FEE + BASIS_COST)
        annual = net / days * 365 * 100
        print(f"{sym:<10} {gross:>+9.4%} {net:>+10.4%} {annual:>+11.2f}%")

    # Hysteresis strategies for BTC
    print("\n" + "=" * 78)
    print("Hysteresis strategy on BTC (enter > X, exit < Y)")
    print("=" * 78)
    btc = coin_data["BTCUSDT"]
    print(f"\n{'enter':<8} {'exit':<8} {'trades':>7} {'in_mkt':>7} {'gross':>10} {'fees':>10} {'net':>10} {'APY':>9}")
    for enter, exit_ in [
        (0.0, -0.001/100),    # always on, exit on negative
        (0.001/100, -0.005/100),  # tiny positive enter, exit on negative
        (0.005/100, -0.001/100),
        (0.01/100, 0.0),
        (0.05/100, 0.0),
        (0.10/100, 0.0),
    ]:
        r = simulate_strategy(btc, enter, exit_)
        days = (btc["timestamp"].iloc[-1] - btc["timestamp"].iloc[0]).total_seconds() / 86400
        apy = r["net_pnl"] / days * 365 * 100
        print(
            f">{enter*10000:>+5.1f}bps "
            f"<{exit_*10000:>+5.1f}bps "
            f"{r['n_trades']:>7} "
            f"{r['in_market_pct']:>6.1%} "
            f"{r['gross_funding']:>+9.4%} "
            f"{r['total_fees']:>9.4%} "
            f"{r['net_pnl']:>+9.4%} "
            f"{apy:>+8.2f}%"
        )

    # Equal-weight portfolio of 4 coins (always-on)
    print("\n" + "=" * 78)
    print("Equal-weight portfolio (BTC + ETH + SOL + BNB, always-on)")
    print("=" * 78)
    # Align on common dates
    aligned = pd.DataFrame()
    for sym, df in coin_data.items():
        s = df.set_index("timestamp")["fundingRate"]
        aligned[sym] = s
    aligned = aligned.dropna()
    aligned["portfolio"] = aligned.mean(axis=1)
    days = (aligned.index[-1] - aligned.index[0]).total_seconds() / 86400
    gross = aligned["portfolio"].sum()
    # Setup fees: 4 coins × 0.35% one-time = 1.4% total
    setup_fee_total = (ROUND_TRIP_FEE + BASIS_COST) * 4
    net = gross - setup_fee_total
    apy = net / days * 365 * 100
    print(f"\nN events:          {len(aligned)}")
    print(f"Days:              {days:.0f}")
    print(f"Gross funding:     {gross:+.4%}")
    print(f"Setup fees (4 ×):  {setup_fee_total:.4%}")
    print(f"Net:               {net:+.4%}")
    print(f"Annualized:        {apy:+.2f}%")

    # Compare 90d rolling APY
    aligned["rolling_90d_btc"] = aligned["BTCUSDT"].rolling(270).sum() / 90 * 365 * 100
    aligned["rolling_90d_port"] = aligned["portfolio"].rolling(270).sum() / 90 * 365 * 100
    print(f"\n{'coin/port':<14} {'avg_90d_apy':>12} {'min':>9} {'max':>9} {'pct_pos':>9}")
    for col, label in [
        ("BTCUSDT", "BTC alone"),
        ("portfolio", "4-coin portfolio"),
    ]:
        rolling = aligned[col].rolling(270).sum() / 90 * 365 * 100
        rolling = rolling.dropna()
        print(
            f"{label:<14} "
            f"{rolling.mean():>+11.2f}% "
            f"{rolling.min():>+8.2f}% "
            f"{rolling.max():>+8.2f}% "
            f"{(rolling>0).mean():>8.1%}"
        )

    # Per-year comparison
    print("\n" + "=" * 78)
    print("Per-year breakdown — portfolio (always-on)")
    print("=" * 78)
    aligned_reset = aligned.reset_index()
    aligned_reset["year"] = aligned_reset["timestamp"].dt.year
    by_year = aligned_reset.groupby("year")["portfolio"].agg(["sum", "size", lambda x: (x>0).mean()])
    by_year.columns = ["total", "n", "pos_pct"]
    by_year["annualized"] = by_year["total"] / by_year["n"] * 1095 * 100
    print(f"\n{'year':<8} {'n':>6} {'total':>10} {'pos%':>8} {'annual':>10}")
    for yr, row in by_year.iterrows():
        print(f"{yr:<8} {int(row['n']):>6} {row['total']:>+9.4%} {row['pos_pct']:>7.1%} {row['annualized']:>+9.2f}%")

    # Plot: per-coin cumulative funding
    fig, axes = plt.subplots(2, 1, figsize=(12, 9))
    for sym in COINS:
        df = coin_data[sym]
        axes[0].plot(df["timestamp"], df["fundingRate"].cumsum() * 100, label=sym)
    axes[0].axhline(0, color="black", linewidth=0.5)
    axes[0].set_title("Cumulative funding rate by coin (short perp earns this)")
    axes[0].set_ylabel("Cumulative %")
    axes[0].legend()
    axes[0].grid(alpha=0.3)

    axes[1].plot(aligned.index, aligned["BTCUSDT"].rolling(270).sum() / 90 * 365 * 100, label="BTC")
    axes[1].plot(aligned.index, aligned["portfolio"].rolling(270).sum() / 90 * 365 * 100,
                 label="4-coin portfolio", linewidth=2)
    axes[1].axhline(0, color="black", linewidth=0.5)
    axes[1].axhline(10, color="green", linestyle="--", linewidth=0.7, label="+10% APY")
    axes[1].set_title("Rolling 90d annualized APY")
    axes[1].set_ylabel("APY %")
    axes[1].legend()
    axes[1].grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig("btc_funding_advanced.png", dpi=120)
    plt.close(fig)
    print("\nSaved btc_funding_advanced.png")


if __name__ == "__main__":
    main()
