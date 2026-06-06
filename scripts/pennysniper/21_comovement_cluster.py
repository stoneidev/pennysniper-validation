"""
Step 21: Co-movement cluster signal — does "theme day" (multiple penny stocks
spiking simultaneously) predict next-day spillover?

Hypothesis: When 5+ penny stocks all spike +30% on the same day, it signals a
THEME (e.g., AI mania, biotech catalyst). Penny stocks in similar price/volume
profile that did NOT spike yet might catch up next day.

Critical: NEXT-DAY entry only uses information available at PRIOR-DAY close.
No look-ahead bias.

Strategy variants:
  V1. Buy ALL penny stocks at next-day open (broad spillover)
  V2. Buy only penny stocks that did NOT spike yet (catch-up)
  V3. Buy only penny stocks that spiked moderately (+10%~+30%) — partial momentum
"""
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

DAILY_CACHE = Path("price_cache")

PRICE_MIN = 1.0
PRICE_MAX = 10.0
SPIKE_THRESHOLD = 1.30  # high/open >= 1.30 = +30% spike
MIN_DOLLAR_VOL = 500_000

THEME_DAY_MIN_SPIKES = 5  # number of simultaneous spikes to call it "theme day"

TP = 0.05
SL = 0.03


def simulate_long_daily(o, h, l, c, tp_pct=TP, sl_pct=SL):
    if o <= 0 or pd.isna(o):
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
    # Load all daily data into one big dataframe
    print("Loading daily caches...")
    all_rows = []
    for f in sorted(DAILY_CACHE.glob("*.csv")):
        sym = f.stem
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
        except Exception:
            continue
        if len(df) < 5 or "Open" not in df.columns:
            continue
        df = df.sort_index()
        df["symbol"] = sym
        df["high_x_open"] = df["High"] / df["Open"]
        df["close_x_open"] = df["Close"] / df["Open"]
        df["dollar_vol"] = df["Close"] * df["Volume"]
        df = df.reset_index()
        # rename whatever the first col is to 'date'
        df = df.rename(columns={df.columns[0]: "date"})
        all_rows.append(df)
    big = pd.concat(all_rows, ignore_index=True)
    big = big.dropna(subset=["Open", "High", "Low", "Close", "Volume"])

    # Penny + liquid filter
    big["is_penny_liquid"] = (
        big["Open"].between(PRICE_MIN, PRICE_MAX) & (big["dollar_vol"] >= MIN_DOLLAR_VOL)
    )

    # Spike flag
    big["is_spike"] = big["is_penny_liquid"] & (big["high_x_open"] >= SPIKE_THRESHOLD)

    print(f"Total day-symbol rows: {len(big)}")
    print(f"Penny-liquid rows:     {big['is_penny_liquid'].sum()}")
    print(f"Spike rows:            {big['is_spike'].sum()}")

    # Count spikes per day
    daily = big.groupby(big["date"].dt.date).agg(
        n_penny_liquid=("is_penny_liquid", "sum"),
        n_spike=("is_spike", "sum"),
    )
    daily["theme_day"] = daily["n_spike"] >= THEME_DAY_MIN_SPIKES
    print(f"\nDays with N>=5 simultaneous spikes (theme days): "
          f"{daily['theme_day'].sum()}/{len(daily)} = {daily['theme_day'].mean():.1%}")

    print(f"\nDistribution of n_spike per day:")
    print(daily["n_spike"].describe(percentiles=[0.5, 0.75, 0.9, 0.95, 0.99]).to_string())

    # ========================================================================
    # Test: next-day entry on theme days vs control
    # ========================================================================
    big = big.sort_values(["symbol", "date"]).reset_index(drop=True)
    big["next_open"] = big.groupby("symbol")["Open"].shift(-1)
    big["next_high"] = big.groupby("symbol")["High"].shift(-1)
    big["next_low"] = big.groupby("symbol")["Low"].shift(-1)
    big["next_close"] = big.groupby("symbol")["Close"].shift(-1)

    big["date_only"] = big["date"].dt.date
    big["theme_day"] = big["date_only"].map(daily["theme_day"])
    big["n_spike_today"] = big["date_only"].map(daily["n_spike"])

    # Filter to penny-liquid stocks ONLY (universe of tradable)
    tradable = big[big["is_penny_liquid"] & big["next_open"].notna()].copy()

    # Simulate buying at next_open with TP/SL on next-day OHLC
    tradable["nxt_ret"] = tradable.apply(
        lambda r: simulate_long_daily(r["next_open"], r["next_high"], r["next_low"], r["next_close"]),
        axis=1,
    )
    tradable = tradable.dropna(subset=["nxt_ret"])

    # ========================================================================
    # Variant 1: Buy ALL penny on next day after theme day
    # ========================================================================
    print("\n" + "=" * 78)
    print("V1: Buy ALL penny-liquid stocks at next-day open (TP +5% / SL -3%)")
    print("=" * 78)
    print(f"\n{'condition':<35} {'N':>7} {'win%':>7} {'avg':>8} {'net@3%':>8}")
    for label, sub in [
        ("After theme day (>=5 spikes)", tradable[tradable["theme_day"]]),
        ("After non-theme day", tradable[~tradable["theme_day"]]),
        ("All days (baseline)", tradable),
    ]:
        if len(sub) == 0:
            continue
        wr = (sub["nxt_ret"] > 0).mean()
        avg = sub["nxt_ret"].mean()
        print(f"{label:<35} {len(sub):>7} {wr:>6.1%} {avg:>+7.3%} {avg-0.03:>+7.3%}")

    # ========================================================================
    # Variant 2: Buy only NON-spike stocks after theme day (catch-up trade)
    # ========================================================================
    print("\n" + "=" * 78)
    print("V2: Catch-up — after theme day, buy NON-spike penny stocks next day")
    print("=" * 78)
    print(f"\n{'condition':<40} {'N':>7} {'win%':>7} {'avg':>8} {'net@3%':>8}")
    for label, sub in [
        ("Theme day, non-spike today", tradable[tradable["theme_day"] & ~tradable["is_spike"]]),
        ("Theme day, did spike today", tradable[tradable["theme_day"] & tradable["is_spike"]]),
        ("Non-theme day, non-spike", tradable[~tradable["theme_day"] & ~tradable["is_spike"]]),
        ("Non-theme day, did spike", tradable[~tradable["theme_day"] & tradable["is_spike"]]),
    ]:
        if len(sub) == 0:
            continue
        wr = (sub["nxt_ret"] > 0).mean()
        avg = sub["nxt_ret"].mean()
        print(f"{label:<40} {len(sub):>7} {wr:>6.1%} {avg:>+7.3%} {avg-0.03:>+7.3%}")

    # ========================================================================
    # Variant 3: Sensitivity to theme threshold
    # ========================================================================
    print("\n" + "=" * 78)
    print("V3: Sensitivity to theme-day threshold")
    print("=" * 78)
    print(f"\n{'threshold':<12} {'theme_days':>11} {'N_trades':>10} {'win%':>7} {'avg':>8} {'net@3%':>8}")
    for thr in [3, 5, 8, 10, 15, 20]:
        theme_dates = set(daily.index[daily["n_spike"] >= thr])
        sub = tradable[tradable["date_only"].isin(theme_dates)]
        if len(sub) == 0:
            continue
        wr = (sub["nxt_ret"] > 0).mean()
        avg = sub["nxt_ret"].mean()
        print(f">= {thr:>3} spikes  {len(theme_dates):>11} {len(sub):>10} {wr:>6.1%} {avg:>+7.3%} {avg-0.03:>+7.3%}")

    # ========================================================================
    # Variant 4: Today's mild momentum + theme day = catch-up
    # ========================================================================
    print("\n" + "=" * 78)
    print("V4: Theme day + today's stock had MILD positive move (+5%~+30%)")
    print("    Hypothesis: stock joining theme but not yet exhausted")
    print("=" * 78)
    tradable["mild_move"] = (
        (tradable["high_x_open"] >= 1.05) & (tradable["high_x_open"] < 1.30)
    )
    print(f"\n{'condition':<40} {'N':>7} {'win%':>7} {'avg':>8} {'net@3%':>8}")
    for label, sub in [
        ("Theme + mild move", tradable[tradable["theme_day"] & tradable["mild_move"]]),
        ("Theme + flat", tradable[tradable["theme_day"] & ~tradable["mild_move"] & ~tradable["is_spike"]]),
        ("Non-theme + mild move", tradable[~tradable["theme_day"] & tradable["mild_move"]]),
    ]:
        if len(sub) == 0:
            continue
        wr = (sub["nxt_ret"] > 0).mean()
        avg = sub["nxt_ret"].mean()
        print(f"{label:<40} {len(sub):>7} {wr:>6.1%} {avg:>+7.3%} {avg-0.03:>+7.3%}")

    # Save full tradable for further analysis
    tradable[["symbol", "date_only", "is_spike", "theme_day", "n_spike_today",
              "high_x_open", "mild_move", "nxt_ret"]].to_csv("comovement_results.csv", index=False)
    print(f"\nSaved comovement_results.csv ({len(tradable)} rows)")


if __name__ == "__main__":
    main()
