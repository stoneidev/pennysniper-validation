"""
Step 19: Gap trading — does opening gap predict intraday outcome?

For each cached minute event:
  1. Get prior trading day's close from daily cache.
  2. Compute gap = (today_RTH_open / prev_close) - 1.
  3. Bucket events by gap size.
  4. Test simple strategies:
     A. Buy at open if gapped DOWN, exit at +5% TP / -3% SL  (gap-down reversal)
     B. Buy at open if gapped UP, exit at +5% TP / -3% SL    (gap-up momentum)
     C. Sell short at open if gapped UP, cover at close      (gap fade)
"""
import json
from pathlib import Path
import pandas as pd
import numpy as np

CACHE_DIR = Path("polygon_minute_cache")
DAILY_CACHE = Path("price_cache")


def load_minute(symbol, date):
    f = CACHE_DIR / f"{symbol}_{date}.json"
    if not f.exists():
        return None
    with open(f) as fp:
        d = json.load(fp)
    if not d.get("results"):
        return None
    df = pd.DataFrame(d["results"])
    df["timestamp"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert("America/New_York")
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df.sort_values("timestamp").reset_index(drop=True)
    rth = df[
        (df["timestamp"].dt.time >= pd.Timestamp("09:30").time())
        & (df["timestamp"].dt.time < pd.Timestamp("16:00").time())
    ].reset_index(drop=True)
    return rth if len(rth) > 0 else None


def get_prev_close(symbol, date):
    """Get prior trading day close from daily cache."""
    f = DAILY_CACHE / f"{symbol}.csv"
    if not f.exists():
        return None
    try:
        df = pd.read_csv(f, index_col=0, parse_dates=True)
    except Exception:
        return None
    if "Close" not in df.columns:
        return None
    target_date = pd.Timestamp(date)
    earlier = df[df.index < target_date]
    if len(earlier) == 0:
        return None
    return float(earlier["Close"].iloc[-1])


def main():
    files = sorted(CACHE_DIR.glob("*.json"))
    rows = []
    for f in files:
        stem = f.stem
        if "_" not in stem:
            continue
        sym, date = stem.rsplit("_", 1)
        bars = load_minute(sym, date)
        if bars is None or len(bars) < 10:
            continue
        rth_open = float(bars["open"].iloc[0])
        rth_close = float(bars["close"].iloc[-1])
        rth_high = float(bars["high"].max())
        rth_low = float(bars["low"].min())
        if rth_open <= 0:
            continue
        prev_close = get_prev_close(sym, date)
        if prev_close is None or prev_close <= 0:
            continue
        gap = rth_open / prev_close - 1.0

        # Strategy A/B: long at open, +5% TP, -3% SL
        entry = rth_open
        tp = entry * 1.05
        sl = entry * 0.97
        long_ret = None
        for j in range(len(bars)):
            bar = bars.iloc[j]
            if j == 0:
                if bar.low <= sl: long_ret = -0.03; break
                if bar.high >= tp: long_ret = 0.05; break
            else:
                if bar.open <= sl: long_ret = bar.open / entry - 1.0; break
                if bar.open >= tp: long_ret = bar.open / entry - 1.0; break
                if bar.low <= sl and bar.high >= tp: long_ret = -0.03; break
                if bar.low <= sl: long_ret = -0.03; break
                if bar.high >= tp: long_ret = 0.05; break
        if long_ret is None:
            long_ret = rth_close / entry - 1.0

        # Strategy C: short at open, cover at close
        short_ret_eod = (rth_open - rth_close) / rth_open

        # Strategy D: short at open, cover at +5% TP (entry*0.95) / -3% SL (entry*1.03)
        tp_short = entry * 0.95
        sl_short = entry * 1.03
        short_ret = None
        for j in range(len(bars)):
            bar = bars.iloc[j]
            if j == 0:
                if bar.high >= sl_short: short_ret = -0.03; break
                if bar.low <= tp_short: short_ret = 0.05; break
            else:
                if bar.open >= sl_short: short_ret = -(bar.open / entry - 1.0); break
                if bar.open <= tp_short: short_ret = -(bar.open / entry - 1.0); break
                if bar.high >= sl_short and bar.low <= tp_short: short_ret = -0.03; break
                if bar.high >= sl_short: short_ret = -0.03; break
                if bar.low <= tp_short: short_ret = 0.05; break
        if short_ret is None:
            short_ret = -(rth_close / entry - 1.0)

        rows.append({
            "symbol": sym,
            "date": date,
            "prev_close": prev_close,
            "rth_open": rth_open,
            "gap_pct": gap,
            "long_ret": long_ret,
            "short_ret": short_ret,
            "short_eod": short_ret_eod,
            "rth_close": rth_close,
            "intraday_high_x_open": rth_high / rth_open,
        })

    df = pd.DataFrame(rows)
    print(f"N = {len(df)}")
    print(f"Median gap: {df['gap_pct'].median():+.1%}")
    print(f"Gap up >= +20%:  {(df['gap_pct'] >= 0.20).sum()}")
    print(f"Gap up +5%~+20%: {((df['gap_pct'] >= 0.05) & (df['gap_pct'] < 0.20)).sum()}")
    print(f"Flat -5%~+5%:    {((df['gap_pct'] >= -0.05) & (df['gap_pct'] < 0.05)).sum()}")
    print(f"Gap down >5%:    {(df['gap_pct'] < -0.05).sum()}")

    print("\n" + "=" * 78)
    print("Strategy A: Long at open, +5% TP / -3% SL — by gap bucket")
    print("=" * 78)
    BUCKETS = [
        ("Gap down (<-5%)", -1.0, -0.05),
        ("Flat (-5%~+5%)", -0.05, 0.05),
        ("Mild gap up (+5%~+20%)", 0.05, 0.20),
        ("Big gap up (+20%~+50%)", 0.20, 0.50),
        ("Huge gap up (>=+50%)", 0.50, 100.0),
    ]
    print(f"\n{'bucket':<26} {'N':>5} {'win%':>6} {'avg':>8} {'net@3%':>8} {'sum':>7}")
    for label, lo, hi in BUCKETS:
        sub = df[(df["gap_pct"] >= lo) & (df["gap_pct"] < hi)]
        if len(sub) == 0:
            print(f"{label:<26} {0:>5}")
            continue
        wr = (sub["long_ret"] > 0).mean()
        avg = sub["long_ret"].mean()
        print(f"{label:<26} {len(sub):>5} {wr:>5.0%} {avg:>+7.2%} {avg-0.03:>+7.2%} {sub['long_ret'].sum():>+6.2f}")

    print("\n" + "=" * 78)
    print("Strategy C: Short at open, cover at close — by gap bucket")
    print("(Gap-up fade hypothesis)")
    print("=" * 78)
    print(f"\n{'bucket':<26} {'N':>5} {'win%':>6} {'avg':>8} {'net@5%':>8} {'sum':>7}")
    for label, lo, hi in BUCKETS:
        sub = df[(df["gap_pct"] >= lo) & (df["gap_pct"] < hi)]
        if len(sub) == 0:
            print(f"{label:<26} {0:>5}")
            continue
        wr = (sub["short_eod"] > 0).mean()
        avg = sub["short_eod"].mean()
        print(f"{label:<26} {len(sub):>5} {wr:>5.0%} {avg:>+7.2%} {avg-0.05:>+7.2%} {sub['short_eod'].sum():>+6.2f}")

    print("\n" + "=" * 78)
    print("Strategy D: Short at open, cover +5% TP / -3% SL — by gap bucket")
    print("=" * 78)
    print(f"\n{'bucket':<26} {'N':>5} {'win%':>6} {'avg':>8} {'net@5%':>8} {'sum':>7}")
    for label, lo, hi in BUCKETS:
        sub = df[(df["gap_pct"] >= lo) & (df["gap_pct"] < hi)]
        if len(sub) == 0:
            print(f"{label:<26} {0:>5}")
            continue
        wr = (sub["short_ret"] > 0).mean()
        avg = sub["short_ret"].mean()
        print(f"{label:<26} {len(sub):>5} {wr:>5.0%} {avg:>+7.2%} {avg-0.05:>+7.2%} {sub['short_ret'].sum():>+6.2f}")

    df.to_csv("gap_trading_results.csv", index=False)


if __name__ == "__main__":
    main()
