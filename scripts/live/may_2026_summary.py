"""
Generate May 2026 HTML summary — same logic as may_summary.py but for 2026.

Rule: trained on 2026.01-03 → applied to 2026 Q2 (= 30d/$1.20-1.50/+15%/30d hold).
"""
import html
import re
import json
from pathlib import Path
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
REPORTS = REPO / "reports"
CACHE = REPO / "data" / "daily_cache"
RULE_FILE = REPO / "config" / "rule_2026_q2.json"

with open(RULE_FILE) as f:
    rule = json.load(f)
TP_RATIO = rule["tp_ratio"]
HOLD = rule["hold_d"]
SLIP = 0.02

# CSS reused from existing daily_report
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
.stats-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.stat { background: var(--panel-2); border-radius: 8px; padding: 14px; }
.stat .label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.stat .value { font-size: 22px; font-weight: 700; margin-top: 4px; font-variant-numeric: tabular-nums; }
.stat .value.green { color: var(--green); }
.stat .value.red { color: var(--red); }
table.trades { width: 100%; border-collapse: collapse; }
table.trades th, table.trades td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); font-size: 13px; }
table.trades th { background: var(--panel-2); color: var(--muted); font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; font-size: 11px; }
table.trades td.num { text-align: right; font-variant-numeric: tabular-nums; }
table.trades td.sym { font-weight: 700; font-family: "SF Mono", Menlo, Consolas, monospace; }
table.trades td.win { color: var(--green); font-weight: 600; }
table.trades td.lose { color: var(--red); font-weight: 600; }
.tag { display: inline-block; padding: 2px 8px; background: var(--panel-2); border: 1px solid var(--border); border-radius: 4px; font-size: 11px; color: var(--muted); margin-right: 4px; }
.kv { display: grid; grid-template-columns: 200px 1fr; gap: 8px 16px; font-size: 14px; }
.kv .k { color: var(--muted); }
.kv .v { color: var(--text); }
footer { margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border); color: var(--muted); font-size: 11px; line-height: 1.6; }
.note { padding: 12px 16px; background: rgba(245, 179, 66, 0.08); border-left: 3px solid var(--yellow); border-radius: 4px; font-size: 13px; color: var(--text); margin: 12px 0; }
"""


def main():
    # Parse signals from May 2026 daily HTML
    signals = []
    for f in sorted(REPORTS.glob("2026-05-*.html")):
        text = f.read_text(encoding="utf-8")
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

    print(f"Found {len(signals)} signals across May 2026 reports")

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
            print(f"  {sym}: no next-day data (still in flight)")
            results.append({
                "signal_date": s["signal_date"],
                "symbol": sym,
                "entry_date": "—",
                "entry": None,
                "exit_date": "still in flight",
                "exit_price": None,
                "tp_hit": None,
                "days_held": None,
                "net_ret": None,
                "in_flight": True,
            })
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

        # check if hold has actually completed (all HOLD bars must exist after entry)
        in_flight = (exit_idx == end_idx and not tp_hit and (end_idx - entry_idx + 1) < HOLD)

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
            "in_flight": in_flight,
        })

    # Render
    out = REPORTS / "_may_2026_summary.html"

    closed = [r for r in results if not r.get("in_flight", False) and r.get("net_ret") is not None]
    in_flight = [r for r in results if r.get("in_flight") or r.get("net_ret") is None]

    if closed:
        rets = [r["net_ret"] for r in closed]
        win_rate = sum(1 for r in rets if r > 0) / len(rets)
        tp_rate = sum(1 for r in closed if r["tp_hit"]) / len(closed)
        mean_ret = sum(rets) / len(rets)
        cash = 1_000_000
        for r in rets:
            position = cash * 0.25
            cash = cash - position + position * (1 + r)
        final_value = cash
        total_return_pct = (cash / 1_000_000 - 1) * 100
    else:
        win_rate = tp_rate = mean_ret = 0
        final_value = 1_000_000
        total_return_pct = 0

    # Trade rows
    trade_rows = ""
    for r in sorted(results, key=lambda x: x["signal_date"]):
        if r.get("in_flight") or r.get("net_ret") is None:
            cls = ""
            tp_s = "—"
            ret_s = '<span class="tag">in flight</span>'
            entry_s = f"${r['entry']:.2f}" if r.get("entry") else "—"
            exit_s = "—"
            days_s = "—"
        else:
            cls = "win" if r["net_ret"] > 0 else "lose"
            tp_s = "✓" if r["tp_hit"] else "✗"
            ret_s = f'{r["net_ret"]*100:+.1f}%'
            entry_s = f"${r['entry']:.2f}"
            exit_s = f"${r['exit_price']:.2f}"
            days_s = str(r["days_held"])

        trade_rows += f"""
        <tr>
          <td>{html.escape(r['signal_date'])}</td>
          <td class="sym">{html.escape(r['symbol'])}</td>
          <td>{html.escape(r['entry_date'])}</td>
          <td class="num">{entry_s}</td>
          <td>{html.escape(r['exit_date'])}</td>
          <td class="num">{exit_s}</td>
          <td>{tp_s}</td>
          <td class="num">{days_s}</td>
          <td class="num {cls}">{ret_s}</td>
        </tr>"""

    daily_links = ""
    for f in sorted(REPORTS.glob("2026-05-*.html")):
        daily_links += f'<li><a href="./{html.escape(f.name)}">{html.escape(f.stem)}</a></li>\n'

    rule_summary = (f"cons {rule['cons_d']}d / entry [${rule['entry_lo']:.2f}, ${rule['entry_hi']:.2f}) / "
                    f"TP +{(TP_RATIO-1)*100:.0f}% / hold {HOLD}d")

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>May 2026 Summary — Breakout Reports</title>
  <style>{CSS}</style>
</head>
<body>
<div class="container">
  <header>
    <h1>May 2026 — Breakout Summary</h1>
    <div class="sub">Aggregated outcome of all signals from May 1-29, 2026 daily reports.</div>
    <div class="nav">
      <a href="./index.html">← All reports</a>
      <a href="https://github.com/stoneidev/pennysniper-validation">GitHub repo</a>
    </div>
  </header>

  <div class="card">
    <h2>Active Rule (trained on 2026.01-03)</h2>
    <div class="kv">
      <div class="k">Consolidation</div><div class="v">{rule['cons_d']} trading days all closed &lt; $1.00</div>
      <div class="k">Entry range</div><div class="v">${rule['entry_lo']:.2f} – ${rule['entry_hi']:.2f}</div>
      <div class="k">Take profit</div><div class="v">+{(TP_RATIO-1)*100:.0f}% (entry × {TP_RATIO:.2f})</div>
      <div class="k">Max hold</div><div class="v">{HOLD} trading days</div>
      <div class="k">Slippage</div><div class="v">2% round-trip</div>
    </div>
    <div style="margin-top:14px;">
      <span class="tag">trained on {html.escape(rule.get('trained_on_period', '?'))}</span>
      <span class="tag">train N = {rule.get('train_n', '?')}</span>
      <span class="tag">train win {rule.get('train_win_rate', 0)*100:.1f}%</span>
      <span class="tag">applied to 2026 Q2 (Apr-Jun)</span>
    </div>
  </div>

  <div class="card">
    <h2>Aggregate Stats {("(closed trades only)" if in_flight else "")}</h2>
    <div class="stats-grid">
      <div class="stat"><div class="label">Total signals</div><div class="value">{len(results)}</div></div>
      <div class="stat"><div class="label">Closed trades</div><div class="value">{len(closed)}</div></div>
      <div class="stat"><div class="label">TP +{(TP_RATIO-1)*100:.0f}% hit</div>
        <div class="value {'green' if tp_rate > 0 else ''}">{tp_rate*100:.0f}%</div></div>
      <div class="stat"><div class="label">Mean net return</div>
        <div class="value {'green' if mean_ret > 0 else 'red' if mean_ret < 0 else ''}">{mean_ret*100:+.1f}%</div></div>
    </div>
    {f'<div class="note">⚠️ {len(in_flight)} trade(s) still in flight (hold period not yet complete). Numbers above reflect closed trades only.</div>' if in_flight else ''}
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
    <h2>₩1,000,000 Simulation (25% allocation per closed trade)</h2>
    <div class="stats-grid">
      <div class="stat"><div class="label">Initial</div><div class="value">₩1,000,000</div></div>
      <div class="stat"><div class="label">Final value</div>
        <div class="value {'green' if total_return_pct > 0 else 'red' if total_return_pct < 0 else ''}">₩{final_value:,.0f}</div></div>
      <div class="stat"><div class="label">Total return</div>
        <div class="value {'green' if total_return_pct > 0 else 'red' if total_return_pct < 0 else ''}">{total_return_pct:+.1f}%</div></div>
      <div class="stat"><div class="label">Period</div><div class="value">May 2026</div></div>
    </div>
  </div>

  <div class="card">
    <h2>All May 2026 Daily Reports</h2>
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
    print(f"\nSummary: {len(results)} signals ({len(closed)} closed, {len(in_flight)} in-flight)")
    if closed:
        print(f"  TP hit: {tp_rate*100:.0f}%, mean {mean_ret*100:+.1f}%, ₩1M → ₩{final_value:,.0f} ({total_return_pct:+.1f}%)")


if __name__ == "__main__":
    main()
