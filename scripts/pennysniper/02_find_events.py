"""
Step 2: Find volume-surge events on penny stock universe.

For each ticker, pull ~2 years of daily OHLCV and flag days where:
  - Volume >= VOLUME_MULTIPLIER * 20-day average volume
  - Intraday return (close/open - 1) >= MIN_INTRADAY_GAIN
  - Price still in penny range that day

These are "scanner trigger" events — what an automated penny-stock scanner
would have flagged in real-time. We will then test whether buying NEXT-DAY
open and exiting on +TP or -SL produces profit.

Saves events.csv with one row per (ticker, date) trigger.
"""
import time
import pandas as pd
import yfinance as yf

UNIVERSE_CSV = "universe.csv"
OUT_CSV = "events.csv"

LOOKBACK_PERIOD = "2y"
VOLUME_MULTIPLIER = 5.0  # today's volume vs 20-day avg
MIN_INTRADAY_GAIN = 0.20  # +20% close/open
PRICE_MIN = 1.0
PRICE_MAX = 10.0


def find_events_for_ticker(symbol: str) -> list[dict]:
    try:
        df = yf.download(
            tickers=symbol,
            period=LOOKBACK_PERIOD,
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception:
        return []
    if df is None or len(df) < 25:
        return []
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=["Open", "Close", "Volume"])
    if len(df) < 25:
        return []

    df["vol_avg20"] = df["Volume"].rolling(20).mean()
    df["intraday_ret"] = df["Close"] / df["Open"] - 1.0
    df["vol_ratio"] = df["Volume"] / df["vol_avg20"]

    mask = (
        (df["vol_ratio"] >= VOLUME_MULTIPLIER)
        & (df["intraday_ret"] >= MIN_INTRADAY_GAIN)
        & (df["Close"].between(PRICE_MIN, PRICE_MAX))
    )
    triggers = df[mask]
    events = []
    for ts, row in triggers.iterrows():
        events.append(
            {
                "symbol": symbol,
                "trigger_date": ts.strftime("%Y-%m-%d"),
                "trigger_close": float(row["Close"]),
                "trigger_intraday_ret": float(row["intraday_ret"]),
                "trigger_vol_ratio": float(row["vol_ratio"]),
            }
        )
    return events


def main() -> None:
    universe = pd.read_csv(UNIVERSE_CSV)
    symbols = universe["symbol"].tolist()
    print(f"Scanning {len(symbols)} tickers for volume-surge events...")
    all_events: list[dict] = []
    for i, sym in enumerate(symbols, 1):
        evts = find_events_for_ticker(sym)
        if evts:
            all_events.extend(evts)
        if i % 50 == 0:
            print(f"  {i}/{len(symbols)} processed, {len(all_events)} events so far")
        time.sleep(0.05)
    df = pd.DataFrame(all_events)
    df.to_csv(OUT_CSV, index=False)
    print(f"\nSaved {len(df)} events to {OUT_CSV}")
    if len(df):
        print(f"  unique tickers: {df['symbol'].nunique()}")
        print(f"  date range: {df['trigger_date'].min()} to {df['trigger_date'].max()}")
        print(f"  median intraday gain on trigger day: {df['trigger_intraday_ret'].median():.1%}")
        print(f"  median volume ratio on trigger day: {df['trigger_vol_ratio'].median():.1f}x")


if __name__ == "__main__":
    main()
