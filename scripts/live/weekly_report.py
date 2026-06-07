"""
Weekly insight report.

Generated every Saturday by the weekly_report.yml workflow.

Aggregates the past ISO week:
  - All breakout signals fired
  - Realized outcomes (TP hit / current state for in-flight)
  - Capital curve simulation
  - Active rule and rule-change events
  - Universe-wide volatility / regime tag
  - Cumulative stats since system start

Output: reports/_weekly_YYYY-WW.html (e.g. _weekly_2026-W23.html)
"""
import json
import re
import html
from pathlib import Path
import pandas as pd
import numpy as np

REPO = Path(__file__).resolve().parents[2]
REPORTS = REPO / "reports"
CACHE = REPO / "data" / "daily_cache"
CONFIG = REPO / "config" / "current_rule.json"
SLIP = 0.02

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
h1 { margin:0 0 6px; font-size:28px; font-weight:700; letter-spacing:-0.01em; }
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
.stat .value.muted { color:var(--muted); }
.stat .small { font-size:11px; color:var(--muted); margin-top:4px; }

table { width:100%; border-collapse:collapse; }
th, td { padding:10px 12px; text-align:left; border-bottom:1px solid var(--border); font-size:13px; }
th { background:var(--panel-2); color:var(--muted); text-transform:uppercase; letter-spacing:0.05em; font-size:11px; font-weight:600; }
td.num { text-align:right; font-variant-numeric:tabular-nums; }
td.sym { font-weight:700; font-family:"SF Mono",Menlo,Consolas,monospace; }
td.win { color:var(--green); font-weight:600; }
td.lose { color:var(--red); font-weight:600; }

.tag { display:inline-block; padding:2px 8px; background:var(--panel-2); border:1px solid var(--border); border-radius:4px; font-size:11px; color:var(--muted); margin-right:4px; }
.kv { display:grid; grid-template-columns:200px 1fr; gap:8px 16px; font-size:14px; }
.kv .k { color:var(--muted); }
.note { padding:12px 16px; background:rgba(245,179,66,0.08); border-left:3px solid var(--yellow); border-radius:4px; font-size:13px; margin:12px 0; }
.callout { padding:14px 16px; border-radius:8px; margin:12px 0; font-size:13px; }
.callout.pos { background:rgba(31,191,117,0.08); border-left:3px solid var(--green); }
.callout.neg { background:rgba(255,91,108,0.08); border-left:3px solid var(--red); }
.callout.neut { background:rgba(139,147,167,0.08); border-left:3px solid var(--muted); }

footer { margin-top:40px; padding-top:20px; border-top:1px solid var(--border); color:var(--muted); font-size:11px; line-height:1.6; }

.pill {
  display:inline-block; padding:4px 10px; border-radius:999px;
  font-size:12px; font-weight:600; margin-right:6px;
}
.pill.green { background:rgba(31,191,117,0.15); color:var(--green); }
.pill.red { background:rgba(255,91,108,0.15); color:var(--red); }
.pill.yellow { background:rgba(245,179,66,0.15); color:var(--yellow); }
.pill.muted { background:rgba(139,147,167,0.15); color:var(--muted); }
"""


def parse_signals_from_html(path):
    text = path.read_text(encoding="utf-8")
    rows = re.findall(
        r'<td class="sym">([A-Z]+)</td>\s*'
        r'<td class="num">\$([\d.]+)</td>\s*'
        r'<td class="num">\$([\d.]+)</td>\s*'
        r'<td class="num">\$([\d.]+)</td>\s*'
        r'<td class="num target">\$([\d.]+)</td>',
        text,
    )
    out = []
    for sym, today, prev, cons, target in rows:
        out.append({
            "symbol": sym,
            "today_close": float(today),
            "prev_close": float(prev),
            "consolidation_avg": float(cons),
            "tp_target": float(target),
        })
    return out


def resolve_outcome(symbol, signal_date, tp_target, tp_ratio, hold_d):
    """Look up actual price action after the signal."""
    csv = CACHE / f"{symbol}.csv"
    if not csv.exists():
        return None
    df = pd.read_csv(csv, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
    sig_date = pd.Timestamp(signal_date)
    idx = df.index[df["Date"] == sig_date]
    if len(idx) == 0:
        return None
    sig_idx = int(idx[0])
    if sig_idx + 1 >= len(df):
        return {"in_flight": True, "entry": None, "current": None,
                "tp_hit": None, "days_held": None, "net_ret": None}

    entry_idx = sig_idx + 1
    entry = float(df["Open"].iloc[entry_idx])
    tp_price = entry * tp_ratio
    end_idx = min(entry_idx + hold_d, len(df) - 1)
    exit_idx = end_idx
    exit_price = float(df["Close"].iloc[end_idx])
    tp_hit = False
    for j in range(entry_idx, end_idx + 1):
        if float(df["High"].iloc[j]) >= tp_price:
            exit_price = tp_price
            exit_idx = j
            tp_hit = True
            break
    in_flight = (not tp_hit) and (exit_idx == end_idx) and ((end_idx - entry_idx + 1) < hold_d)
    days_held = exit_idx - entry_idx + 1
    gross = exit_price / entry - 1.0
    net = gross - SLIP
    current_close = float(df["Close"].iloc[-1])
    return {
        "in_flight": in_flight,
        "entry": entry,
        "entry_date": df["Date"].iloc[entry_idx].strftime("%Y-%m-%d"),
        "exit_date": df["Date"].iloc[exit_idx].strftime("%Y-%m-%d") if not in_flight else None,
        "exit_price": exit_price if not in_flight else None,
        "current_close": current_close,
        "tp_hit": tp_hit if not in_flight else None,
        "days_held": days_held if not in_flight else None,
        "net_ret": net if not in_flight else None,
    }


def regime_tag(week_signals_count, week_universe_volatility):
    """Crude market regime tag based on signal density + volatility."""
    if week_signals_count >= 5:
        return ("Active breakout regime", "green",
                "5+ breakouts in a week — penny universe is active.")
    if week_signals_count >= 2:
        return ("Normal regime", "yellow",
                "Some breakouts firing, market normalcy.")
    if week_signals_count == 1:
        return ("Quiet regime", "muted",
                "Few breakouts — universe consolidating.")
    return ("No breakouts this week", "muted",
            "Possible bear market or post-mania normalization. Patience.")


def estimate_universe_volatility():
    """Compute median 5-day volatility across cached universe (rough proxy)."""
    files = list(CACHE.glob("*.csv"))
    files = [f for f in files if not f.name.startswith("_")]
    vols = []
    for f in files[:200]:  # sample
        try:
            df = pd.read_csv(f, parse_dates=["Date"]).tail(20)
            if len(df) < 5:
                continue
            ret = df["Close"].pct_change().dropna()
            if len(ret) > 0:
                vols.append(ret.std() * np.sqrt(252))
        except Exception:
            continue
    if not vols:
        return None
    return float(np.median(vols))


def main():
    today = pd.Timestamp.now().normalize()
    iso_year, iso_week, _ = today.isocalendar()
    week_start = today - pd.Timedelta(days=today.weekday())  # Monday
    week_end = week_start + pd.Timedelta(days=6)

    print(f"Generating weekly report for ISO week {iso_year}-W{iso_week:02d}")
    print(f"  Week range: {week_start.date()} ~ {week_end.date()}")

    # Load active rule
    if not CONFIG.exists():
        print("ERROR: no current_rule.json — run monthly_retrain.py first")
        return
    with open(CONFIG) as f:
        rule = json.load(f)
    tp_ratio = rule["tp_ratio"]
    hold_d = rule["hold_d"]

    # Collect this week's signals from daily reports
    week_signals = []
    for d in pd.date_range(week_start, week_end, freq="D"):
        report = REPORTS / f"{d.strftime('%Y-%m-%d')}.html"
        if not report.exists():
            continue
        sigs = parse_signals_from_html(report)
        for s in sigs:
            s["signal_date"] = d.strftime("%Y-%m-%d")
            week_signals.append(s)

    # Resolve outcomes for each signal (look at actual prices after)
    resolved = []
    for s in week_signals:
        outcome = resolve_outcome(s["symbol"], s["signal_date"],
                                   s["tp_target"], tp_ratio, hold_d)
        s.update(outcome or {})
        resolved.append(s)

    # Cumulative stats: all signals across all daily reports
    all_signals = []
    for f in sorted(REPORTS.glob("[0-9]*.html")):
        # filename like 2025-05-08.html
        try:
            date = pd.Timestamp(f.stem)
        except Exception:
            continue
        sigs = parse_signals_from_html(f)
        for s in sigs:
            s["signal_date"] = f.stem
            all_signals.append(s)

    # Resolve cumulative
    cum_results = []
    for s in all_signals:
        out = resolve_outcome(s["symbol"], s["signal_date"],
                              s["tp_target"], tp_ratio, hold_d)
        if out is None:
            continue
        s.update(out)
        cum_results.append(s)

    # Stats
    closed = [r for r in cum_results if not r.get("in_flight", False) and r.get("net_ret") is not None]
    in_flight = [r for r in cum_results if r.get("in_flight")]

    if closed:
        rets = [r["net_ret"] for r in closed]
        cum_win = sum(1 for r in rets if r > 0) / len(rets)
        cum_tp = sum(1 for r in closed if r["tp_hit"]) / len(closed)
        cum_mean = sum(rets) / len(rets)
        cash = 1_000_000
        for r in rets:
            position = cash * 0.25
            cash = cash - position + position * (1 + r)
        cum_final = cash
        cum_total_pct = (cash / 1_000_000 - 1) * 100
    else:
        cum_win = cum_tp = cum_mean = 0
        cum_final = 1_000_000
        cum_total_pct = 0

    # This week's stats
    week_closed = [r for r in resolved if not r.get("in_flight", False) and r.get("net_ret") is not None]
    week_in_flight = [r for r in resolved if r.get("in_flight")]

    if week_closed:
        wrets = [r["net_ret"] for r in week_closed]
        week_win = sum(1 for r in wrets if r > 0) / len(wrets)
        week_tp = sum(1 for r in week_closed if r["tp_hit"]) / len(week_closed)
        week_mean = sum(wrets) / len(wrets)
    else:
        week_win = week_tp = week_mean = None

    # Regime
    uvol = estimate_universe_volatility()
    regime_name, regime_color, regime_desc = regime_tag(len(resolved), uvol)

    # Render
    week_rows = ""
    for r in sorted(resolved, key=lambda x: x["signal_date"]):
        sym = r["symbol"]
        if r.get("in_flight"):
            cls = ""
            ret_s = '<span class="tag">in flight</span>'
            entry_s = f"${r['entry']:.2f}" if r.get("entry") else "—"
            exit_s = "—"
            cur_s = f"${r['current_close']:.2f}" if r.get("current_close") else "—"
        elif r.get("net_ret") is None:
            cls = "muted"
            ret_s = "—"
            entry_s = exit_s = cur_s = "—"
        else:
            cls = "win" if r["net_ret"] > 0 else "lose"
            ret_s = f'{r["net_ret"]*100:+.1f}%'
            entry_s = f"${r['entry']:.2f}"
            exit_s = f"${r['exit_price']:.2f}" if r.get("exit_price") else "—"
            cur_s = f"${r['current_close']:.2f}"
        tp_s = "✓" if r.get("tp_hit") else ("—" if r.get("in_flight") else "✗")
        week_rows += f"""
        <tr>
          <td>{r['signal_date']}</td>
          <td class="sym">{html.escape(sym)}</td>
          <td class="num">${r['today_close']:.2f}</td>
          <td class="num">${r['tp_target']:.2f}</td>
          <td>{entry_s}</td>
          <td>{exit_s}</td>
          <td>{cur_s}</td>
          <td>{tp_s}</td>
          <td class="num {cls}">{ret_s}</td>
        </tr>"""

    if not week_rows:
        week_rows = '<tr><td colspan="9" style="text-align:center; color:var(--muted); padding:24px;">No signals this week.</td></tr>'

    rule_str = (f"{rule['cons_d']}d cons / "
                f"${rule['entry_lo']:.2f}-${rule['entry_hi']:.2f} / "
                f"TP +{(tp_ratio-1)*100:.0f}% / hold {hold_d}d")

    week_win_s = f"{week_win*100:.0f}%" if week_win is not None else "—"
    week_mean_s = f"{week_mean*100:+.1f}%" if week_mean is not None else "—"
    week_mean_cls = "green" if week_mean and week_mean > 0 else ("red" if week_mean and week_mean < 0 else "muted")

    # Insights
    insights = []
    if len(resolved) == 0:
        insights.append(("neut", "이번 주 시그널 없음. 시장이 조용한 상태."))
    if len(in_flight) > 0:
        insights.append(("neut", f"{len(in_flight)}건 holding 중 — 다음 주 결과에 따라 누적 통계 갱신 예정."))
    if week_win is not None and week_win >= 0.8:
        insights.append(("pos", f"이번 주 승률 {week_win*100:.0f}% — 룰이 현재 시장에 잘 맞는 시기."))
    elif week_win is not None and week_win <= 0.5:
        insights.append(("neg", f"이번 주 승률 {week_win*100:.0f}% — 시장 환경 변화 가능성. 다음 월간 재학습 주목."))

    if cum_win >= 0.7:
        insights.append(("pos", f"누적 승률 {cum_win*100:.0f}% — 룰의 장기 성과 견고."))
    if cum_total_pct > 50:
        insights.append(("pos", f"₩1M → ₩{cum_final:,.0f} ({cum_total_pct:+.1f}%) 누적. 인덱스 ETF 대비 우월."))

    insights.append(("neut", "Paper trading 6개월 이상 검증 후 실전 권장. 슬리피지 5-10%, 양도세 22% 미반영."))

    insights_html = ""
    for cls, txt in insights:
        insights_html += f'<div class="callout {cls}">{html.escape(txt)}</div>\n'

    body = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Weekly Report — {iso_year} W{iso_week:02d}</title>
  <style>{CSS}</style>
</head>
<body>
<div class="container">
  <header>
    <h1>Weekly Insight Report — {iso_year} W{iso_week:02d}</h1>
    <div class="sub">{week_start.strftime('%Y-%m-%d (%a)')} → {week_end.strftime('%Y-%m-%d (%a)')}</div>
    <div class="nav">
      <a href="./index.html">← All reports</a>
      <a href="https://github.com/stoneidev/pennysniper-validation">GitHub</a>
    </div>
  </header>

  <div class="card">
    <h2>Market Regime</h2>
    <span class="pill {regime_color}">{html.escape(regime_name)}</span>
    <span class="tag">universe vol ~ {uvol*100:.1f}%</span>
    <div style="margin-top:10px; color:var(--muted); font-size:13px;">{html.escape(regime_desc)}</div>
  </div>

  <div class="card">
    <h2>This Week</h2>
    <div class="stats-grid">
      <div class="stat"><div class="label">Signals fired</div>
        <div class="value">{len(resolved)}</div></div>
      <div class="stat"><div class="label">Closed (TP hit or expired)</div>
        <div class="value">{len(week_closed)}</div></div>
      <div class="stat"><div class="label">Win rate</div>
        <div class="value {week_mean_cls}">{week_win_s}</div></div>
      <div class="stat"><div class="label">Mean net return</div>
        <div class="value {week_mean_cls}">{week_mean_s}</div></div>
    </div>
  </div>

  <div class="card">
    <h2>Active Rule</h2>
    <div class="kv">
      <div class="k">Rule</div><div>{rule_str}</div>
      <div class="k">Trained on</div><div>{rule.get('trained_on_period', '?')}</div>
      <div class="k">Train win rate</div><div>{rule.get('train_win_rate', 0)*100:.1f}% (N={rule.get('train_n', '?')})</div>
      <div class="k">Valid until</div><div>{rule.get('valid_until', '?')}</div>
    </div>
  </div>

  <div class="card">
    <h2>Cumulative (since first daily report)</h2>
    <div class="stats-grid">
      <div class="stat"><div class="label">Total signals</div>
        <div class="value">{len(cum_results)}</div>
        <div class="small">{len(closed)} closed, {len(in_flight)} in flight</div></div>
      <div class="stat"><div class="label">Cumulative win rate</div>
        <div class="value green">{cum_win*100:.1f}%</div></div>
      <div class="stat"><div class="label">Mean net per trade</div>
        <div class="value {('green' if cum_mean > 0 else 'red')}">{cum_mean*100:+.2f}%</div></div>
      <div class="stat"><div class="label">₩1M (25% allocation)</div>
        <div class="value {('green' if cum_total_pct > 0 else 'red')}">₩{cum_final:,.0f}</div>
        <div class="small">{cum_total_pct:+.1f}%</div></div>
    </div>
  </div>

  <div class="card">
    <h2>This Week's Signals</h2>
    <table>
      <thead>
        <tr>
          <th>Signal Date</th>
          <th>Symbol</th>
          <th class="num">Today Close</th>
          <th class="num">TP Target</th>
          <th>Entry</th>
          <th>Exit</th>
          <th>Current</th>
          <th>TP</th>
          <th class="num">Net Return</th>
        </tr>
      </thead>
      <tbody>{week_rows}
      </tbody>
    </table>
  </div>

  <div class="card">
    <h2>Insights</h2>
    {insights_html}
  </div>

  <footer>
    Auto-generated weekly. Next report: next Saturday.
    Past performance ≠ future results. Slippage, taxes, broker fees not fully modeled.
  </footer>
</div>
</body>
</html>
"""
    out_path = REPORTS / f"_weekly_{iso_year}-W{iso_week:02d}.html"
    out_path.write_text(body, encoding="utf-8")
    print(f"\nWrote: {out_path}")
    print(f"  Week signals: {len(resolved)} ({len(week_closed)} closed, {len(week_in_flight)} in flight)")
    print(f"  Cumulative: {len(cum_results)} signals, win {cum_win*100:.1f}%, ₩1M → ₩{cum_final:,.0f}")


if __name__ == "__main__":
    main()
