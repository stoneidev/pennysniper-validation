"""
Step 9: Extract pre-entry features from cached Polygon minute bars.

Critical constraint: only use information available BEFORE the entry bar.
No look-ahead bias allowed. Entry bar = first bar where high >= 2 * RTH_open.
We use bars from RTH_open up to (but NOT including) entry bar.
"""
import json
from pathlib import Path
import pandas as pd
import numpy as np

CACHE_DIR = Path("polygon_minute_cache")
EVENTS_CSV = "chasing_trades_minute_clean.csv"
OUT_CSV = "events_with_features.csv"

ENTRY_MULTIPLE = 2.0


def load_minute_bars(symbol: str, date: str) -> pd.DataFrame | None:
    f = CACHE_DIR / f"{symbol}_{date}.json"
    if not f.exists():
        return None
    with open(f) as fp:
        data = json.load(fp)
    if not data.get("results"):
        return None
    df = pd.DataFrame(data["results"])
    df["timestamp"] = pd.to_datetime(df["t"], unit="ms", utc=True).dt.tz_convert("America/New_York")
    df = df.rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
    df = df[["timestamp", "open", "high", "low", "close", "volume"]].sort_values("timestamp").reset_index(drop=True)
    rth = df[
        (df["timestamp"].dt.time >= pd.Timestamp("09:30").time())
        & (df["timestamp"].dt.time < pd.Timestamp("16:00").time())
    ].reset_index(drop=True)
    return rth if len(rth) > 0 else None


def extract_features(symbol: str, date: str) -> dict | None:
    bars = load_minute_bars(symbol, date)
    if bars is None or len(bars) < 2:
        return None

    rth_open = float(bars["open"].iloc[0])
    if rth_open <= 0:
        return None
    entry_target = rth_open * ENTRY_MULTIPLE

    # Find entry bar
    entry_idx = None
    for i, row in enumerate(bars.itertuples(index=False)):
        if row.high >= entry_target:
            entry_idx = i
            break
    if entry_idx is None or entry_idx == 0:
        # entry_idx == 0 means the very first RTH bar already gapped to +100% — no pre-entry data
        return None

    pre = bars.iloc[:entry_idx].copy()  # bars STRICTLY before entry bar

    # === Feature engineering ===
    feat = {}

    # Time to trigger (minutes from RTH open)
    feat["minutes_to_trigger"] = entry_idx

    # Total volume / dollar volume before entry
    feat["pre_volume"] = float(pre["volume"].sum())
    feat["pre_dollar_volume"] = float((pre["close"] * pre["volume"]).sum())

    # Volume in last 5 minutes before entry (acceleration)
    last5 = pre.tail(5)
    feat["vol_last5"] = float(last5["volume"].sum())
    feat["dvol_last5"] = float((last5["close"] * last5["volume"]).sum())

    # Volume ratio: last 5 / earlier
    earlier = pre.iloc[:-5] if len(pre) > 5 else pd.DataFrame()
    if len(earlier):
        early_avg = float(earlier["volume"].mean()) if len(earlier) else 0
        feat["vol_acceleration"] = (
            float(last5["volume"].mean()) / early_avg if early_avg > 0 else np.nan
        )
    else:
        feat["vol_acceleration"] = np.nan

    # Number of bars (sparseness measure)
    feat["pre_bars_count"] = len(pre)

    # Red vs green candles (1 = red, 0 = green)
    pre["is_red"] = (pre["close"] < pre["open"]).astype(int)
    feat["red_ratio"] = float(pre["is_red"].mean())

    # Maximum pullback during the run-up (largest drawdown from running high)
    running_high = pre["high"].cummax()
    drawdown = (pre["low"] - running_high) / running_high
    feat["max_pullback_pct"] = float(drawdown.min())  # negative number

    # Smoothness: std of returns
    rets = pre["close"].pct_change().dropna()
    feat["return_std"] = float(rets.std()) if len(rets) > 1 else np.nan

    # Acceleration: ratio of last-5-min return to earlier return
    if len(pre) >= 10:
        last5_ret = pre["close"].iloc[-1] / pre["close"].iloc[-5] - 1.0
        early_ret = pre["close"].iloc[-5] / pre["close"].iloc[0] - 1.0
        feat["return_last5"] = float(last5_ret)
        feat["return_earlier"] = float(early_ret)
        feat["acceleration"] = float(last5_ret - early_ret)
    else:
        feat["return_last5"] = float(pre["close"].iloc[-1] / pre["close"].iloc[0] - 1.0)
        feat["return_earlier"] = np.nan
        feat["acceleration"] = np.nan

    # Gap from RTH open: how far above open was the very first bar's close?
    # (proxy for pre-market strength carrying in)
    feat["first_bar_close_vs_open"] = float(pre["close"].iloc[0] / rth_open - 1.0)

    # VWAP deviation at entry trigger
    typical = (pre["high"] + pre["low"] + pre["close"]) / 3
    vwap = (typical * pre["volume"]).sum() / max(pre["volume"].sum(), 1e-9)
    feat["vwap"] = float(vwap)
    feat["price_above_vwap_pct"] = float(pre["close"].iloc[-1] / vwap - 1.0)

    # Where in pre window is the running high relative to entry trigger?
    # = how recent is the max high before entry
    bars_since_high = len(pre) - 1 - int(pre["high"].idxmax())
    feat["bars_since_high"] = bars_since_high

    # RTH open price level (penny stock micro-structure varies a lot)
    feat["rth_open_price"] = rth_open

    # Highest high before entry, scaled by RTH open
    feat["pre_high_x_open"] = float(pre["high"].max() / rth_open)

    return feat


def main() -> None:
    events = pd.read_csv(EVENTS_CSV)
    print(f"Extracting features for {len(events)} events...")

    rows = []
    for _, ev in events.iterrows():
        f = extract_features(ev["symbol"], ev["date"])
        if f is None:
            continue
        f["symbol"] = ev["symbol"]
        f["date"] = ev["date"]
        f["minute_return"] = ev["minute_return"]
        f["exit_reason"] = ev["exit_reason"]
        f["is_winner"] = int(ev["minute_return"] > 0)
        rows.append(f)

    df = pd.DataFrame(rows)
    df.to_csv(OUT_CSV, index=False)
    print(f"Saved {len(df)} rows with features to {OUT_CSV}")
    print(f"  winners (TP): {df['is_winner'].sum()}")
    print(f"  losers (SL):  {(df['is_winner']==0).sum()}")
    print(f"  baseline win rate: {df['is_winner'].mean():.1%}")
    print(f"\nFeatures extracted:")
    for c in df.columns:
        if c not in ("symbol", "date", "minute_return", "exit_reason", "is_winner"):
            n_nan = df[c].isna().sum()
            print(f"  {c}: {n_nan} NaN")


if __name__ == "__main__":
    main()
