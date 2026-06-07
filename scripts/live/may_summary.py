"""
Generate May 2025 HTML summary report.

Aggregates all signals from May 2025 daily HTML reports and shows realized outcomes.
"""
import html
import re
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
REPORTS = REPO / "reports"
CACHE = REPO / "data" / "daily_cache"

TP_RATIO = 1.50
HOLD = 60
SLIP = 0.02


# Re-use CSS from daily_report.py
CSS = """
:root {
  --bg: #0f1115;
  --panel: #181b22;
  --panel-2: #1f232c;
  --border: #2a2f3a;
  --text: #e8e8ea;
  --muted: #8b93a7;
  --accent: #4f8cff;
  --green: #1fbf75;
  --red: #ff5b6c;
  --yellow: #f5b342;
}
* { box-sizing: border-box; }
body {
  margin: 0; padding: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
  background: var(--bg); color: var(--text); line-height: 1.5;
}
.container { max-width: 980px; margin: 0 auto; padding: 32px 20px 80px; }
header { padding-bottom: 24px; border-bottom: 1px solid var(--border); margin-bottom: 28px; }
h1 { margin: 0 0 6px; font-size: 26px; font-weight: 700; }
.sub { color: var(--muted); font-size: 13px; }
.nav { margin-top: 14px; }
.nav a { display: inline-block; margin-right: 12px; color: var(--accent); text-decoration: none; font-size: 13px; }
.nav a:hover { text-decoration: underline; }

.card { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 20px; margin-bottom: 20px; }
.card h2 { margin: 0 0 14px; font-size: 16px; font-weight: 600; }

.stats-grid {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px;
}
.stat {
  background: var(--panel-2); border-radius: 8px; padding: 14px;
}
.stat .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.stat .value { font-size: 22px; font-weight: 700; margin-top: 4px; font-variant-numeric: tabular-nums; }
.stat .value.green { color: var(--green); }
.stat .value.red { color: var(--red); }

table.trades { width: 100%; border-collapse: collapse; }
table.trades th, table.trades td {
  padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); font-size: 13px;
}
table.trades th {
  background: var(--panel-2); color: var(--muted);
  font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; font-size: 11px;
}
table.trades td.num { text-align: right; font-variant-numeric: tabular-nums; }
table.trades td.sym {
  font-weight: 700; font-family: "SF Mono", Menlo, Consolas, monospace;
}
table.trades td.win { color: var(--green); font-weight: 600; }
table.trades td.lose { color: var(--red); font-weight: 600; }
.tag {
  display: inline-block; padding: 2px 8px;
  background: var(--panel-2); border: 1px solid var(--border);
  border-radius: 4px; font-size: 11px; color: var(--muted);
}

.kv { display: grid; grid-template-columns: 200px 1fr; gap: 8px 16px; font-size: 14px; }
.kv .k { color: var(--muted); }
.kv .v { color: var(--text); }

footer {
  margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border);
  color: var(--muted); font-size: 11px; line-height: 1.6;
}
"""


def main():
    # Parse signals from each May daily HTML
    signals = []
    for f in sorted(REPORTS.glob("2025-05-*.html")):
        text = f.read_text(encoding="utf-8")
        # Find rows in the signals table
        # Pattern: <td class="sym">SYM</td><td class="num">$X.XX</td><td class="num">$Y.YY</td><td class="num">$Z.ZZ</td><td class="num target">$T.TT</td>
        rows = re.findall(
            r'<td class="sym">([A-Z]+)</td>\s*'
            r'<td class="num">\$([\d.]+)</td>\s*'
            r'<td class="num">\$([\d.]+)</td>\s*'
            r'<td class="num">\$([\d.]+)</td>\s*'
            r'<td class="num target">\$([\d.]+)</td>',
            text,
        )
        for sym, today, prev, cons, target in rows:
            signals.append({
                "signal_date": f.stem,
                "symbol": sym,
                "today_close": float(today),
                "tp_target": float(target),
            })

    print(f"Found {len(signals)} signals across May reports")

    # Resolve each signal: simulate entry & exit
    results = []
    for s in signals:
        sym = s["symbol"]
        sig_date = pd.Timestamp(s["signal_date"])
        csv = CACHE / f"{sym}.csv"
        if not csv.exists():
            continue
        df = pd.read_csv(csv, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
        idx = df.index[df["Date"] == sig_date]
        if len(idx) == 0:
            continue
        sig_idx = int(idx[0])
        if sig_idx + 1 >= len(df):
            continue

        entry_idx = sig_idx + 1
        entry = float(df["Open"].iloc[entry_idx])
        tp_price = entry * TP_RATIO
        end_idx = min(entry_idx + HOLD, len(df) - 1)
        exit_idx = end_idx
        exit_price = float(df["Close"].iloc[end_idx])
        tp_hit = False
        for j in range(entry_idx, end_idx + 1):
            if float(df["High"].iloc[j]) >= tp_price:
                exit_price = tp_price
                exit_idx = j
                tp_hit = True
                break
        days_held = exit_idx - entry_idx + 1
        gross = exit_price / entry - 1.0
        net = gross - SLIP
        results.append({
            "signal_date": s["signal_date"],
            "symbol": sym,
            "entry_date": df["Date"].iloc[entry_idx].strftime("%Y-%m-%d"),
            "entry": entry,
            "exit_date": df["Date"].iloc[exit_idx].strftime("%Y-%m-%d"),
            "exit_price": exit_price,
            "tp_hit": tp_hit,
            "days_held": days_held,
            "net_ret": net,
        })

    # Render HTML
    out = REPORTS / "_may_2025_summary.html"
    if not results:
        body = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>May 2025 Summary</title>
<style>{CSS}</style></head><body><div class="container">
<header><h1>May 2025 Summary</h1><div class="sub">No signals.</div></header>
</div></body></html>"""
        out.write_text(body, encoding="utf-8")
        return

    # Compute aggregates
    rets = [r["net_ret"] for r in results]
    win_rate = sum(1 for r in rets if r > 0) / len(rets)
    tp_rate = sum(1 for r in results if r["tp_hit"]) / len(results)
    mean_ret = sum(rets) / len(rets)

    cash = 1_000_000
    for r in rets:
        position = cash * 0.25
        cash = cash - position + position * (1 + r)
    final_value = cash
    total_return_pct = (cash / 1_000_000 - 1) * 100

    # Trade rows
    trade_rows = ""
    for r in results:
        cls = "win" if r["net_ret"] > 0 else "lose"
        tp_s = "✓" if r["tp_hit"] else "✗"
        trade_rows += f"""
        <tr>
          <td>{html.escape(r['signal_date'])}</td>
          <td class="sym">{html.escape(r['symbol'])}</td>
          <td>{html.escape(r['entry_date'])}</td>
          <td class="num">${r['entry']:.2f}</td>
          <td>{html.escape(r['exit_date'])}</td>
          <td class="num">${r['exit_price']:.2f}</td>
          <td>{tp_s}</td>
          <td class="num">{r['days_held']}</td>
          <td class="num {cls}">{r['net_ret']*100:+.1f}%</td>
        </tr>"""

    daily_links = ""
    for f in sorted(REPORTS.glob("2025-05-*.html")):
        daily_links += f'<li><a href="./{html.escape(f.name)}">{html.escape(f.stem)}</a></li>\n'

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>May 2025 Summary — Breakout Reports</title>
  <style>{CSS}</style>
</head>
<body>
<div class="container">
  <header>
    <h1>May 2025 — Breakout Summary</h1>
    <div class="sub">Aggregated outcome of all signals from May 1-30, 2025 daily reports.</div>
    <div class="nav">
      <a href="./index.html">← All reports</a>
      <a href="https://github.com/stoneidev/pennysniper-validation">GitHub repo</a>
    </div>
  </header>

  <div class="card">
    <h2>Active Rule (trained on 2025.01-03)</h2>
    <div class="kv">
      <div class="k">Consolidation</div><div class="v">30 trading days all closed &lt; $1.00</div>
      <div class="k">Entry range</div><div class="v">$1.05 – $1.20</div>
      <div class="k">Take profit</div><div class="v">+50% (entry × 1.50)</div>
      <div class="k">Max hold</div><div class="v">60 trading days</div>
      <div class="k">Slippage</div><div class="v">2% round-trip</div>
    </div>
    <div style="margin-top:14px;">
      <span class="tag">trained on 2025-01-01 ~ 2025-04-01</span>
      <span class="tag">applied retrospectively to May 2025</span>
    </div>
  </div>

  <div class="card">
    <h2>Aggregate Stats</h2>
    <div class="stats-grid">
      <div class="stat"><div class="label">Total signals</div><div class="value">{len(results)}</div></div>
      <div class="stat"><div class="label">TP +50% hit</div><div class="value green">{tp_rate*100:.0f}%</div></div>
      <div class="stat"><div class="label">Win rate</div><div class="value green">{win_rate*100:.0f}%</div></div>
      <div class="stat"><div class="label">Mean net return</div><div class="value {'green' if mean_ret > 0 else 'red'}">{mean_ret*100:+.1f}%</div></div>
    </div>
  </div>

  <div class="card">
    <h2>Trades</h2>
    <table class="trades">
      <thead>
        <tr>
          <th>Signal Date</th>
          <th>Symbol</th>
          <th>Entry Date</th>
          <th class="num">Entry</th>
          <th>Exit Date</th>
          <th class="num">Exit</th>
          <th>TP</th>
          <th class="num">Days</th>
          <th class="num">Net Return</th>
        </tr>
      </thead>
      <tbody>{trade_rows}
      </tbody>
    </table>
  </div>

  <div class="card">
    <h2>₩1,000,000 Simulation (25% allocation per trade)</h2>
    <div class="stats-grid">
      <div class="stat"><div class="label">Initial</div><div class="value">₩1,000,000</div></div>
      <div class="stat"><div class="label">Final value</div><div class="value green">₩{final_value:,.0f}</div></div>
      <div class="stat"><div class="label">Total return</div><div class="value green">+{total_return_pct:.1f}%</div></div>
      <div class="stat"><div class="label">Period</div><div class="value">May 2025</div></div>
    </div>
  </div>

  <div class="card">
    <h2>All May 2025 Daily Reports</h2>
    <ul style="padding-left:20px; margin:0;">
{daily_links}
    </ul>
  </div>

  <footer>
    Past performance does not guarantee future results. Slippage, taxes, broker fees not fully modeled.
    Paper-trade for 6+ months before deploying real capital.
  </footer>
</div>
</body>
</html>
"""
    out.write_text(body, encoding="utf-8")
    print(f"Wrote: {out}")
    print()
    print(f"Summary: {len(results)} signals, {tp_rate*100:.0f}% TP hit, mean {mean_ret*100:+.1f}%, "
          f"₩1M → ₩{final_value:,.0f} ({total_return_pct:+.1f}%)")


if __name__ == "__main__":
    main()
