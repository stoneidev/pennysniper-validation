"""
Step 20: Critical validation — does the "flat gap → buy at open" signal work
on the FULL penny stock universe, or only on pre-selected spike days?

If alpha persists across ALL flat-gap penny stock days, signal is real.
If alpha disappears, the +3.81% finding was selection bias from spike-only sample.

Method:
  - For every (symbol, date) in daily cache where:
      * abs(open / prev_close - 1) < 0.05  (flat gap)
      * 1 <= open <= 10  (penny range)
      * close * volume >= $500k (liquidity)
  - Simulate: buy at open, +5% TP / -3% SL using daily OHLC.
    Pessimistic: if low <= SL and high >= TP same day, SL fires first.
    Held to close otherwise.
  - Aggregate stats. Compare to spike-day subset.
"""
import pandas as pd
import numpy as np
from pathlib import Path

DAILY_CACHE = Path("price_cache")
GAP_THRESHOLD = 0.05  # |gap| < 5%
PRICE_MIN = 1.0
PRICE_MAX = 10.0
MIN_DOLLAR_VOL = 500_000

TP = 0.05
SL = 0.03


def simulate_day_long(o, h, l, c, tp_pct, sl_pct):
    """Daily-bar simulation: long at open, +TP / -SL.
    Pessimistic: SL fires first if same day touches both."""
    tp_p = o * (1 + tp_pct)
    sl_p = o * (1 - sl_pct)
    sl_hit = l <= sl_p
    tp_hit = h >= tp_p
    if sl_hit and tp_hit:
        return -sl_pct, "sl_first"
    if sl_hit:
        return -sl_pct, "sl"
    if tp_hit:
        return tp_pct, "tp"
    return c / o - 1.0, "close"


def main() -> None:
    rows = []
    csv_files = sorted(DAILY_CACHE.glob("*.csv"))
    print(f"Scanning {len(csv_files)} daily cache files...")

    for f in csv_files:
        sym = f.stem
        try:
            df = pd.read_csv(f, index_col=0, parse_dates=True)
        except Exception:
            continue
        if len(df) < 5:
            continue
        if not all(c in df.columns for c in ["Open", "High", "Low", "Close", "Volume"]):
            continue
        df = df.sort_index()
        prev_close = df["Close"].shift(1)
        gap = df["Open"] / prev_close - 1.0

        valid = (
            (df["Open"] > 0)
            & (df["Open"].between(PRICE_MIN, PRICE_MAX))
            & (df["Close"] * df["Volume"] >= MIN_DOLLAR_VOL)
            & (gap.abs() < GAP_THRESHOLD)
            & gap.notna()
        )

        for ts in df.index[valid]:
            o = float(df.loc[ts, "Open"])
            h = float(df.loc[ts, "High"])
            l = float(df.loc[ts, "Low"])
            c = float(df.loc[ts, "Close"])
            ret, reason = simulate_day_long(o, h, l, c, TP, SL)
            rows.append({
                "symbol": sym,
                "date": ts.strftime("%Y-%m-%d"),
                "gap": float(gap.loc[ts]),
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "ret": ret,
                "reason": reason,
                "intraday_high_x_open": h / o,
                "is_spike": int(h / o >= 1.30),
            })

    df = pd.DataFrame(rows)
    print(f"\nTotal flat-gap penny stock days: {len(df)}")
    print(f"  unique symbols: {df['symbol'].nunique()}")
    print(f"  date range: {df['date'].min()} → {df['date'].max()}")
    print(f"  spike days (high/open>=1.30): {df['is_spike'].sum()} ({df['is_spike'].mean():.1%})")

    print("\n" + "=" * 78)
    print("ALL flat-gap days (full universe — no selection bias)")
    print("=" * 78)
    print(f"\n{'cost':<8} {'win%':>7} {'avg':>8} {'sum':>10} {'compounded':>14} {'sharpe':>8}")
    for cost in [0.00, 0.01, 0.02, 0.03, 0.05]:
        net = df["ret"] - cost
        wr = (net > 0).mean()
        avg = net.mean()
        s = net.sum()
        comp = (1 + net).prod()
        sharpe_ann = (avg / net.std()) * np.sqrt(252) if net.std() > 0 else 0
        print(f"{cost:>5.0%}    {wr:>6.1%} {avg:>+7.3%} {s:>+9.2f} {comp:>14.2e} {sharpe_ann:>+8.2f}")

    print("\n" + "=" * 78)
    print("Stratification: SPIKE days vs NON-SPIKE days (within flat-gap subset)")
    print("=" * 78)
    print(f"\n{'subset':<25} {'N':>6} {'win%':>7} {'avg':>8} {'net@3%':>8}")
    for label, sub in [
        ("Spike days (h/o≥1.30)", df[df["is_spike"] == 1]),
        ("Non-spike (h/o<1.30)", df[df["is_spike"] == 0]),
    ]:
        if len(sub) == 0:
            continue
        wr = (sub["ret"] > 0).mean()
        avg = sub["ret"].mean()
        print(f"{label:<25} {len(sub):>6} {wr:>6.1%} {avg:>+7.2%} {avg-0.03:>+7.2%}")

    print("\n" + "=" * 78)
    print("INTERPRETATION")
    print("=" * 78)
    full_alpha = df["ret"].mean() - 0.03
    nonspike_alpha = df[df["is_spike"] == 0]["ret"].mean() - 0.03
    print(f"\nFull universe alpha (after 3% cost): {full_alpha:+.2%}")
    print(f"Non-spike alpha (after 3% cost):     {nonspike_alpha:+.2%}")
    print(f"\nIf non-spike alpha is significantly negative, the +3.81% finding was selection bias.")
    print(f"If non-spike alpha is positive, signal is partially real.")

    df.to_csv("gap_universe_full.csv", index=False)
    print(f"\nSaved gap_universe_full.csv ({len(df)} rows)")


if __name__ == "__main__":
    main()
