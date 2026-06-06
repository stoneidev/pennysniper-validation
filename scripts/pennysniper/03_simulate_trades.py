"""
Step 3: Simulate trades on volume-surge events.

For each event in events.csv, simulate:
  - ENTRY: next trading day's OPEN
  - EXIT (in priority): take-profit (+TP), stop-loss (-SL),
                       or end of simulation horizon (close of HOLD_DAYS later)
  - COSTS: round-trip slippage+spread+commission

Computes:
  - per-trade P&L
  - hit rate, expectancy, equity curve
  - sensitivity to assumed cost level

The HOLD_DAYS=1 case is the "buy next day open, sell same day close OR earlier
on TP/SL touch" scenario — closest proxy to PRD's intraday strategy with daily
data. We approximate intra-day TP/SL by checking next-day high/low against
entry.
"""
import pandas as pd
import yfinance as yf
import numpy as np
import time
from pathlib import Path

EVENTS_CSV = "events.csv"
OUT_TRADES = "trades.csv"

TAKE_PROFIT = 0.10   # +10%
STOP_LOSS = 0.05     # -5%
HOLD_DAYS = 1        # exit by close of N days after entry if neither TP nor SL hit

# Cost scenarios for sensitivity
COST_SCENARIOS = {
    "optimistic_1pct": 0.01,
    "realistic_3pct": 0.03,
    "pessimistic_5pct": 0.05,
}

CACHE_DIR = Path("price_cache")
CACHE_DIR.mkdir(exist_ok=True)


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


def simulate_trade(hist: pd.DataFrame, trigger_date: str) -> dict | None:
    """Simulate one trade entered on day after trigger_date."""
    idx = hist.index.searchsorted(pd.Timestamp(trigger_date))
    # Next trading day after trigger
    entry_idx = idx + 1
    if entry_idx >= len(hist):
        return None
    entry_row = hist.iloc[entry_idx]
    entry_price = float(entry_row["Open"])
    if entry_price <= 0:
        return None

    tp_price = entry_price * (1 + TAKE_PROFIT)
    sl_price = entry_price * (1 - STOP_LOSS)

    exit_price = None
    exit_reason = None
    exit_day_offset = None

    end_idx = min(entry_idx + HOLD_DAYS, len(hist) - 1)
    for j in range(entry_idx, end_idx + 1):
        bar = hist.iloc[j]
        high = float(bar["High"])
        low = float(bar["Low"])
        close = float(bar["Close"])

        # On entry day, the open IS the entry price; check intraday
        # On subsequent days, check from open onwards
        if j == entry_idx:
            # If gap up above TP at open, treat open as exit (slippage in our favor capped by realism)
            if entry_price >= tp_price:
                exit_price = entry_price
                exit_reason = "tp_at_open"
                exit_day_offset = 0
                break
            # If gap down below SL at open, exit at open
            if entry_price <= sl_price:
                exit_price = entry_price
                exit_reason = "sl_at_open"
                exit_day_offset = 0
                break
            # Pessimistic ordering: assume low hit first, then high
            # This is the standard backtester convention since intraday path is unknown
            if low <= sl_price:
                exit_price = sl_price
                exit_reason = "sl_intraday"
                exit_day_offset = 0
                break
            if high >= tp_price:
                exit_price = tp_price
                exit_reason = "tp_intraday"
                exit_day_offset = 0
                break
        else:
            day_open = float(bar["Open"])
            if day_open >= tp_price:
                exit_price = day_open
                exit_reason = "tp_gap"
                exit_day_offset = j - entry_idx
                break
            if day_open <= sl_price:
                exit_price = day_open
                exit_reason = "sl_gap"
                exit_day_offset = j - entry_idx
                break
            if low <= sl_price:
                exit_price = sl_price
                exit_reason = "sl_intraday"
                exit_day_offset = j - entry_idx
                break
            if high >= tp_price:
                exit_price = tp_price
                exit_reason = "tp_intraday"
                exit_day_offset = j - entry_idx
                break

    if exit_price is None:
        # Time exit at close of last bar
        last_bar = hist.iloc[end_idx]
        exit_price = float(last_bar["Close"])
        exit_reason = "time_exit"
        exit_day_offset = end_idx - entry_idx

    gross_ret = exit_price / entry_price - 1.0
    return {
        "entry_date": hist.index[entry_idx].strftime("%Y-%m-%d"),
        "exit_date": hist.index[entry_idx + exit_day_offset].strftime("%Y-%m-%d"),
        "entry_price": entry_price,
        "exit_price": exit_price,
        "gross_return": gross_ret,
        "exit_reason": exit_reason,
        "hold_days": exit_day_offset,
    }


def main() -> None:
    events = pd.read_csv(EVENTS_CSV)
    print(f"Simulating {len(events)} trades...")

    trades = []
    cache: dict[str, pd.DataFrame] = {}

    for i, ev in events.iterrows():
        sym = ev["symbol"]
        if sym not in cache:
            hist = get_history(sym)
            if hist is None:
                cache[sym] = None
            else:
                cache[sym] = hist
            time.sleep(0.05)
        hist = cache[sym]
        if hist is None:
            continue
        result = simulate_trade(hist, ev["trigger_date"])
        if result is None:
            continue
        result["symbol"] = sym
        result["trigger_date"] = ev["trigger_date"]
        result["trigger_intraday_ret"] = ev["trigger_intraday_ret"]
        result["trigger_vol_ratio"] = ev["trigger_vol_ratio"]
        trades.append(result)
        if (i + 1) % 100 == 0:
            print(f"  {i + 1}/{len(events)} done, {len(trades)} trades simulated")

    df = pd.DataFrame(trades)
    df.to_csv(OUT_TRADES, index=False)
    print(f"\nSaved {len(df)} trades to {OUT_TRADES}")

    # Sensitivity to costs
    print("\n=== RESULTS ===")
    print(f"Total trades: {len(df)}")
    print(f"Take-profit: +{TAKE_PROFIT:.0%} / Stop-loss: -{STOP_LOSS:.0%} / Hold: {HOLD_DAYS}d max\n")

    print(f"{'cost':<22} {'win%':>6} {'avg_ret':>9} {'median':>9} {'expect':>9} {'total_eq':>10} {'sharpe':>8}")
    for label, cost in COST_SCENARIOS.items():
        net = df["gross_return"] - cost
        wins = (net > 0).sum()
        win_rate = wins / len(net) if len(net) else 0
        avg = net.mean()
        med = net.median()
        # Expectancy (per-trade arithmetic mean) already = avg
        # Compounded equity if we trade each event with fixed fraction (here 100%)
        # but that's unrealistic; report sum of returns instead
        equity_sum = net.sum()
        sharpe = (avg / net.std()) * np.sqrt(252) if net.std() > 0 else 0
        print(f"{label:<22} {win_rate:>6.1%} {avg:>9.2%} {med:>9.2%} {avg:>9.2%} {equity_sum:>10.2f} {sharpe:>8.2f}")

    print("\n=== EXIT REASON BREAKDOWN ===")
    print(df["exit_reason"].value_counts().to_string())

    print("\n=== GROSS RETURN DISTRIBUTION ===")
    g = df["gross_return"]
    print(f"  mean:   {g.mean():.2%}")
    print(f"  median: {g.median():.2%}")
    print(f"  std:    {g.std():.2%}")
    print(f"  min:    {g.min():.2%}")
    print(f"  max:    {g.max():.2%}")
    print(f"  p10:    {g.quantile(0.10):.2%}")
    print(f"  p90:    {g.quantile(0.90):.2%}")


if __name__ == "__main__":
    main()
