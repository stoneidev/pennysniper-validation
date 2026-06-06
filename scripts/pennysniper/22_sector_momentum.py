"""
Step 22: Sector momentum spillover test.

Get sector for each penny stock via yfinance. For each (sector, date) pair:
  - Count how many stocks in that sector spiked +30%
  - If >= 2 spiked, mark sector as "hot"
  - Test: buy non-spiked stocks in same hot sector next day

Cache sector metadata to disk to avoid re-fetching.
"""
import json
import time
from pathlib import Path
import pandas as pd
import numpy as np
import yfinance as yf

DAILY_CACHE = Path("price_cache")
SECTOR_CACHE = Path("sector_cache.json")

PRICE_MIN = 1.0
PRICE_MAX = 10.0
SPIKE_THRESHOLD = 1.30
MIN_DOLLAR_VOL = 500_000
SECTOR_HOT_MIN = 2  # require >= 2 spikes in same sector to call it hot

TP = 0.05
SL = 0.03


def get_sectors(symbols: list[str]) -> dict:
    cache = {}
    if SECTOR_CACHE.exists():
        with open(SECTOR_CACHE) as f:
            cache = json.load(f)

    missing = [s for s in symbols if s not in cache]
    if not missing:
        return cache

    print(f"Fetching sectors for {len(missing)} symbols (yfinance)...")
    for i, sym in enumerate(missing, 1):
        try:
            t = yf.Ticker(sym)
            info = t.info
            cache[sym] = {
                "sector": info.get("sector", "Unknown"),
                "industry": info.get("industry", "Unknown"),
            }
        except Exception:
            cache[sym] = {"sector": "Unknown", "industry": "Unknown"}
        if i % 25 == 0:
            print(f"  {i}/{len(missing)} fetched")
            with open(SECTOR_CACHE, "w") as f:
                json.dump(cache, f)
        time.sleep(0.1)
    with open(SECTOR_CACHE, "w") as f:
        json.dump(cache, f)
    return cache


def simulate_long_daily(o, h, l, c, tp_pct=TP, sl_pct=SL):
    if pd.isna(o) or o <= 0:
        return None
    tp_p = o * (1 + tp_pct)
    sl_p = o * (1 - sl_pct)
    sl_hit = l <= sl_p
    tp_hit = h >= tp_p
    if sl_hit and tp_hit:
        return -sl_pct
    if sl_hit:
        return -sl_pct
    if tp_hit:
        return tp_pct
    return c / o - 1.0


def main() -> None:
    # Load all daily data
    print("Loading daily caches...")
    rows = []
    for f in sorted(DAILY_CACHE.glob("*.csv")):
        sym = f.stem
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
        except Exception:
            continue
        if len(df) < 5 or "Open" not in df.columns:
            continue
        df = df.sort_index().reset_index()
        df = df.rename(columns={df.columns[0]: "date"})
        df["symbol"] = sym
        df["high_x_open"] = df["High"] / df["Open"]
        df["dollar_vol"] = df["Close"] * df["Volume"]
        rows.append(df)
    big = pd.concat(rows, ignore_index=True)
    big = big.dropna(subset=["Open", "High", "Low", "Close", "Volume"])

    # Penny + liquid
    big["is_penny_liquid"] = big["Open"].between(PRICE_MIN, PRICE_MAX) & (big["dollar_vol"] >= MIN_DOLLAR_VOL)
    big["is_spike"] = big["is_penny_liquid"] & (big["high_x_open"] >= SPIKE_THRESHOLD)

    # Sectors
    symbols = big["symbol"].unique().tolist()
    sectors_map = get_sectors(symbols)
    big["sector"] = big["symbol"].map(lambda s: sectors_map.get(s, {}).get("sector", "Unknown"))

    print(f"\nSector distribution:")
    print(big[big["is_penny_liquid"]]["sector"].value_counts().head(15).to_string())

    # For each (date, sector), count spikes
    big["date_only"] = big["date"].dt.date
    sector_day = big[big["is_penny_liquid"]].groupby(["date_only", "sector"]).agg(
        n_in_sector=("symbol", "size"),
        n_spike_in_sector=("is_spike", "sum"),
    ).reset_index()

    # Mark hot sector-days
    sector_day["sector_hot"] = sector_day["n_spike_in_sector"] >= SECTOR_HOT_MIN

    # Merge back: for each penny-liquid (symbol, date), is its sector hot today?
    big = big.merge(
        sector_day[["date_only", "sector", "sector_hot", "n_spike_in_sector"]],
        on=["date_only", "sector"],
        how="left",
    )
    big["sector_hot"] = big["sector_hot"].fillna(False).astype(bool)
    big["n_spike_in_sector"] = big["n_spike_in_sector"].fillna(0).astype(int)

    # Next-day OHLC
    big = big.sort_values(["symbol", "date"]).reset_index(drop=True)
    big["next_open"] = big.groupby("symbol")["Open"].shift(-1)
    big["next_high"] = big.groupby("symbol")["High"].shift(-1)
    big["next_low"] = big.groupby("symbol")["Low"].shift(-1)
    big["next_close"] = big.groupby("symbol")["Close"].shift(-1)

    tradable = big[big["is_penny_liquid"] & big["next_open"].notna()].copy()
    tradable["nxt_ret"] = tradable.apply(
        lambda r: simulate_long_daily(r["next_open"], r["next_high"], r["next_low"], r["next_close"]),
        axis=1,
    )
    tradable = tradable.dropna(subset=["nxt_ret"])

    print(f"\nTotal tradable next-day events: {len(tradable)}")
    print(f"Hot-sector subset: {tradable['sector_hot'].sum()}")

    # ========================================================================
    # Test 1: Hot vs cold sector days
    # ========================================================================
    print("\n" + "=" * 78)
    print("Sector hot day → buy any penny stock in sector next day")
    print("=" * 78)
    print(f"\n{'condition':<40} {'N':>7} {'win%':>7} {'avg':>8} {'net@3%':>8}")
    for label, sub in [
        ("Sector HOT (>=2 spikes today)", tradable[tradable["sector_hot"]]),
        ("Sector cold", tradable[~tradable["sector_hot"]]),
        ("All baseline", tradable),
    ]:
        if len(sub) == 0:
            continue
        wr = (sub["nxt_ret"] > 0).mean()
        avg = sub["nxt_ret"].mean()
        print(f"{label:<40} {len(sub):>7} {wr:>6.1%} {avg:>+7.3%} {avg-0.03:>+7.3%}")

    # Test 2: Hot sector AND today's stock did NOT spike yet (catch-up)
    print("\n" + "=" * 78)
    print("Catch-up: hot sector + this stock did NOT spike yet today")
    print("=" * 78)
    print(f"\n{'condition':<45} {'N':>7} {'win%':>7} {'avg':>8} {'net@3%':>8}")
    for label, sub in [
        ("Hot sector + non-spike today", tradable[tradable["sector_hot"] & ~tradable["is_spike"]]),
        ("Hot sector + did spike today", tradable[tradable["sector_hot"] & tradable["is_spike"]]),
        ("Cold sector + non-spike today", tradable[~tradable["sector_hot"] & ~tradable["is_spike"]]),
    ]:
        if len(sub) == 0:
            continue
        wr = (sub["nxt_ret"] > 0).mean()
        avg = sub["nxt_ret"].mean()
        print(f"{label:<45} {len(sub):>7} {wr:>6.1%} {avg:>+7.3%} {avg-0.03:>+7.3%}")

    # Test 3: Sensitivity — require >=N spikes in sector
    print("\n" + "=" * 78)
    print("Sensitivity: require >= N spikes in same sector")
    print("=" * 78)
    print(f"\n{'threshold':<10} {'N_trades':>10} {'win%':>7} {'avg':>8} {'net@3%':>8}")
    for thr in [1, 2, 3, 4, 5, 7, 10]:
        sub = tradable[tradable["n_spike_in_sector"] >= thr]
        if len(sub) == 0:
            continue
        wr = (sub["nxt_ret"] > 0).mean()
        avg = sub["nxt_ret"].mean()
        print(f">= {thr:>3}     {len(sub):>10} {wr:>6.1%} {avg:>+7.3%} {avg-0.03:>+7.3%}")

    # Test 4: Hot sector + sub-bucket by today's stock movement
    print("\n" + "=" * 78)
    print("Hot sector + today's stock movement bucket")
    print("=" * 78)
    print(f"\n{'today range':<25} {'N':>7} {'win%':>7} {'avg':>8} {'net@3%':>8}")
    hot = tradable[tradable["sector_hot"]].copy()
    hot["bucket"] = pd.cut(
        hot["high_x_open"],
        bins=[-np.inf, 1.0, 1.05, 1.10, 1.20, 1.30, 1.50, 2.0, np.inf],
        labels=["<+0%", "+0~+5%", "+5~+10%", "+10~+20%", "+20~+30%", "+30~+50%", "+50~+100%", ">+100%"],
    )
    for label, g in hot.groupby("bucket", observed=True):
        if len(g) == 0:
            continue
        wr = (g["nxt_ret"] > 0).mean()
        avg = g["nxt_ret"].mean()
        print(f"{str(label):<25} {len(g):>7} {wr:>6.1%} {avg:>+7.3%} {avg-0.03:>+7.3%}")

    tradable[["symbol", "date_only", "sector", "is_spike", "sector_hot",
              "n_spike_in_sector", "high_x_open", "nxt_ret"]].to_csv("sector_results.csv", index=False)
    print("\nSaved sector_results.csv")


if __name__ == "__main__":
    main()
