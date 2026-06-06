"""
Step 18: Multi-hypothesis test on existing 214 minute-bar files.

Hypotheses tested:
  H1. Time-of-day seasonality
  H2. Volume cluster (does volume timing predict outcome?)
  H3. Short strategy at +100% (reverse of long)
  H4. Pump-and-fade pattern (anticipate fade after spike)

Selection bias warning: our 214 events are ALL "spike days" (high/open >= 1.30).
This biases time-of-day analysis. We control by:
  - Reporting baseline (always-trade) per bucket
  - Reporting clean subset (no +100% peek-ahead) where applicable
"""
import json
from pathlib import Path
import pandas as pd
import numpy as np

CACHE_DIR = Path("polygon_minute_cache")


def load_bars(symbol, date):
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
    df = df[["timestamp", "open", "high", "low", "close", "volume"]].sort_values("timestamp").reset_index(drop=True)
    rth = df[
        (df["timestamp"].dt.time >= pd.Timestamp("09:30").time())
        & (df["timestamp"].dt.time < pd.Timestamp("16:00").time())
    ].reset_index(drop=True)
    return rth if len(rth) > 0 else None


def collect_all_events():
    files = sorted(CACHE_DIR.glob("*.json"))
    events = []
    for f in files:
        stem = f.stem
        if "_" not in stem:
            continue
        sym, date = stem.rsplit("_", 1)
        bars = load_bars(sym, date)
        if bars is None or len(bars) < 10:
            continue
        events.append({"symbol": sym, "date": date, "bars": bars})
    return events


# =====================================================================
# H1: Time-of-day seasonality
# =====================================================================
def time_of_day_analysis(events):
    print("=" * 78)
    print("H1: Time-of-day seasonality")
    print("=" * 78)
    print("\nTrigger: +30% from current bar's running RTH open")
    print("Bucket = the minute when trigger fires (or 'no trigger')\n")

    BUCKETS = [
        ("09:30-09:35 (open spike)", 0, 5),
        ("09:35-10:00 (early morning)", 5, 30),
        ("10:00-11:30 (morning)", 30, 120),
        ("11:30-13:30 (lunch)", 120, 240),
        ("13:30-15:00 (afternoon)", 240, 330),
        ("15:00-15:30 (pre-close)", 330, 360),
        ("15:30-16:00 (last 30min)", 360, 390),
    ]

    # For each event, find first +30% trigger bar index
    rows = []
    for ev in events:
        bars = ev["bars"]
        rth_open = float(bars["open"].iloc[0])
        if rth_open <= 0:
            continue
        target = rth_open * 1.30
        trig_idx = None
        for i, r in enumerate(bars.itertuples(index=False)):
            if r.high >= target:
                trig_idx = i
                break
        if trig_idx is None:
            continue
        if trig_idx == 0 and bars["low"].iloc[0] >= target:
            continue

        # Simulate +10% TP / -5% SL from trigger
        entry = target
        tp = entry * 1.10
        sl = entry * 0.95
        ret = None
        for j in range(trig_idx, len(bars)):
            bar = bars.iloc[j]
            if j == trig_idx:
                if bar.low <= sl: ret = -0.05; break
                if bar.high >= tp: ret = 0.10; break
            else:
                if bar.open <= sl: ret = bar.open / entry - 1.0; break
                if bar.open >= tp: ret = bar.open / entry - 1.0; break
                if bar.low <= sl and bar.high >= tp: ret = -0.05; break
                if bar.low <= sl: ret = -0.05; break
                if bar.high >= tp: ret = 0.10; break
        if ret is None:
            ret = float(bars["close"].iloc[-1]) / entry - 1.0
        # Reached +100% on day?
        reached_100 = float(bars["high"].max()) / rth_open >= 2.0
        rows.append({
            "trigger_min": trig_idx,
            "ret": ret,
            "clean": not reached_100,
        })

    df = pd.DataFrame(rows)
    print(f"{'bucket':<32} {'N_all':>5} {'win%':>6} {'avg':>8} | {'N_clean':>7} {'win%':>6} {'avg':>8}")
    for label, lo, hi in BUCKETS:
        sub = df[(df["trigger_min"] >= lo) & (df["trigger_min"] < hi)]
        sc = sub[sub["clean"]]
        if len(sub) == 0:
            print(f"{label:<32} {0:>5}")
            continue
        line = (
            f"{label:<32} {len(sub):>5} "
            f"{(sub['ret']>0).mean():>5.0%} {sub['ret'].mean():>+7.2%}"
        )
        if len(sc) > 0:
            line += f" | {len(sc):>7} {(sc['ret']>0).mean():>5.0%} {sc['ret'].mean():>+7.2%}"
        else:
            line += f" | {0:>7}"
        print(line)
    print()


# =====================================================================
# H2: Volume cluster predictivity
# =====================================================================
def volume_cluster_analysis(events):
    print("=" * 78)
    print("H2: Volume cluster — does pre-trigger volume profile predict outcome?")
    print("=" * 78)
    print("\nFor each +30% trigger event, examine volume in 5-min window before trigger.")
    print("Quintile by 'volume burst intensity' = trigger_bar_volume / pre_avg_volume\n")

    rows = []
    for ev in events:
        bars = ev["bars"]
        rth_open = float(bars["open"].iloc[0])
        if rth_open <= 0:
            continue
        target = rth_open * 1.30
        trig_idx = None
        for i, r in enumerate(bars.itertuples(index=False)):
            if r.high >= target:
                trig_idx = i
                break
        if trig_idx is None or trig_idx < 5:
            continue
        if trig_idx == 0 and bars["low"].iloc[0] >= target:
            continue

        # volume profile: trigger bar volume vs prior bars
        pre = bars.iloc[:trig_idx]
        trig_vol = float(bars["volume"].iloc[trig_idx])
        pre_avg = float(pre["volume"].mean()) if len(pre) > 0 else 0
        burst_ratio = trig_vol / pre_avg if pre_avg > 0 else np.nan

        # Simulate +10/-5
        entry = target
        tp = entry * 1.10
        sl = entry * 0.95
        ret = None
        for j in range(trig_idx, len(bars)):
            bar = bars.iloc[j]
            if j == trig_idx:
                if bar.low <= sl: ret = -0.05; break
                if bar.high >= tp: ret = 0.10; break
            else:
                if bar.open <= sl: ret = bar.open / entry - 1.0; break
                if bar.open >= tp: ret = bar.open / entry - 1.0; break
                if bar.low <= sl and bar.high >= tp: ret = -0.05; break
                if bar.low <= sl: ret = -0.05; break
                if bar.high >= tp: ret = 0.10; break
        if ret is None:
            ret = float(bars["close"].iloc[-1]) / entry - 1.0
        reached_100 = float(bars["high"].max()) / rth_open >= 2.0
        rows.append({"burst_ratio": burst_ratio, "ret": ret, "clean": not reached_100})

    df = pd.DataFrame(rows).dropna()
    print(f"N = {len(df)}")
    if len(df) >= 10:
        df["q"] = pd.qcut(df["burst_ratio"], q=5, labels=False, duplicates="drop")
        print(f"\n{'quintile':<10} {'burst_range':<22} {'N_all':>5} {'win%':>6} {'avg':>8} | {'N_clean':>7} {'win%':>6} {'avg':>8}")
        for q in sorted(df["q"].dropna().unique()):
            sub = df[df["q"] == q]
            sc = sub[sub["clean"]]
            br_lo = sub["burst_ratio"].min()
            br_hi = sub["burst_ratio"].max()
            line = (
                f"Q{int(q)+1:<9} {br_lo:>5.1f}-{br_hi:<10.1f} {len(sub):>5} "
                f"{(sub['ret']>0).mean():>5.0%} {sub['ret'].mean():>+7.2%}"
            )
            if len(sc) > 0:
                line += f" | {len(sc):>7} {(sc['ret']>0).mean():>5.0%} {sc['ret'].mean():>+7.2%}"
            print(line)
    print()


# =====================================================================
# H3: Short strategy
# =====================================================================
def short_strategy_analysis(events):
    print("=" * 78)
    print("H3: Short strategy — sell when stock hits +100%, cover at -10% TP / +5% SL")
    print("=" * 78)
    print("\nBorrow fee: penny stock typical 30% annual = ~0.082%/day")
    print("Same-day cover: borrow fee negligible (~0)")
    print("Short locate availability NOT modeled (pessimistic: assume always shortable)\n")

    rows = []
    for ev in events:
        bars = ev["bars"]
        rth_open = float(bars["open"].iloc[0])
        if rth_open <= 0:
            continue
        target = rth_open * 2.0  # +100% short entry
        trig_idx = None
        for i, r in enumerate(bars.itertuples(index=False)):
            if r.high >= target:
                trig_idx = i
                break
        if trig_idx is None:
            continue
        if trig_idx == 0 and bars["low"].iloc[0] >= target:
            continue

        # Short entry at target, TP = entry * 0.90 (cover lower), SL = entry * 1.05 (cover higher)
        entry = target
        tp_cover = entry * 0.90  # take profit at -10%
        sl_cover = entry * 1.05  # stop loss at +5%
        ret = None
        for j in range(trig_idx, len(bars)):
            bar = bars.iloc[j]
            if j == trig_idx:
                # Pessimistic: assume SL hit first if both reachable
                if bar.high >= sl_cover: ret = -0.05; break
                if bar.low <= tp_cover: ret = 0.10; break
            else:
                if bar.open >= sl_cover: ret = -(bar.open / entry - 1.0); break
                if bar.open <= tp_cover: ret = -(bar.open / entry - 1.0); break
                if bar.high >= sl_cover and bar.low <= tp_cover: ret = -0.05; break
                if bar.high >= sl_cover: ret = -0.05; break
                if bar.low <= tp_cover: ret = 0.10; break
        if ret is None:
            ret = -(float(bars["close"].iloc[-1]) / entry - 1.0)
        rows.append({"ret": ret})

    df = pd.DataFrame(rows)
    print(f"N = {len(df)}")
    if len(df) > 0:
        print(f"\nWin rate:    {(df['ret']>0).mean():.1%}")
        print(f"Mean gross:  {df['ret'].mean():+.2%}")
        print(f"Median:      {df['ret'].median():+.2%}")
        print(f"\n{'cost+fee':<12} {'mean':>8} {'sum':>8}")
        # Penny stock shorts: borrow fee + spread + slippage often 5-10% round-trip
        for cost in [0.00, 0.03, 0.05, 0.10]:
            net = df["ret"] - cost
            print(f"{cost:>5.0%}        {net.mean():>+7.2%} {net.sum():>+7.2f}")
    print()


# =====================================================================
# H4: Pump-and-fade pattern
# =====================================================================
def pump_fade_analysis(events):
    print("=" * 78)
    print("H4: Pump-and-fade — among 214 spike days, how often does it fade?")
    print("=" * 78)
    print()

    rows = []
    for ev in events:
        bars = ev["bars"]
        rth_open = float(bars["open"].iloc[0])
        rth_high = float(bars["high"].max())
        rth_close = float(bars["close"].iloc[-1])
        if rth_open <= 0:
            continue
        peak_x = rth_high / rth_open
        close_x = rth_close / rth_open
        fade_ratio = (rth_high - rth_close) / (rth_high - rth_open) if rth_high > rth_open else 0
        rows.append({
            "peak_x": peak_x,
            "close_x": close_x,
            "fade_ratio": fade_ratio,  # 0=held all gains, 1=gave back all gains, >1=closed below open
        })

    df = pd.DataFrame(rows)
    print(f"N = {len(df)} spike days (high/open >= 1.30)")
    print(f"\nPeak vs close behavior:")
    print(f"  median peak/open:  {df['peak_x'].median():.2f}x  (intraday high)")
    print(f"  median close/open: {df['close_x'].median():.2f}x  (closing multiple)")
    print(f"  median fade ratio: {df['fade_ratio'].median():.2f}  (1.0 = full giveback)")
    print()
    print(f"  closed in green (close > open):           {(df['close_x']>=1.0).sum()}/{len(df)} = {(df['close_x']>=1.0).mean():.1%}")
    print(f"  closed in red despite intraday spike:     {(df['close_x']<1.0).sum()}/{len(df)} = {(df['close_x']<1.0).mean():.1%}")
    print(f"  faded >= 50% of gain (close gave back ½): {(df['fade_ratio']>=0.5).sum()}/{len(df)} = {(df['fade_ratio']>=0.5).mean():.1%}")
    print()

    print("Pattern: peak-fade trading = sell at intraday high, cover at close")
    print(f"  hypothetical mean return (gross): {(df['peak_x'] - df['close_x']).mean() / df['peak_x'].mean():+.2%}")
    print(f"  (this is OPTIMAL/oracle — picking exact peak — not realistic)")
    print()

    # Realistic pattern: sell when peak first reached AFTER stock has +50% from open
    # Cover at end of day OR on first significant pullback (-5% from peak)
    print("Realistic: short when peak crosses +50% from open, cover at close")
    rows2 = []
    for ev in events:
        bars = ev["bars"]
        rth_open = float(bars["open"].iloc[0])
        if rth_open <= 0:
            continue
        target = rth_open * 1.50
        trig_idx = None
        for i, r in enumerate(bars.itertuples(index=False)):
            if r.high >= target:
                trig_idx = i
                break
        if trig_idx is None:
            continue
        if trig_idx == 0 and bars["low"].iloc[0] >= target:
            continue
        entry = target
        # Short, hold to close
        cover = float(bars["close"].iloc[-1])
        # short return = (entry - cover) / entry
        ret = (entry - cover) / entry
        rows2.append({"ret": ret})

    df2 = pd.DataFrame(rows2)
    print(f"\nN = {len(df2)}")
    if len(df2) > 0:
        print(f"  win rate:   {(df2['ret']>0).mean():.1%}")
        print(f"  mean gross: {df2['ret'].mean():+.2%}")
        print(f"  median:     {df2['ret'].median():+.2%}")
        for cost in [0.0, 0.03, 0.05, 0.10]:
            net = df2["ret"] - cost
            print(f"  net@{cost:.0%}:   {net.mean():+.2%}")
    print()


def main():
    print("Loading minute bar data...")
    events = collect_all_events()
    print(f"Loaded {len(events)} event-days\n")

    time_of_day_analysis(events)
    volume_cluster_analysis(events)
    short_strategy_analysis(events)
    pump_fade_analysis(events)


if __name__ == "__main__":
    main()
