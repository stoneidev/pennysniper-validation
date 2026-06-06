"""
Step 5: Test "chasing +100%" strategy intraday.

Hypothesis: enter when stock has already moved +100% from open within the
day, take +10% profit or -5% stop loss before close.

Data limitation: yfinance free only gives daily OHLC. We use:
  - High/Open >= 2.0  →  proves stock touched +100% intraday
  - Entry price = Open * 2.0 (exactly +100%)
  - TP price = Entry * 1.10  →  hit if High/Open >= 2.2
  - SL price = Entry * 0.95  →  hit if Low/Open <= 1.90 AND price came back down
                                 after touching +100%

The intraday path is unknown from daily OHLC, so we run TWO scenarios:

  OPTIMISTIC: TP fires whenever (High/Open >= 2.2). SL fires only when
              we can prove the price came back down: Close/Open < 1.90
              AND no TP. (Maximum favorable interpretation.)

  PESSIMISTIC: TP fires only if Close/Open >= 2.2 (proof we held to TP
               without prior SL). SL fires if Low/Open <= 1.90 after
               High/Open >= 2.0. (Standard backtester convention:
               assume SL touched first if both reachable.)

Realistic estimate ≈ between these two.
"""
import pandas as pd
import numpy as np
import time
from pathlib import Path
import yfinance as yf

CACHE_DIR = Path("price_cache")
CACHE_DIR.mkdir(exist_ok=True)

UNIVERSE_CSV = "universe.csv"
OUT_CSV = "chasing_trades.csv"

PRICE_MIN = 1.0
PRICE_MAX = 10.0
ENTRY_THRESHOLD = 2.0   # +100% from open
TP_THRESHOLD = 2.2      # +10% from entry  (= +120% from open)
SL_THRESHOLD = 1.90     # -5% from entry  (= +90% from open)
MIN_VOLUME_USD = 500_000  # filter out illiquid prints


def get_history(symbol: str) -> pd.DataFrame | None:
    cache_path = CACHE_DIR / f"{symbol}.csv"
    if cache_path.exists():
        try:
            return pd.read_csv(cache_path, index_col=0, parse_dates=True)
        except Exception:
            pass
    try:
        df = yf.download(
            tickers=symbol,
            period="2y",
            interval="1d",
            auto_adjust=True,
            progress=False,
            threads=False,
        )
    except Exception:
        return None
    if df is None or len(df) == 0:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    df.to_csv(cache_path)
    return df


def find_chasing_trades(symbol: str) -> list[dict]:
    hist = get_history(symbol)
    if hist is None or len(hist) < 5:
        return []

    # Need: Open > 0, High/Open >= 2.0, price in penny range, has $$ volume
    o = hist["Open"]
    h = hist["High"]
    l = hist["Low"]
    c = hist["Close"]
    v = hist["Volume"]

    valid = o > 0
    high_to_open = h / o.where(valid)
    low_to_open = l / o.where(valid)
    close_to_open = c / o.where(valid)
    dollar_vol = c * v

    mask = (
        valid
        & (high_to_open >= ENTRY_THRESHOLD)
        & (o.between(PRICE_MIN, PRICE_MAX))
        & (dollar_vol >= MIN_VOLUME_USD)
    )

    trades = []
    for ts in hist.index[mask]:
        op = float(o.loc[ts])
        hp = float(h.loc[ts])
        lp = float(l.loc[ts])
        cp = float(c.loc[ts])

        entry = op * ENTRY_THRESHOLD  # = op * 2.0
        tp = entry * 1.10
        sl = entry * 0.95

        h_ratio = hp / op
        l_ratio = lp / op
        c_ratio = cp / op

        # OPTIMISTIC interpretation
        # TP hits if high reached 2.2x open. SL hits only if it can be proven
        # (no TP and close clearly below SL).
        tp_reachable = h_ratio >= 2.2
        sl_reachable_pessimistic = l_ratio <= 1.90  # low touched SL line
        sl_proven = (not tp_reachable) and (c_ratio < 1.90)

        if tp_reachable:
            opt_outcome = +0.10
            opt_reason = "tp"
        elif sl_proven:
            opt_outcome = -0.05
            opt_reason = "sl"
        else:
            # Held to close
            opt_outcome = c_ratio / 2.0 - 1.0  # close/entry - 1
            opt_reason = "close"

        # PESSIMISTIC interpretation
        # If both TP and SL reachable, assume SL hit first.
        if sl_reachable_pessimistic and tp_reachable:
            pes_outcome = -0.05
            pes_reason = "sl_first"
        elif tp_reachable:
            pes_outcome = +0.10
            pes_reason = "tp"
        elif sl_reachable_pessimistic:
            pes_outcome = -0.05
            pes_reason = "sl"
        else:
            pes_outcome = c_ratio / 2.0 - 1.0
            pes_reason = "close"

        trades.append({
            "symbol": symbol,
            "date": ts.strftime("%Y-%m-%d"),
            "open": op,
            "high": hp,
            "low": lp,
            "close": cp,
            "high_x_open": h_ratio,
            "low_x_open": l_ratio,
            "close_x_open": c_ratio,
            "entry": entry,
            "opt_return": opt_outcome,
            "opt_reason": opt_reason,
            "pes_return": pes_outcome,
            "pes_reason": pes_reason,
            "dollar_vol": float(dollar_vol.loc[ts]),
        })
    return trades


def main() -> None:
    universe = pd.read_csv(UNIVERSE_CSV)
    symbols = universe["symbol"].tolist()
    print(f"Scanning {len(symbols)} tickers for +100% intraday events...")

    all_trades = []
    for i, sym in enumerate(symbols, 1):
        try:
            trades = find_chasing_trades(sym)
        except Exception as e:
            continue
        all_trades.extend(trades)
        if i % 100 == 0:
            print(f"  {i}/{len(symbols)} processed, {len(all_trades)} +100% events found")
        time.sleep(0.02)

    df = pd.DataFrame(all_trades)
    df.to_csv(OUT_CSV, index=False)
    print(f"\nFound {len(df)} intraday +100% events")

    if len(df) == 0:
        print("No events found.")
        return

    print(f"Unique tickers: {df['symbol'].nunique()}")
    print(f"Date range: {df['date'].min()} to {df['date'].max()}")

    print("\n=== OPTIMISTIC interpretation ===")
    print("(TP hit whenever high reached threshold; SL only if proven)")
    print(df["opt_reason"].value_counts().to_string())
    for cost in [0.0, 0.02, 0.05]:
        net = df["opt_return"] - cost
        print(f"  cost={cost:.0%}: win%={(net>0).mean():.1%}, "
              f"avg={net.mean():.2%}, "
              f"sum={net.sum():.2f}, "
              f"compounded $1 → {(1+net).prod():.2e}")

    print("\n=== PESSIMISTIC interpretation ===")
    print("(SL assumed to hit before TP if both reachable)")
    print(df["pes_reason"].value_counts().to_string())
    for cost in [0.0, 0.02, 0.05]:
        net = df["pes_return"] - cost
        print(f"  cost={cost:.0%}: win%={(net>0).mean():.1%}, "
              f"avg={net.mean():.2%}, "
              f"sum={net.sum():.2f}, "
              f"compounded $1 → {(1+net).prod():.2e}")

    print("\n=== Realistic midpoint (avg of opt + pes) ===")
    df["mid_return"] = (df["opt_return"] + df["pes_return"]) / 2
    for cost in [0.0, 0.03, 0.05, 0.08]:
        net = df["mid_return"] - cost
        print(f"  cost={cost:.0%}: win%={(net>0).mean():.1%}, "
              f"avg={net.mean():.2%}, "
              f"sum={net.sum():.2f}")


if __name__ == "__main__":
    main()
