"""
Daily breakout signal scanner + HTML report generator.

Reads:
  data/daily_cache/{TICKER}.csv  (from fetch_universe.py)
  config/current_rule.json       (from quarterly_retrain.py)

Outputs:
  reports/YYYY-MM-DD.html         (one report per day, pretty HTML)
  reports/index.html              (auto-updated index)

For a specific historical date, use --as-of YYYY-MM-DD.
"""
import json
import argparse
import html
from pathlib import Path
import pandas as pd
import numpy as np

REPO = Path(__file__).resolve().parents[2]
CACHE = REPO / "data" / "daily_cache"
CONFIG = REPO / "config" / "current_rule.json"
REPORTS = REPO / "reports"
REPORTS.mkdir(exist_ok=True)

MIN_AVG_VOL = 10_000


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
h1 { margin: 0 0 6px; font-size: 26px; font-weight: 700; letter-spacing: -0.01em; }
.sub { color: var(--muted); font-size: 13px; }
.nav { margin-top: 14px; }
.nav a {
  display: inline-block; margin-right: 12px;
  color: var(--accent); text-decoration: none; font-size: 13px;
}
.nav a:hover { text-decoration: underline; }

.card {
  background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
  padding: 20px; margin-bottom: 20px;
}
.card h2 { margin: 0 0 14px; font-size: 16px; font-weight: 600; color: var(--text); }
.card .label { color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em; }

.kv { display: grid; grid-template-columns: 200px 1fr; gap: 8px 16px; font-size: 14px; }
.kv .k { color: var(--muted); }
.kv .v { color: var(--text); font-variant-numeric: tabular-nums; }

.banner {
  border-radius: 10px; padding: 16px 20px; margin-bottom: 20px;
  display: flex; align-items: center; gap: 14px;
}
.banner.empty { background: rgba(139, 147, 167, 0.1); border: 1px solid var(--border); }
.banner.signal { background: rgba(31, 191, 117, 0.08); border: 1px solid rgba(31, 191, 117, 0.4); }
.banner .num { font-size: 30px; font-weight: 700; }
.banner.signal .num { color: var(--green); }
.banner.empty .num { color: var(--muted); }
.banner .text { font-size: 14px; }
.banner .text strong { color: var(--text); }

table.signals { width: 100%; border-collapse: collapse; margin-top: 8px; }
table.signals th, table.signals td {
  padding: 10px 12px; text-align: left;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
}
table.signals th {
  background: var(--panel-2); color: var(--muted);
  font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; font-size: 11px;
}
table.signals td.num { text-align: right; font-variant-numeric: tabular-nums; }
table.signals td.sym {
  font-weight: 700; color: var(--text);
  font-family: "SF Mono", Menlo, Consolas, monospace;
}
table.signals .target { color: var(--green); font-weight: 600; }

.steps { padding-left: 20px; margin: 8px 0; }
.steps li { padding: 4px 0; color: var(--text); font-size: 13px; }

footer {
  margin-top: 40px; padding-top: 20px; border-top: 1px solid var(--border);
  color: var(--muted); font-size: 11px; line-height: 1.6;
}
.tag {
  display: inline-block; padding: 2px 8px;
  background: var(--panel-2); border: 1px solid var(--border);
  border-radius: 4px; font-size: 11px; color: var(--muted);
}
"""


def parse_csv(path):
    try:
        df = pd.read_csv(path, parse_dates=["Date"])
    except Exception:
        return None
    if df.empty or len(df) < 35:
        return None
    return df.sort_values("Date").reset_index(drop=True)


def detect_signals(rule, as_of):
    # Skip-trading marker (Option A: no candidate passed strict filter)
    if rule.get("skip_trading"):
        return []
    cons_d = rule["cons_d"]
    entry_lo = rule["entry_lo"]
    entry_hi = rule["entry_hi"]
    sub_level = rule.get("sub_level", 1.0)  # consolidation top (default 1.0 for backward compat)

    csv_files = sorted(CACHE.glob("*.csv"))
    csv_files = [f for f in csv_files if not f.name.startswith("_")]
    signals = []

    for f in csv_files:
        sym = f.stem
        df = parse_csv(f)
        if df is None:
            continue
        df = df[df["Date"] <= as_of].reset_index(drop=True)
        if len(df) < cons_d + 2:
            continue

        last = df.iloc[-1]
        if last["Date"] != as_of:
            if (as_of - last["Date"]).days > 4:
                continue
        prev = df.iloc[-2] if len(df) >= 2 else None
        last_close = float(last["Close"])
        prev_close = float(prev["Close"]) if prev is not None else None

        if not (entry_lo <= last_close < entry_hi):
            continue
        if prev_close is None or prev_close >= entry_lo:
            continue

        prior = df["Close"].values[-(cons_d + 1):-1]
        if len(prior) < cons_d:
            continue
        if not (prior < sub_level).all() or not (prior > 0).all():
            continue
        if df["Volume"].values[-(cons_d + 1):-1].mean() < MIN_AVG_VOL:
            continue

        signals.append({
            "symbol": sym,
            "signal_date": last["Date"].strftime("%Y-%m-%d"),
            "today_close": last_close,
            "prev_close": prev_close,
            "consolidation_avg": float(prior.mean()),
            "consolidation_avg_vol": float(df["Volume"].values[-(cons_d + 1):-1].mean()),
        })

    return signals


def render_html(rule, as_of, signals, out_path):
    target_ratio = rule["tp_ratio"]
    hold_d = rule["hold_d"]
    target_pct = (target_ratio - 1) * 100

    if signals:
        signal_rows = "\n".join(
            f"""
        <tr>
          <td class="sym">{html.escape(s['symbol'])}</td>
          <td class="num">${s['today_close']:.2f}</td>
          <td class="num">${s['prev_close']:.2f}</td>
          <td class="num">${s['consolidation_avg']:.2f}</td>
          <td class="num target">${s['today_close'] * target_ratio:.2f}</td>
        </tr>"""
            for s in signals
        )
        signal_section = f"""
    <div class="banner signal">
      <div class="num">{len(signals)}</div>
      <div class="text"><strong>NEW SIGNAL{('S' if len(signals) > 1 else '')} TODAY</strong><br>
        Buy at next-day open, take profit at +{target_pct:.0f}%, force-exit after {hold_d} trading days.
      </div>
    </div>

    <div class="card">
      <h2>Signals</h2>
      <table class="signals">
        <thead>
          <tr>
            <th>Symbol</th>
            <th class="num">Today Close</th>
            <th class="num">Prev Close</th>
            <th class="num">Cons Avg</th>
            <th class="num">TP Target</th>
          </tr>
        </thead>
        <tbody>{signal_rows}
        </tbody>
      </table>
    </div>

    <div class="card">
      <h2>Trade Plan (per signal)</h2>
      <ol class="steps">
        <li>Place market <strong>BUY</strong> at the OPEN of the next trading day.</li>
        <li>Immediately place a limit <strong>SELL</strong> at the TP target price (entry × {target_ratio:.2f}).</li>
        <li>If TP not hit within {hold_d} trading days, force-sell at close on day {hold_d}.</li>
        <li>Recommended position size: <strong>25% of cash</strong> per signal (max 4 simultaneous).</li>
      </ol>
    </div>
"""
    else:
        signal_section = """
    <div class="banner empty">
      <div class="num">0</div>
      <div class="text"><strong>No new breakout signals today.</strong><br>
        Universe scanned, no tickers matched the active rule.
      </div>
    </div>
"""

    train_period = rule.get("trained_on_period", "?")
    train_n = rule.get("train_n", "?")
    train_win = rule.get("train_win_rate", 0) or 0
    train_mean = rule.get("train_mean_return", 0) or 0
    valid_until = rule.get("valid_until", "?")

    body = f"""
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Breakout Daily Report — {as_of.strftime('%Y-%m-%d')}</title>
  <style>{CSS}</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Breakout Daily Report — {as_of.strftime('%Y-%m-%d')}</h1>
    <div class="sub">Generated {pd.Timestamp.now().isoformat()}</div>
    <div class="nav">
      <a href="./index.html">← All reports</a>
      <a href="https://github.com/stoneidev/pennysniper-validation">GitHub repo</a>
    </div>
  </header>

  <div class="card">
    <h2>Active Rule</h2>
    <div class="kv">
      <div class="k">Consolidation</div>
      <div class="v">prior <strong>{rule['cons_d']} trading days</strong> all closed below $1.00</div>
      <div class="k">Entry range</div>
      <div class="v">today close in <strong>[${rule['entry_lo']:.2f}, ${rule['entry_hi']:.2f})</strong></div>
      <div class="k">Take profit</div>
      <div class="v">entry × <strong>{rule['tp_ratio']:.2f}</strong> ( +{target_pct:.0f}% )</div>
      <div class="k">Max hold</div>
      <div class="v">{hold_d} trading days</div>
      <div class="k">Stop loss</div>
      <div class="v">none (per backtest finding)</div>
      <div class="k">Slippage</div>
      <div class="v">2% round-trip assumption</div>
    </div>
    <div style="margin-top:14px; font-size:12px; color: var(--muted);">
      <span class="tag">trained on {html.escape(train_period)}</span>
      <span class="tag">N = {train_n}</span>
      <span class="tag">train win {train_win*100:.1f}%</span>
      <span class="tag">train mean {train_mean*100:+.2f}%</span>
      <span class="tag">valid until {valid_until}</span>
    </div>
  </div>

{signal_section}

  <footer>
    Past performance does not guarantee future results. Slippage, taxes, and broker fees are not fully modeled.
    Paper-trade for 6+ months before deploying real capital. The rule is automatically re-trained every quarter
    using the prior 3 months of NASDAQ data.
  </footer>
</div>
</body>
</html>
"""
    out_path.write_text(body, encoding="utf-8")


def update_index():
    reports = sorted([r for r in REPORTS.glob("*.html") if r.name not in ("index.html",)], reverse=True)
    by_month = {}
    for r in reports:
        # filename: YYYY-MM-DD.html or _may_2025_summary.html, etc.
        stem = r.stem
        if stem.startswith("_"):
            continue
        try:
            d = pd.Timestamp(stem)
        except Exception:
            continue
        month = d.strftime("%Y-%m")
        by_month.setdefault(month, []).append((d, r.name))

    # Special files (summaries)
    summaries = sorted([r for r in REPORTS.glob("_*.html")])

    cards = []
    if summaries:
        rows = "\n".join(
            f'<li><a href="./{html.escape(s.name)}">{html.escape(s.stem.lstrip("_"))}</a></li>'
            for s in summaries
        )
        cards.append(f'<div class="card"><h2>Summaries</h2><ul class="steps">{rows}</ul></div>')

    for month in sorted(by_month.keys(), reverse=True):
        rows = "\n".join(
            f'<li><a href="./{html.escape(name)}">{d.strftime("%Y-%m-%d")} ({d.strftime("%a")})</a></li>'
            for d, name in sorted(by_month[month], reverse=True)
        )
        cards.append(f'<div class="card"><h2>{month}</h2><ul class="steps">{rows}</ul></div>')

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Breakout Daily Reports — Index</title>
  <style>{CSS}</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Breakout Daily Reports</h1>
    <div class="sub">{sum(len(v) for v in by_month.values())} daily reports + {len(summaries)} summary file(s)</div>
    <div class="nav">
      <a href="https://github.com/stoneidev/pennysniper-validation">GitHub repo</a>
    </div>
  </header>
{"".join(cards)}
  <footer>
    Auto-generated by <code>scripts/live/daily_report.py</code> after each daily scan.
  </footer>
</div>
</body>
</html>
"""
    (REPORTS / "index.html").write_text(body, encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", type=str, default=None)
    parser.add_argument("--rule-file", type=str, default=str(CONFIG))
    args = parser.parse_args()

    rule_path = Path(args.rule_file)
    if not rule_path.exists():
        print(f"ERROR: rule file {rule_path} missing.")
        return
    with open(rule_path) as f:
        rule = json.load(f)

    as_of = pd.Timestamp(args.as_of) if args.as_of else pd.Timestamp.now().normalize()

    print(f"Scan date: {as_of.date()}")
    print(f"Active rule: cons {rule['cons_d']}d / entry [${rule['entry_lo']:.2f}, ${rule['entry_hi']:.2f}) / "
          f"TP +{(rule['tp_ratio']-1)*100:.0f}% / hold {rule['hold_d']}d")

    signals = detect_signals(rule, as_of)
    print(f"Detected {len(signals)} signal(s)")

    out_path = REPORTS / f"{as_of.strftime('%Y-%m-%d')}.html"
    render_html(rule, as_of, signals, out_path)
    print(f"Wrote: {out_path}")

    update_index()
    print(f"Updated: {REPORTS / 'index.html'}")


if __name__ == "__main__":
    main()
