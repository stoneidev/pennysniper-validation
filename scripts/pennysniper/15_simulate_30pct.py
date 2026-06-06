"""
Step 15: Simulate "+30% quick-trigger" strategy.

Hypothesis: enter when stock reaches +30% from RTH open WITHIN N minutes
            (= strong/fast momentum, not slow drift).
            Exit on +10% TP / -5% SL.

Combined dataset:
  - 100 +100% events (already have minute data)
  - ~100 new +30%-but-<+100% events (just fetched)

For each event, walk minute bars:
  1. Find first bar where high/RTH_open >= 1.30
  2. Check if that bar's index <= MAX_TRIGGER_MINUTES (filter for "fast")
  3. If yes: entry = RTH_open * 1.30, then walk for TP/SL
  4. Pessimistic SL-first if same bar reaches both

Compare vs +100% strategy.
"""
import json
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt

CACHE_DIR = Path("polygon_minute_cache")

ENTRY_MULT = 1.30  # +30%
TP_MULT = 1.10
SL_MULT = 0.95
MAX_TRIGGER_MIN = 30  # must reach +30% within first 30 min of RTH


def load_bars(symbol: str, date: str) -> pd.DataFrame | None:
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


def simulate(bars: pd.DataFrame) -> dict:
    if bars is None or len(bars) < 2:
        return {"status": "no_data"}
    rth_open = float(bars["open"].iloc[0])
    if rth_open <= 0:
        return {"status": "bad_open"}
    entry_target = rth_open * ENTRY_MULT

    entry_idx = None
    for i, row in enumerate(bars.itertuples(index=False)):
        if row.high >= entry_target:
            entry_idx = i
            break
    if entry_idx is None:
        return {"status": "no_entry", "rth_open": rth_open}

    # Filter: must trigger within first MAX_TRIGGER_MIN minutes
    if entry_idx > MAX_TRIGGER_MIN:
        return {
            "status": "slow_trigger",
            "rth_open": rth_open,
            "trigger_minute": entry_idx,
        }
    # Skip if first bar gapped above entry (not really "+30% intraday move", it's a gap)
    if entry_idx == 0 and bars["low"].iloc[0] >= entry_target:
        return {"status": "gap_open", "rth_open": rth_open}

    entry = entry_target
    tp = entry * TP_MULT
    sl = entry * SL_MULT
    entry_time = bars["timestamp"].iloc[entry_idx]

    for j in range(entry_idx, len(bars)):
        bar = bars.iloc[j]
        if j == entry_idx:
            # Same bar: pessimistic SL-first
            if bar.low <= sl:
                return _r("sl", entry_time, bar.timestamp, entry, sl, j - entry_idx, entry_idx)
            if bar.high >= tp:
                return _r("tp", entry_time, bar.timestamp, entry, tp, j - entry_idx, entry_idx)
        else:
            if bar.open <= sl:
                return _r("sl_gap", entry_time, bar.timestamp, entry, bar.open, j - entry_idx, entry_idx)
            if bar.open >= tp:
                return _r("tp_gap", entry_time, bar.timestamp, entry, bar.open, j - entry_idx, entry_idx)
            if bar.low <= sl and bar.high >= tp:
                return _r("sl", entry_time, bar.timestamp, entry, sl, j - entry_idx, entry_idx)
            if bar.low <= sl:
                return _r("sl", entry_time, bar.timestamp, entry, sl, j - entry_idx, entry_idx)
            if bar.high >= tp:
                return _r("tp", entry_time, bar.timestamp, entry, tp, j - entry_idx, entry_idx)

    last = bars.iloc[-1]
    return _r("eod", entry_time, last.timestamp, entry, float(last.close), len(bars) - 1 - entry_idx, entry_idx)


def _r(reason, et, xt, ep, xp, held, trig):
    return {
        "status": "ok",
        "exit_reason": reason,
        "entry_time": str(et),
        "exit_time": str(xt),
        "entry_price": ep,
        "exit_price": xp,
        "minute_return": xp / ep - 1.0,
        "bars_held": held,
        "trigger_minute": trig,
    }


def main() -> None:
    # Build event list from minute cache directly
    cache_files = sorted(CACHE_DIR.glob("*.json"))
    print(f"Total cached minute files: {len(cache_files)}")

    rows = []
    for f in cache_files:
        # filename: SYMBOL_YYYY-MM-DD.json
        stem = f.stem
        # symbol may contain underscore? our universe doesn't have any with _, so split once from right
        if "_" not in stem:
            continue
        sym, date = stem.rsplit("_", 1)
        bars = load_bars(sym, date)
        sim = simulate(bars)
        sim["symbol"] = sym
        sim["date"] = date
        rows.append(sim)

    df = pd.DataFrame(rows)
    print(f"\nStatus breakdown:")
    print(df["status"].value_counts().to_string())

    ok = df[df["status"] == "ok"].copy()
    print(f"\n=== +30% within {MAX_TRIGGER_MIN}min — N={len(ok)} ===")
    print(f"Exit reason:")
    print(ok["exit_reason"].value_counts().to_string())

    print(f"\nWin rate: {(ok['minute_return']>0).mean():.1%}")
    print(f"Mean return (gross):   {ok['minute_return'].mean():.2%}")
    print(f"Median return:         {ok['minute_return'].median():.2%}")
    print(f"Median bars held:      {ok['bars_held'].median():.0f} min")
    print(f"Median trigger minute: {ok['trigger_minute'].median():.0f} (within first 30)")

    print(f"\n{'cost':<8} {'win%':>7} {'avg':>8} {'sum':>9}")
    for cost in [0.00, 0.02, 0.03, 0.05]:
        net = ok["minute_return"] - cost
        print(f"{cost:>5.0%}    {(net>0).mean():>6.1%} {net.mean():>+7.2%} {net.sum():>+8.2f}")

    ok.to_csv("trades_30pct.csv", index=False)

    # Plot
    if len(ok) > 0:
        fig, axes = plt.subplots(1, 2, figsize=(14, 5))
        axes[0].hist(ok["minute_return"] * 100, bins=30, edgecolor="black", color="steelblue")
        axes[0].axvline(ok["minute_return"].mean() * 100, color="red", linestyle="--",
                        label=f"mean = {ok['minute_return'].mean():.2%}")
        axes[0].axvline(0, color="black", linewidth=0.5)
        axes[0].set_title(f"+30% within {MAX_TRIGGER_MIN}min — return distribution (N={len(ok)})")
        axes[0].set_xlabel("Return %")
        axes[0].legend()
        axes[0].grid(alpha=0.3)

        sorted_ok = ok.sort_values("date").reset_index(drop=True)
        sorted_ok["date_dt"] = pd.to_datetime(sorted_ok["date"])
        for cost, label in [(0.0, "0%"), (0.03, "3%"), (0.05, "5%")]:
            net = sorted_ok["minute_return"] - cost
            axes[1].plot(sorted_ok["date_dt"], net.cumsum(),
                         label=f"{label} cost: final={net.cumsum().iloc[-1]:.2f}")
        axes[1].axhline(0, color="black", linewidth=0.5)
        axes[1].set_title(f"+30% within {MAX_TRIGGER_MIN}min — cumulative P&L")
        axes[1].set_xlabel("Date")
        axes[1].legend()
        axes[1].grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig("strategy_30pct.png", dpi=120)
        plt.close(fig)
        print(f"\nSaved strategy_30pct.png")

    # Compare across trigger speeds
    print(f"\n=== Sensitivity: trigger speed cutoff ===")
    for cutoff in [5, 10, 15, 20, 30, 60, 120, 390]:
        # Re-simulate with different cutoffs (just filter the existing trigger_minute results)
        # We need to re-include "slow_trigger" cases for higher cutoffs.
        # Instead, re-parse using a more general approach:
        sub_rows = []
        for f in cache_files:
            stem = f.stem
            if "_" not in stem:
                continue
            sym, date = stem.rsplit("_", 1)
            bars = load_bars(sym, date)
            if bars is None or len(bars) < 2:
                continue
            rth_open = float(bars["open"].iloc[0])
            if rth_open <= 0:
                continue
            entry_target = rth_open * ENTRY_MULT
            entry_idx = None
            for i, row in enumerate(bars.itertuples(index=False)):
                if row.high >= entry_target:
                    entry_idx = i
                    break
            if entry_idx is None or entry_idx > cutoff:
                continue
            if entry_idx == 0 and bars["low"].iloc[0] >= entry_target:
                continue
            # quick simulation
            entry = entry_target
            tp = entry * TP_MULT
            sl = entry * SL_MULT
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
            sub_rows.append(ret)
        if sub_rows:
            arr = np.array(sub_rows)
            print(f"  cutoff <= {cutoff:>3} min: N={len(arr):>3}  win={np.mean(arr>0):.1%}  "
                  f"avg={arr.mean():+.2%}  net@3%={arr.mean()-0.03:+.2%}")


if __name__ == "__main__":
    main()
