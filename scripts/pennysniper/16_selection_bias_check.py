"""
Step 16: Selection bias check on the +30% / ≤10min finding.

Question: among the 27 events that triggered +30% within 10 minutes,
how many were in the "+100% on the day" group vs the "+30% to +99% on the day" group?

If the alpha (+1.11% gross) is concentrated in the +100% group,
the "fast trigger" pattern is just a proxy for "already going to +100% today" —
which we cannot detect ex-ante.

If alpha is similar in both groups, the fast-trigger pattern has independent value.
"""
import json
from pathlib import Path
import pandas as pd
import numpy as np

CACHE_DIR = Path("polygon_minute_cache")

ENTRY_MULT = 1.30
TP_MULT = 1.10
SL_MULT = 0.95
CUTOFFS = [5, 10, 15, 20, 30]


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


def simulate_event(bars, max_trigger_min):
    if bars is None or len(bars) < 2:
        return None
    rth_open = float(bars["open"].iloc[0])
    if rth_open <= 0:
        return None
    entry_target = rth_open * ENTRY_MULT
    entry_idx = None
    for i, row in enumerate(bars.itertuples(index=False)):
        if row.high >= entry_target:
            entry_idx = i
            break
    if entry_idx is None or entry_idx > max_trigger_min:
        return None
    if entry_idx == 0 and bars["low"].iloc[0] >= entry_target:
        return None

    entry = entry_target
    tp = entry * TP_MULT
    sl = entry * SL_MULT
    rth_high = float(bars["high"].max())
    daily_max_x_open = rth_high / rth_open

    ret = None
    for j in range(entry_idx, len(bars)):
        bar = bars.iloc[j]
        if j == entry_idx:
            if bar.low <= sl:
                ret = -0.05
                break
            if bar.high >= tp:
                ret = 0.10
                break
        else:
            if bar.open <= sl:
                ret = bar.open / entry - 1.0
                break
            if bar.open >= tp:
                ret = bar.open / entry - 1.0
                break
            if bar.low <= sl and bar.high >= tp:
                ret = -0.05
                break
            if bar.low <= sl:
                ret = -0.05
                break
            if bar.high >= tp:
                ret = 0.10
                break
    if ret is None:
        ret = float(bars["close"].iloc[-1]) / entry - 1.0

    return {
        "trigger_min": entry_idx,
        "minute_return": ret,
        "daily_max_x_open": daily_max_x_open,
        "is_winner": int(ret > 0),
        "reached_100pct": int(daily_max_x_open >= 2.0),
    }


def main():
    files = sorted(CACHE_DIR.glob("*.json"))
    rows = []
    for f in files:
        stem = f.stem
        if "_" not in stem:
            continue
        sym, date = stem.rsplit("_", 1)
        bars = load_bars(sym, date)
        sim = simulate_event(bars, max_trigger_min=120)  # collect all up to 2hr
        if sim is None:
            continue
        sim["symbol"] = sym
        sim["date"] = date
        rows.append(sim)

    df = pd.DataFrame(rows)
    print(f"Total triggered (≤120 min cutoff): {len(df)}")
    print(f"Of which reached +100% on day:     {df['reached_100pct'].sum()}")
    print(f"Of which capped between +30%~+99%: {(df['reached_100pct']==0).sum()}\n")

    print("=" * 78)
    print("Stratified analysis: alpha by trigger speed AND by 'reached +100%' group")
    print("=" * 78)
    print(f"\n{'cutoff':<8} {'group':<28} {'N':>5} {'win%':>7} {'avg':>8} {'net@3%':>8}")
    for cutoff in CUTOFFS:
        sub = df[df["trigger_min"] <= cutoff]
        for label, g in [
            ("all", sub),
            ("reached +100% (biased)", sub[sub["reached_100pct"] == 1]),
            ("only +30%~+99% (clean)", sub[sub["reached_100pct"] == 0]),
        ]:
            if len(g) == 0:
                continue
            wr = g["is_winner"].mean()
            avg = g["minute_return"].mean()
            print(f"≤{cutoff:>3}min  {label:<28} {len(g):>5} {wr:>6.1%} {avg:>+7.2%} {avg - 0.03:>+7.2%}")
        print()

    # The honest test: clean subset only (no +100% peek-ahead)
    print("=" * 78)
    print("HONEST TEST: among events that did NOT reach +100% on the day,")
    print("does fast trigger still produce alpha?")
    print("=" * 78)
    clean = df[df["reached_100pct"] == 0]
    print(f"\nN = {len(clean)} events")
    print(f"\n{'cutoff':<10} {'N':>5} {'win%':>7} {'avg':>8} {'net@3%':>8} {'net@5%':>8}")
    for cutoff in CUTOFFS:
        g = clean[clean["trigger_min"] <= cutoff]
        if len(g) < 3:
            continue
        wr = g["is_winner"].mean()
        avg = g["minute_return"].mean()
        print(f"≤{cutoff:>3}min     {len(g):>5} {wr:>6.1%} {avg:>+7.2%} {avg - 0.03:>+7.2%} {avg - 0.05:>+7.2%}")

    df.to_csv("selection_bias_check.csv", index=False)
    print(f"\nSaved selection_bias_check.csv")


if __name__ == "__main__":
    main()
