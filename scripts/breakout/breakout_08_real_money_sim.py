"""
Real money simulation: ₩1,000,000 starting Jan 2025, following the 60d
consolidation breakout rule.

Strategy:
  - Trigger: 60d below $1, today close in [$1.05, $1.20]
  - Entry: NEXT day at OPEN
  - Exit: TP $2.40 OR after 180 days (whichever comes first)
  - Slippage: 2% round-trip

Capital allocation:
  Compare 3 strategies:
    A. ALL-IN per signal (100% of cash)
    B. 25% per signal (max 4 simultaneous positions)
    C. 10% per signal (more diversification)

Currency:
  - Initial: ₩1,000,000 (KRW)
  - USD/KRW: assume 1,400 (rough average 2025)
  - = $714 USD start
  - Returns in % so currency factor applied at end

Constraint:
  - Cannot enter if cash < min_position
  - Must wait for cash to free up (TP/180d exit)
"""
import pandas as pd
import numpy as np
from pathlib import Path
import matplotlib.pyplot as plt

DAILY_CACHE = Path("price_cache")
SLIP = 0.02

# Read all 60d events
df = pd.read_csv("breakout_60d_results.csv")
df["date_dt"] = pd.to_datetime(df["date"])

# Filter: from 2025-01-01 onwards
START_DATE = pd.Timestamp("2025-01-01")
events = df[df["date_dt"] >= START_DATE].sort_values("date_dt").reset_index(drop=True)
print(f"Events from {START_DATE.date()} onwards: {len(events)}")
print()

# Pre-load price data for each symbol
price_cache = {}
for sym in events["symbol"].unique():
    f = DAILY_CACHE / f"{sym}.csv"
    if f.exists():
        d = pd.read_csv(f, index_col=0, parse_dates=True).sort_index()
        price_cache[sym] = d


def simulate_trade(symbol, breakout_date, entry_price, capital_in):
    """Simulate single trade. Returns (exit_date, capital_out, return_pct, exit_reason)."""
    d = price_cache.get(symbol)
    if d is None:
        return None
    bdate = pd.Timestamp(breakout_date)
    idx = d.index.searchsorted(bdate) + 1  # next-day open day
    if idx >= len(d):
        return None
    if entry_price <= 0:
        return None

    tp = 2.40
    max_hold = 180

    end_idx = min(idx + max_hold, len(d))
    for j in range(idx, end_idx):
        bar = d.iloc[j]
        # Check if TP hit (using High)
        if float(bar["High"]) >= tp:
            # Sold at TP
            ret = tp / entry_price - 1.0 - SLIP
            capital_out = capital_in * (1 + ret)
            return (d.index[j], capital_out, ret, f"TP@${tp}")
    # Held to horizon close
    last_bar = d.iloc[end_idx - 1]
    exit_p = float(last_bar["Close"])
    ret = exit_p / entry_price - 1.0 - SLIP
    capital_out = capital_in * (1 + ret)
    return (d.index[end_idx - 1], capital_out, ret, f"180d_close@${exit_p:.2f}")


def run_strategy(events, allocation_pct, label):
    """Allocation per trade as fraction of CURRENT cash (or NAV)."""
    print(f"\n{'=' * 78}")
    print(f"Strategy: {label} — allocate {allocation_pct*100:.0f}% per trade")
    print(f"{'=' * 78}")

    cash = 1_000_000  # KRW
    portfolio_value = cash
    open_positions = []  # list of (symbol, entry_price, exit_date, capital_in)
    trades = []
    equity_history = [(START_DATE, cash)]

    for _, ev in events.iterrows():
        bdate = ev["date_dt"]
        sym = ev["symbol"]
        entry = float(ev["next_open"])

        # Settle any positions whose exit_date <= today
        new_open = []
        for pos_sym, pos_entry, pos_exit_date, pos_capital, pos_ret, pos_reason in open_positions:
            if pos_exit_date <= bdate:
                cash += pos_capital
                trades[-len([t for t in trades if t["symbol"] == pos_sym]):]
            else:
                new_open.append((pos_sym, pos_entry, pos_exit_date, pos_capital, pos_ret, pos_reason))
        open_positions = new_open

        # Allocation = % of CURRENT cash
        position_size = cash * allocation_pct
        if position_size < 1000:  # less than 1000 KRW, skip
            continue

        # Simulate the trade
        result = simulate_trade(sym, ev["date"], entry, position_size)
        if result is None:
            continue
        exit_date, capital_out, ret, reason = result

        # Spend cash
        cash -= position_size
        # Schedule the exit
        open_positions.append((sym, entry, exit_date, capital_out, ret, reason))

        trades.append({
            "symbol": sym,
            "breakout_date": ev["date"],
            "entry_date": (bdate + pd.Timedelta(days=1)).date(),
            "exit_date": exit_date.date(),
            "entry_price": entry,
            "position_in": position_size,
            "position_out": capital_out,
            "return_pct": ret,
            "exit_reason": reason,
            "days_held": (exit_date - bdate).days,
        })
        equity_history.append((bdate, cash + sum(p[3] for p in open_positions)))

    # Settle remaining positions (using their scheduled exit values)
    for pos_sym, pos_entry, pos_exit_date, pos_capital, pos_ret, pos_reason in open_positions:
        cash += pos_capital
        equity_history.append((pos_exit_date, cash))

    final_value = cash

    # Trades dataframe
    t = pd.DataFrame(trades)
    if len(t) > 0:
        # Sort by entry date for display
        t = t.sort_values("entry_date").reset_index(drop=True)
        print(f"\nTrades executed: {len(t)}")
        print(f"\n{'symbol':<8} {'entry_d':<12} {'exit_d':<12} {'entry$':>8} {'in_KRW':>10} {'out_KRW':>10} {'ret':>8} {'days':>5} {'reason':<20}")
        for _, tr in t.iterrows():
            print(f"{tr['symbol']:<8} {str(tr['entry_date']):<12} {str(tr['exit_date']):<12} "
                  f"${tr['entry_price']:>7.2f} ₩{tr['position_in']:>9,.0f} ₩{tr['position_out']:>9,.0f} "
                  f"{tr['return_pct']:>+7.1%} {tr['days_held']:>5} {tr['exit_reason']:<20}")

        print(f"\nWin rate: {(t['return_pct']>0).mean():.1%}")
        print(f"Mean per trade: {t['return_pct'].mean():+.2%}")
        print(f"Best:           {t['return_pct'].max():+.2%} ({t.loc[t['return_pct'].idxmax(), 'symbol']})")
        print(f"Worst:          {t['return_pct'].min():+.2%} ({t.loc[t['return_pct'].idxmin(), 'symbol']})")

    print(f"\n💰 FINAL VALUE: ₩{final_value:,.0f}")
    print(f"   Initial:      ₩1,000,000")
    print(f"   Total return: {(final_value/1_000_000 - 1)*100:+.1f}%")

    return final_value, t, equity_history


# Run all 3 strategies
result_A = run_strategy(events, 1.00, "ALL-IN (100% per signal, sequential)")
result_B = run_strategy(events, 0.25, "25% per signal (up to 4 positions)")
result_C = run_strategy(events, 0.10, "10% per signal (up to 10 positions)")

# Compare
print(f"\n{'=' * 78}")
print("FINAL COMPARISON")
print(f"{'=' * 78}")
print(f"{'strategy':<35} {'final ₩':>15} {'return':>10}")
for label, (val, _, _) in [
    ("ALL-IN sequential", (result_A[0], None, None)),
    ("25% per trade", (result_B[0], None, None)),
    ("10% per trade", (result_C[0], None, None)),
]:
    ret = (val / 1_000_000 - 1) * 100
    print(f"{label:<35} ₩{val:>14,.0f} {ret:>+9.1f}%")

# Plot equity curves
fig, ax = plt.subplots(figsize=(12, 6))
for label, (final, t, eq) in [
    (f"ALL-IN: ₩{result_A[0]:,.0f}", result_A),
    (f"25% per trade: ₩{result_B[0]:,.0f}", result_B),
    (f"10% per trade: ₩{result_C[0]:,.0f}", result_C),
]:
    eq_df = pd.DataFrame(eq, columns=["date", "value"]).sort_values("date")
    ax.plot(eq_df["date"], eq_df["value"], marker=".", label=label)
ax.axhline(1_000_000, color="black", linestyle="--", linewidth=0.5, label="Initial ₩1,000,000")
ax.set_title("₩1,000,000 starting Jan 2025: 60d-cons + breakout $1.05~$1.20 + TP $2.40 / 180d max")
ax.set_xlabel("Date")
ax.set_ylabel("Portfolio value (KRW)")
ax.legend(loc="upper left")
ax.grid(alpha=0.3)
ax.set_yscale("linear")
fig.tight_layout()
fig.savefig("breakout_real_money_sim.png", dpi=120)
plt.close(fig)
print("\nSaved breakout_real_money_sim.png")
