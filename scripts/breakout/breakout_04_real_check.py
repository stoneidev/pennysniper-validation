"""
Re-check the "$1.05~$1.20 weak breakout" result with realistic exit.

Previous claim: 30-day buy-and-hold returned +52% mean, +24% with TP/SL.
But we just learned penny stocks crash hard after spikes.

Test: of those 36 events, what % are still profitable as of TODAY (latest close)?
What was the TRUE intra-30-day max DD vs final close?
"""
import pandas as pd
import numpy as np
from pathlib import Path

# Load all events
df = pd.read_csv('breakout_universe.csv', parse_dates=['date'])
sub = df[(df['today_close'] >= 1.05) & (df['today_close'] < 1.20)].copy()
print(f"$1.05~$1.20 weak breakout events: {len(sub)}")

results = []
for _, ev in sub.iterrows():
    sym = ev['symbol']
    bdate = ev['date']
    next_open = ev['next_open']

    f = Path(f'price_cache/{sym}.csv')
    if not f.exists():
        continue
    d = pd.read_csv(f, index_col=0, parse_dates=True).sort_index()
    if len(d) == 0:
        continue

    idx = d.index.searchsorted(bdate) + 1  # next-day open day
    if idx >= len(d):
        continue

    latest_close = float(d['Close'].iloc[-1])
    latest_date = d.index[-1]
    days_since = (latest_date - bdate).days

    # 30-day window from entry
    end_idx = min(idx + 30, len(d))
    window = d.iloc[idx:end_idx]

    if len(window) == 0:
        continue

    max_high_30d = float(window['High'].max())
    min_low_30d = float(window['Low'].min())
    close_30d = float(window['Close'].iloc[-1])

    # Strategies
    ret_30d_close = close_30d / next_open - 1.0
    ret_to_now = latest_close / next_open - 1.0
    max_unrealized_gain_30d = max_high_30d / next_open - 1.0
    max_drawdown_30d = min_low_30d / next_open - 1.0

    results.append({
        'symbol': sym,
        'breakout_date': bdate.strftime('%Y-%m-%d'),
        'next_open': next_open,
        'max_high_30d': max_high_30d,
        'min_low_30d': min_low_30d,
        'close_30d': close_30d,
        'latest_close': latest_close,
        'days_since': days_since,
        'ret_30d_close': ret_30d_close,
        'ret_to_now': ret_to_now,
        'max_gain_30d': max_unrealized_gain_30d,
        'max_dd_30d': max_drawdown_30d,
    })

r = pd.DataFrame(results)
print(f"Realized: {len(r)} events with full 30-day data")

print(f"\nDistribution of 30-day BUY-AND-HOLD return (close to close):")
print(f"  mean:    {r['ret_30d_close'].mean():+.2%}")
print(f"  median:  {r['ret_30d_close'].median():+.2%}")
print(f"  win%:    {(r['ret_30d_close']>0).mean():.1%}")
print(f"  p10:     {r['ret_30d_close'].quantile(0.10):+.2%}")
print(f"  p90:     {r['ret_30d_close'].quantile(0.90):+.2%}")

print(f"\nDistribution of HOLD-TO-NOW return:")
print(f"  mean:    {r['ret_to_now'].mean():+.2%}")
print(f"  median:  {r['ret_to_now'].median():+.2%}")
print(f"  win%:    {(r['ret_to_now']>0).mean():.1%}")

print(f"\n30-day max gain vs max drawdown:")
print(f"  mean max gain:    {r['max_gain_30d'].mean():+.2%}")
print(f"  mean max DD:      {r['max_dd_30d'].mean():+.2%}")
print(f"  events with DD < -20% before any +50%:")
both = r[(r['max_dd_30d'] < -0.20)]
print(f"    {len(both)}/{len(r)} = {len(both)/len(r):.1%}")

# Realistic TP+SL: which fired first?
# We don't have intra-day path; conservatively if max_dd < -20% AND max_gain >= 50%, assume SL first
print(f"\nRealistic TP+50/SL-20 outcome (pessimistic SL-first if both touched):")
def outcome(row):
    if row['max_dd_30d'] <= -0.20 and row['max_gain_30d'] >= 0.50:
        return -0.20
    elif row['max_gain_30d'] >= 0.50:
        return 0.50
    elif row['max_dd_30d'] <= -0.20:
        return -0.20
    else:
        return row['ret_30d_close']
r['tpsl_outcome'] = r.apply(outcome, axis=1)
r['tpsl_net'] = r['tpsl_outcome'] - 0.02  # 2% slippage
print(f"  mean: {r['tpsl_net'].mean():+.2%}")
print(f"  win%: {(r['tpsl_net']>0).mean():.1%}")
print(f"  sum:  {r['tpsl_net'].sum():+.2f}")

# Top winners and losers
print(f"\nTop 5 winners (30-day close):")
print(r.nlargest(5, 'ret_30d_close')[['symbol', 'breakout_date', 'next_open', 'close_30d', 'latest_close', 'ret_30d_close', 'ret_to_now']].to_string(index=False))
print(f"\nTop 5 losers (30-day close):")
print(r.nsmallest(5, 'ret_30d_close')[['symbol', 'breakout_date', 'next_open', 'close_30d', 'latest_close', 'ret_30d_close', 'ret_to_now']].to_string(index=False))

r.to_csv('breakout_real_check.csv', index=False)
