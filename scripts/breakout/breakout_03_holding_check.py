"""
Critical check: did the breakout winners actually hold their gains?
Compare 90-day max high vs the LATEST price.

This reveals whether buy-and-hold is realistic, or whether we'd need
perfect timing (sell at peak) to capture the +900% averages we saw.
"""
import pandas as pd
from pathlib import Path

events = pd.read_csv('breakout_events.csv')
unique_events = events.drop_duplicates(['symbol', 'date'])

print("Did breakout winners HOLD their gains, or crash back?")
print("=" * 100)
print(f"{'sym':<8} {'breakout_d':<12} {'b_close':>9} {'90d_max':>9} "
      f"{'latest':>9} {'date':<12} {'dd_from_peak':>14} {'hold_ret':>10}")
print("-" * 100)

drawdowns = []
hold_returns = []

for _, ev in unique_events.iterrows():
    sym = ev['symbol']
    bdate = ev['date']
    bclose = float(ev['breakout_close'])
    max90 = ev.get('max_high_90d')

    f = Path(f'price_cache/{sym}.csv')
    if not f.exists():
        continue
    d = pd.read_csv(f, index_col=0, parse_dates=True).sort_index()
    if len(d) == 0:
        continue
    latest = float(d['Close'].iloc[-1])
    latest_date = d.index[-1].strftime('%Y-%m-%d')

    if pd.isna(max90):
        max90_s = 'N/A'
        dd_s = 'N/A'
    else:
        max90 = float(max90)
        max90_s = f"${max90:.2f}"
        dd = (latest / max90 - 1) * 100
        dd_s = f"{dd:+.1f}%"
        drawdowns.append(dd)

    hold_ret = (latest / bclose - 1) * 100
    hold_returns.append(hold_ret)

    print(f"{sym:<8} {bdate:<12} ${bclose:>8.2f} {max90_s:>9} "
          f"${latest:>8.2f} {latest_date:<12} {dd_s:>14} {hold_ret:>+9.1f}%")

print()
print(f"Summary across {len(unique_events)} breakouts:")
if hold_returns:
    import statistics
    print(f"  Mean hold-to-now return:  {statistics.mean(hold_returns):+.1f}%")
    print(f"  Median:                   {statistics.median(hold_returns):+.1f}%")
    print(f"  Winners (>0):             {sum(1 for r in hold_returns if r > 0)}/{len(hold_returns)}")
    print(f"  Losers (<-50%):           {sum(1 for r in hold_returns if r < -50)}/{len(hold_returns)}")
if drawdowns:
    print(f"\n  Mean drawdown peak→now:   {statistics.mean(drawdowns):+.1f}%")
    print(f"  Median drawdown:          {statistics.median(drawdowns):+.1f}%")
    print(f"  Stocks crashed >-50%:     {sum(1 for d in drawdowns if d < -50)}/{len(drawdowns)}")
    print(f"  Stocks crashed >-80%:     {sum(1 for d in drawdowns if d < -80)}/{len(drawdowns)}")
