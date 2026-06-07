"""
Positions HTML report.

Reads data/positions.json and generates reports/_positions.html with:
  - Open positions (current unrealized P&L using latest cached close)
  - Closed history (realized P&L)
  - Cumulative stats (win rate, mean, total KRW)
  - Capital curve (sequential 25% allocation simulation)
  - Signal-vs-trade reconciliation (signals you didn't act on)
"""
import json
import html
from pathlib import Path
import re
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
POS_FILE = REPO / "data" / "positions.json"
REPORTS = REPO / "reports"
CACHE = REPO / "data" / "daily_cache"

CSS = """
:root {
  --bg:#0f1115; --panel:#181b22; --panel-2:#1f232c; --border:#2a2f3a;
  --text:#e8e8ea; --muted:#8b93a7; --accent:#4f8cff;
  --green:#1fbf75; --red:#ff5b6c; --yellow:#f5b342;
}
* { box-sizing: border-box; }
body { margin:0; padding:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:var(--bg); color:var(--text); line-height:1.5; }
.container { max-width:1080px; margin:0 auto; padding:32px 20px 80px; }
header { padding-bottom:24px; border-bottom:1px solid var(--border); margin-bottom:28px; }
h1 { margin:0 0 6px; font-size:26px; font-weight:700; }
h2 { margin:0 0 14px; font-size:16px; font-weight:600; }
.sub { color:var(--muted); font-size:13px; }
.nav { margin-top:14px; }
.nav a { display:inline-block; margin-right:12px; color:var(--accent); text-decoration:none; font-size:13px; }
.nav a:hover { text-decoration:underline; }
.card { background:var(--panel); border:1px solid var(--border); border-radius:10px; padding:20px; margin-bottom:20px; }
.stats-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; }
.stat { background:var(--panel-2); border-radius:8px; padding:14px; }
.stat .label { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:0.05em; }
.stat .value { font-size:22px; font-weight:700; margin-top:4px; font-variant-numeric:tabular-nums; }
.stat .value.green { color:var(--green); }
.stat .value.red { color:var(--red); }
.stat .small { font-size:11px; color:var(--muted); margin-top:4px; }

table { width:100%; border-collapse:collapse; }
th, td { padding:10px 12px; text-align:left; border-bottom:1px solid var(--border); font-size:13px; }
th { background:var(--panel-2); color:var(--muted); text-transform:uppercase; letter-spacing:0.05em; font-size:11px; font-weight:600; }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
td.sym { font-weight:700; font-family:"SF Mono",Menlo,Consolas,monospace; }
td.win { color:var(--green); font-weight:600; }
td.lose { color:var(--red); font-weight:600; }
td.muted { color:var(--muted); }

.tag { display:inline-block; padding:2px 8px; background:var(--panel-2); border:1px solid var(--border); border-radius:4px; font-size:11px; color:var(--muted); margin-right:4px; }
.pill { display:inline-block; padding:3px 10px; border-radius:999px; font-size:11px; font-weight:600; }
.pill.green { background:rgba(31,191,117,0.15); color:var(--green); }
.pill.red { background:rgba(255,91,108,0.15); color:var(--red); }
.pill.yellow { background:rgba(245,179,66,0.15); color:var(--yellow); }
.pill.muted { background:rgba(139,147,167,0.15); color:var(--muted); }
.pill.blue { background:rgba(79,140,255,0.15); color:var(--accent); }

footer { margin-top:40px; padding-top:20px; border-top:1px solid var(--border); color:var(--muted); font-size:11px; line-height:1.6; }

svg.curve { width:100%; height:200px; }
.curve-grid { stroke:var(--border); stroke-width:1; }
.curve-line { stroke:var(--green); stroke-width:2; fill:none; }
.curve-point { fill:var(--green); }

.empty { text-align:center; color:var(--muted); padding:32px 0; }
"""


def load_positions():
    if not POS_FILE.exists():
        return []
    return json.load(open(POS_FILE)).get("positions", [])


def latest_close(symbol):
    csv = CACHE / f"{symbol}.csv"
    if not csv.exists():
        return None
    try:
        df = pd.read_csv(csv, parse_dates=["Date"]).sort_values("Date")
        if len(df) == 0:
            return None
        return float(df["Close"].iloc[-1])
    except Exception:
        return None


def collect_signals_from_reports():
    """Parse all daily HTML reports to collect (date, symbol) signal pairs."""
    sigs = set()
    for f in REPORTS.glob("[0-9]*.html"):
        try:
            date = pd.Timestamp(f.stem).strftime("%Y-%m-%d")
        except Exception:
            continue
        text = f.read_text(encoding="utf-8")
        rows = re.findall(r'<td class="sym">([A-Z]+)</td>', text)
        for sym in rows:
            sigs.add((date, sym))
    return sigs


def make_curve_svg(rets, width=1000, height=200, padding=20):
    """Sequential 25% allocation capital curve."""
    if not rets:
        return ""
    cash = 1_000_000
    pts = [(0, cash)]
    for r in rets:
        pos = cash * 0.25
        cash = cash - pos + pos * (1 + r)
        pts.append((len(pts), cash))
    if len(pts) < 2:
        return ""
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    if ymax == ymin:
        ymax += 1
    def sx(x): return padding + (x - xmin) / (xmax - xmin) * (width - 2*padding)
    def sy(y): return height - padding - (y - ymin) / (ymax - ymin) * (height - 2*padding)
    path = " ".join(f"{'M' if i==0 else 'L'} {sx(x):.1f} {sy(y):.1f}" for i, (x, y) in enumerate(pts))
    points = "".join(f'<circle class="curve-point" cx="{sx(x):.1f}" cy="{sy(y):.1f}" r="2.5"/>' for x, y in pts)
    # Horizontal initial line
    init_y = sy(1_000_000)
    return f"""
<svg class="curve" viewBox="0 0 {width} {height}" preserveAspectRatio="none">
  <line class="curve-grid" x1="{padding}" y1="{init_y}" x2="{width-padding}" y2="{init_y}"
        stroke-dasharray="4,4"/>
  <path class="curve-line" d="{path}"/>
  {points}
  <text x="{width-padding}" y="{init_y - 6}" fill="#8b93a7" font-size="10" text-anchor="end">₩1M start</text>
  <text x="{padding}" y="14" fill="#e8e8ea" font-size="11" font-weight="600">₩{cash:,.0f}</text>
</svg>
"""


def main():
    positions = load_positions()
    open_pos = [p for p in positions if p.get("sell_date") is None]
    closed_pos = [p for p in positions if p.get("sell_date") is not None]
    closed_pos.sort(key=lambda x: x.get("sell_date") or x["buy_date"])

    today = pd.Timestamp.now().normalize()

    # ---------- Cumulative stats ----------
    if closed_pos:
        rets = [p["realized_pnl_pct"] for p in closed_pos]
        wr = sum(1 for r in rets if r > 0) / len(rets)
        avg = sum(rets) / len(rets)
        total_krw = sum(p.get("realized_pnl_krw", 0) for p in closed_pos)
        # Capital curve (sequential 25%)
        cash = 1_000_000
        for r in rets:
            cash = cash - cash * 0.25 + cash * 0.25 * (1 + r)
        final_cash = cash
        total_pct = (cash / 1_000_000 - 1) * 100
    else:
        rets = []
        wr = avg = 0
        total_krw = 0
        final_cash = 1_000_000
        total_pct = 0

    # ---------- Open positions table ----------
    open_rows = ""
    open_unrealized_total = 0
    for p in sorted(open_pos, key=lambda x: x["buy_date"]):
        cur = latest_close(p["symbol"])
        if cur:
            pnl_pct = (cur / p["buy_price"] - 1) * 100
            cur_s = f"${cur:.2f}"
            cls = "win" if pnl_pct > 0 else ("lose" if pnl_pct < 0 else "muted")
            pnl_s = f"{pnl_pct:+.1f}%"
            open_unrealized_total += (cur - p["buy_price"]) * p["shares"]
        else:
            cur_s = "—"; pnl_s = "—"; cls = "muted"
        tp_s = f"${p['tp_target']:.2f}" if p.get("tp_target") else "—"
        days_held = (today - pd.Timestamp(p["buy_date"])).days
        mh = pd.Timestamp(p["max_hold_until"]) if p.get("max_hold_until") else None
        if mh and today > mh:
            stat_pill = '<span class="pill yellow">EXPIRED</span>'
        elif p.get("tp_target") and cur and cur >= p["tp_target"]:
            stat_pill = '<span class="pill green">TP REACHED</span>'
        else:
            stat_pill = f'<span class="pill blue">holding {days_held}d</span>'
        open_rows += f"""
        <tr>
          <td>{html.escape(p['id'])}</td>
          <td class="sym">{html.escape(p['symbol'])}</td>
          <td>{p['buy_date']}</td>
          <td class="num">${p['buy_price']:.2f}</td>
          <td class="num">{p['shares']:,}</td>
          <td class="num">{cur_s}</td>
          <td class="num {cls}">{pnl_s}</td>
          <td class="num">{tp_s}</td>
          <td>{stat_pill}</td>
        </tr>"""
    if not open_rows:
        open_rows = '<tr><td colspan="9" class="empty">No open positions.</td></tr>'

    # ---------- Closed positions table ----------
    closed_rows = ""
    for p in reversed(closed_pos):  # latest first
        cls = "win" if p["realized_pnl_pct"] > 0 else "lose"
        pnl_s = f"{p['realized_pnl_pct']*100:+.1f}%"
        krw = p.get("realized_pnl_krw", 0)
        closed_rows += f"""
        <tr>
          <td>{html.escape(p['id'])}</td>
          <td class="sym">{html.escape(p['symbol'])}</td>
          <td>{p['buy_date']}</td>
          <td>{p['sell_date']}</td>
          <td class="num">${p['buy_price']:.2f}</td>
          <td class="num">${p['sell_price']:.2f}</td>
          <td class="num {cls}">{pnl_s}</td>
          <td class="num {cls}">{krw:+,d}</td>
          <td class="muted">{html.escape(p.get('exit_reason') or '—')}</td>
        </tr>"""
    if not closed_rows:
        closed_rows = '<tr><td colspan="9" class="empty">No closed trades yet.</td></tr>'

    # ---------- Signal vs trade reconciliation ----------
    sig_pairs = collect_signals_from_reports()
    traded_pairs = set()
    for p in positions:
        # We approximate signal date as buy_date - 1 trading day
        # Simpler: just match symbols on buy_date or buy_date-1
        traded_pairs.add((p["buy_date"], p["symbol"]))
        # Also try one day earlier (signal day vs buy day)
        try:
            sig_date = (pd.Timestamp(p["buy_date"]) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            traded_pairs.add((sig_date, p["symbol"]))
        except Exception:
            pass

    missed_sigs = [(d, s) for (d, s) in sig_pairs if (d, s) not in traded_pairs]
    missed_sigs.sort(reverse=True)
    missed_rows = ""
    for d, s in missed_sigs[:30]:
        cur = latest_close(s)
        cur_s = f"${cur:.2f}" if cur else "—"
        missed_rows += f"""
        <tr>
          <td>{d}</td>
          <td class="sym">{html.escape(s)}</td>
          <td class="num">{cur_s}</td>
        </tr>"""
    if not missed_rows:
        missed_rows = '<tr><td colspan="3" class="empty">All signals acted upon (or no signals yet).</td></tr>'

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Positions & P&L — PennySniper</title>
  <style>{CSS}</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Positions & P&L</h1>
    <div class="sub">Tracking your actual buys/sells against the system signals. Generated {pd.Timestamp.now().isoformat()}</div>
    <div class="nav">
      <a href="./index.html">← All reports</a>
      <a href="https://github.com/stoneidev/pennysniper-validation">GitHub</a>
    </div>
  </header>

  <div class="card">
    <h2>Cumulative (closed trades only)</h2>
    <div class="stats-grid">
      <div class="stat"><div class="label">Closed trades</div>
        <div class="value">{len(closed_pos)}</div></div>
      <div class="stat"><div class="label">Win rate</div>
        <div class="value {'green' if wr >= 0.5 else 'red' if wr > 0 else 'muted'}">{wr*100:.1f}%</div></div>
      <div class="stat"><div class="label">Mean P&L</div>
        <div class="value {'green' if avg > 0 else 'red' if avg < 0 else 'muted'}">{avg*100:+.2f}%</div></div>
      <div class="stat"><div class="label">Realized KRW</div>
        <div class="value {'green' if total_krw > 0 else 'red' if total_krw < 0 else 'muted'}">₩{total_krw:+,d}</div></div>
    </div>
  </div>

  <div class="card">
    <h2>Capital curve — ₩1M with 25% allocation, sequential</h2>
    {make_curve_svg(rets) if rets else '<div class="empty">No closed trades to plot.</div>'}
    <div style="text-align:right; color:var(--muted); font-size:11px; margin-top:8px;">
      Final: ₩{final_cash:,.0f} ({total_pct:+.1f}%)
    </div>
  </div>

  <div class="card">
    <h2>Open Positions ({len(open_pos)})</h2>
    <table>
      <thead>
        <tr>
          <th>ID</th><th>Symbol</th><th>Buy Date</th>
          <th class="num">Buy</th><th class="num">Shares</th>
          <th class="num">Current</th><th class="num">Unrealized</th>
          <th class="num">TP</th><th>Status</th>
        </tr>
      </thead>
      <tbody>{open_rows}
      </tbody>
    </table>
    {f'<div style="margin-top:12px; color:var(--muted); font-size:12px;">Open unrealized total (USD): ${open_unrealized_total:+,.2f}</div>' if open_pos else ''}
  </div>

  <div class="card">
    <h2>Closed History ({len(closed_pos)})</h2>
    <table>
      <thead>
        <tr>
          <th>ID</th><th>Symbol</th><th>Buy</th><th>Sell</th>
          <th class="num">Buy $</th><th class="num">Sell $</th>
          <th class="num">P&L %</th><th class="num">P&L KRW</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>{closed_rows}
      </tbody>
    </table>
  </div>

  <div class="card">
    <h2>Missed Signals (signal fired but no trade recorded)</h2>
    <div class="sub" style="margin-bottom:12px;">
      Signals from <code>reports/*.html</code> that have no corresponding buy in positions.json.
      Useful for paper-tracking opportunities you skipped.
    </div>
    <table>
      <thead>
        <tr><th>Signal Date</th><th>Symbol</th><th class="num">Latest Close</th></tr>
      </thead>
      <tbody>{missed_rows}
      </tbody>
    </table>
  </div>

  <footer>
    Auto-generated from <code>data/positions.json</code>.
    Use <code>scripts/live/positions.py</code> to record buys/sells.
    KRW values use FX 1 USD = 1,400 KRW unless overridden per trade.
  </footer>
</div>
</body>
</html>
"""
    out = REPORTS / "_positions.html"
    out.write_text(body, encoding="utf-8")
    print(f"Wrote: {out}")
    print(f"  Open: {len(open_pos)}, Closed: {len(closed_pos)}")
    if closed_pos:
        print(f"  Win rate: {wr*100:.1f}%, mean {avg*100:+.2f}%, ₩1M → ₩{final_cash:,.0f}")


if __name__ == "__main__":
    main()
