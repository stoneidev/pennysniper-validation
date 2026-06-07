"""
Wide-grid OOS validation with win-rate ≥ 80% selection rule.

Expansion vs previous long-term run:
  ENTRY_RANGES adds mania-zone bands ($1.5–$2, $2–$3, $3–$5)
  SUB_LEVELS adds higher consolidation tops ($1.5, $2.0)

Selection per month:
  1. Filter: win_rate ≥ 0.80 AND N ≥ 5
  2. Tiebreaker: maximize  win_rate × sqrt(N)
  3. If no candidate passes, no trades that month.

Same monthly walk-forward as live system. Stooq archive 2018-2026.
"""
import time
import json
import html
from pathlib import Path
import pandas as pd
import numpy as np

REPO = Path(__file__).resolve().parents[2]
STOOQ_DIR = Path("/Users/stoni/Downloads/data/daily/us/nasdaq stocks")
OUT_DIR = REPO / "results" / "csv"
REPORTS = REPO / "reports"
DOCS = REPO / "docs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = pd.Timestamp("2017-09-01")
TEST_FIRST = pd.Timestamp("2018-01-01")
TEST_LAST = pd.Timestamp("2026-06-01")

SLIP = 0.02
MIN_AVG_VOL = 10_000
MIN_TRAIN_N = 5
MIN_WINRATE = 0.80

# Wide grid
SUB_LEVELS = [1.0, 1.5, 2.0]
ENTRY_RANGES = [
    # original (low zone)
    (1.05, 1.15, "$1.05-$1.15"),
    (1.05, 1.20, "$1.05-$1.20"),
    (1.10, 1.30, "$1.10-$1.30"),
    (1.20, 1.50, "$1.20-$1.50"),
    # mid zone
    (1.50, 1.80, "$1.50-$1.80"),
    (1.50, 2.00, "$1.50-$2.00"),
    (2.00, 2.50, "$2.00-$2.50"),
    (2.00, 3.00, "$2.00-$3.00"),
    # higher zone
    (3.00, 4.00, "$3.00-$4.00"),
    (3.00, 5.00, "$3.00-$5.00"),
]
CONS_DAYS_LIST = [30, 45, 60]
TP_LEVELS = [1.10, 1.15, 1.20, 1.30, 1.50]
HOLDS = [30, 60, 90]

EXCLUDE_SUFFIX = ("W", "R", "U", "Z")


def is_excluded(s):
    if s.endswith(EXCLUDE_SUFFIX):
        return True
    if len(s) > 4 and s[-3:].startswith("PR"):
        return True
    return False


def parse_stooq(path):
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    if df.empty or "<DATE>" not in df.columns:
        return None
    df = df.rename(columns={
        "<DATE>": "date", "<OPEN>": "Open", "<HIGH>": "High",
        "<LOW>": "Low", "<CLOSE>": "Close", "<VOL>": "Volume",
    })
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
    df = df[df["date"] >= START_DATE].dropna(subset=["Open", "High", "Low", "Close"])
    if len(df) < 100:
        return None
    return df.sort_values("date").reset_index(drop=True)


def find_events(df, sym, cons_d, sub_level, lo, hi):
    """Find events where:
       - prior cons_d closes < sub_level (and > 0)
       - today close in [lo, hi)
       - prev close < lo (= today is first breakout)
       - cons-period avg volume >= MIN_AVG_VOL
    """
    if len(df) < cons_d + 5:
        return []
    c = df["Close"].values
    o = df["Open"].values
    h = df["High"].values
    v = df["Volume"].values
    dates = df["date"].values
    rows = []
    for i in range(cons_d, len(c) - 1):
        prior = c[i - cons_d : i]
        if not (prior < sub_level).all() or not (prior > 0).all():
            continue
        if v[i - cons_d : i].mean() < MIN_AVG_VOL:
            continue
        if not (lo <= c[i] < hi):
            continue
        if i > 0 and c[i - 1] >= lo:
            continue
        if i + 1 >= len(c):
            continue
        entry = o[i + 1]
        if entry <= 0:
            continue
        rows.append({
            "symbol": sym,
            "date": pd.Timestamp(dates[i]),
            "entry": float(entry),
            "future_h": h[i + 1:].copy(),
            "future_c": c[i + 1:].copy(),
        })
    return rows


def simulate(events, tp_ratio, max_hold):
    rets = []
    for ev in events:
        entry = ev["entry"]
        tp_price = entry * tp_ratio
        n = min(max_hold, len(ev["future_h"]))
        if n == 0:
            continue
        ret = None
        tp_hit = False
        for j in range(n):
            if ev["future_h"][j] >= tp_price:
                ret = tp_ratio - 1.0 - SLIP
                tp_hit = True
                break
        if ret is None:
            ret = float(ev["future_c"][n - 1]) / entry - 1.0 - SLIP
        rets.append({"symbol": ev["symbol"], "date": ev["date"],
                     "ret": ret, "tp_hit": tp_hit})
    return rets


def main():
    print("Loading Stooq archive...")
    csv_files = []
    for d in STOOQ_DIR.iterdir():
        if d.is_dir():
            csv_files.extend(d.glob("*.txt"))
    print(f"  {len(csv_files)} files")

    print("Pre-computing events for all (cons, sub_level, entry_range) combos...")
    events_by_key = {}
    t0 = time.time()
    n_loaded = 0
    for f in csv_files:
        sym = f.stem.upper().replace(".US", "")
        if is_excluded(sym):
            continue
        df = parse_stooq(f)
        if df is None:
            continue
        n_loaded += 1
        for cd in CONS_DAYS_LIST:
            for sub in SUB_LEVELS:
                for lo, hi, label in ENTRY_RANGES:
                    if lo < sub:  # entry must be above consolidation top
                        continue
                    if hi > 5.0:  # cap upper bound
                        continue
                    evs = find_events(df, sym, cd, sub, lo, hi)
                    if evs:
                        events_by_key.setdefault((cd, sub, label), []).extend(evs)
    print(f"  {n_loaded} stocks in {time.time()-t0:.0f}s")
    n_combos = len(events_by_key)
    n_events = sum(len(v) for v in events_by_key.values())
    print(f"  {n_combos} (cons, sub, entry) combos, {n_events} total events")

    # Monthly windows
    months = pd.date_range(TEST_FIRST, TEST_LAST + pd.Timedelta(days=31), freq="MS").tolist()
    print(f"\nMonthly OOS windows: {len(months)-1}")

    log_rows = []
    all_oos = []

    for i in range(len(months) - 1):
        test_start = months[i]
        test_end = months[i + 1]
        train_start = test_start - pd.DateOffset(months=3)
        train_end = test_start

        # Grid search on train, applying selection rule
        candidates = []
        for (cd, sub, label), all_events in events_by_key.items():
            train_evs = [e for e in all_events if train_start <= e["date"] < train_end]
            if len(train_evs) < MIN_TRAIN_N:
                continue
            for tp in TP_LEVELS:
                for hold in HOLDS:
                    sims = simulate(train_evs, tp, hold)
                    if len(sims) < MIN_TRAIN_N:
                        continue
                    rets = np.array([s["ret"] for s in sims])
                    wr = (rets > 0).mean()
                    if wr < MIN_WINRATE:
                        continue
                    n = len(rets)
                    score = wr * np.sqrt(n)
                    candidates.append({
                        "cd": cd, "sub": sub, "label": label,
                        "tp": tp, "hold": hold,
                        "n": n, "win": wr, "mean": rets.mean(),
                        "p10": float(np.percentile(rets, 10)),
                        "score": score,
                    })

        if not candidates:
            log_rows.append({
                "month": test_start.strftime("%Y-%m"),
                "rule": "—", "sub_level": None,
                "train_n": 0, "train_win": None,
                "test_n": 0, "test_win": None, "test_mean": None, "test_sum": 0,
            })
            continue

        best = max(candidates, key=lambda x: x["score"])
        rule_str = (f"{best['cd']}d/sub${best['sub']:.1f}/{best['label']}/"
                    f"+{(best['tp']-1)*100:.0f}%/{best['hold']}d")

        # Apply to test month
        test_evs = [e for e in events_by_key.get((best["cd"], best["sub"], best["label"]), [])
                    if test_start <= e["date"] < test_end]
        sims = simulate(test_evs, best["tp"], best["hold"])
        for s in sims:
            all_oos.append({
                "month": test_start.strftime("%Y-%m"),
                "symbol": s["symbol"],
                "date": s["date"].strftime("%Y-%m-%d"),
                "rule": rule_str,
                "ret": s["ret"],
                "tp_hit": s["tp_hit"],
            })
        rets = np.array([s["ret"] for s in sims]) if sims else np.array([])
        log_rows.append({
            "month": test_start.strftime("%Y-%m"),
            "rule": rule_str,
            "sub_level": best["sub"],
            "train_n": best["n"],
            "train_win": best["win"],
            "test_n": len(rets),
            "test_win": float((rets > 0).mean()) if len(rets) else None,
            "test_mean": float(rets.mean()) if len(rets) else None,
            "test_sum": float(rets.sum()),
        })

    log_df = pd.DataFrame(log_rows)
    log_df.to_csv(OUT_DIR / "widegrid_oos_log.csv", index=False)
    trades_df = pd.DataFrame(all_oos)
    trades_df.to_csv(OUT_DIR / "widegrid_oos_trades.csv", index=False)

    # ===== Aggregate =====
    if not all_oos:
        print("No OOS trades passed the selection criteria!")
        return

    rets_arr = np.array([t["ret"] for t in all_oos])
    print("\n" + "=" * 80)
    print("WIDE-GRID + WIN_RATE>=80% AGGREGATE (2018-01 to 2026-06)")
    print("=" * 80)
    print(f"  Total OOS trades: {len(rets_arr)}")
    print(f"  Win rate:         {(rets_arr > 0).mean():.1%}")
    print(f"  Mean:             {rets_arr.mean()*100:+.2f}%")
    print(f"  Median:           {np.median(rets_arr)*100:+.2f}%")
    print(f"  p10:              {np.percentile(rets_arr, 10)*100:+.2f}%")
    print(f"  p90:              {np.percentile(rets_arr, 90)*100:+.2f}%")

    print("\n  ₩1M capital sim:")
    for alloc, name in [(1.0, "ALL_IN"), (0.25, "25%"), (0.10, "10%")]:
        cash = 1_000_000
        for r in rets_arr:
            pos = cash * alloc
            cash = cash - pos + pos * (1 + r)
        print(f"    {name:<10} → ₩{cash:>16,.0f} ({(cash/1_000_000-1)*100:+.1f}%)")

    # Per-year
    trades_df["year"] = pd.to_datetime(trades_df["date"]).dt.year
    print("\n  Per-year:")
    print(f"  {'year':<6} {'trades':>7} {'win%':>7} {'mean':>9} {'sum':>10} {'₩25%':>14}")
    for year in sorted(trades_df["year"].unique()):
        yr = trades_df[trades_df["year"] == year]
        rets = yr["ret"].values
        cash = 1_000_000
        for r in rets:
            pos = cash * 0.25
            cash = cash - pos + pos * (1 + r)
        print(f"  {year:<6} {len(rets):>7} {(rets>0).mean()*100:>6.1f}% "
              f"{rets.mean()*100:>+8.2f}% {rets.sum()*100:>+9.1f}% "
              f"₩{cash:>12,.0f}")

    # Sub-level usage
    print("\n  Sub-level distribution (which consolidation top was chosen):")
    sub_counts = log_df["sub_level"].value_counts(dropna=False).sort_index()
    for sub, count in sub_counts.items():
        print(f"    sub_level={sub}: {count} months")

    # ===== HTML =====
    cum_25 = 1_000_000
    capital_curve = [(pd.Timestamp("2017-12-31"), cum_25)]
    for t in sorted(all_oos, key=lambda x: x["date"]):
        pos = cum_25 * 0.25
        cum_25 = cum_25 - pos + pos * (1 + t["ret"])
        capital_curve.append((pd.Timestamp(t["date"]), cum_25))

    width, height, padding = 1000, 220, 30
    if len(capital_curve) > 1:
        xs = [(p[0] - capital_curve[0][0]).days for p in capital_curve]
        ys = [p[1] for p in capital_curve]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        if ymax == ymin:
            ymax += 1
        def sx(x): return padding + (x - xmin) / (xmax - xmin) * (width - 2*padding)
        def sy(y): return height - padding - (y - ymin) / (ymax - ymin) * (height - 2*padding)
        path = " ".join(f"{'M' if i==0 else 'L'} {sx(x):.1f} {sy(y):.1f}"
                        for i, (x, y) in enumerate(zip(xs, ys)))
        init_y = sy(1_000_000)
        svg_curve = f"""
<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none" style="width:100%;height:240px">
  <line x1="{padding}" y1="{init_y}" x2="{width-padding}" y2="{init_y}"
        stroke="#2a2f3a" stroke-dasharray="4,4"/>
  <path d="{path}" stroke="#1fbf75" stroke-width="2" fill="none"/>
  <text x="{padding}" y="18" fill="#e8e8ea" font-size="12" font-weight="600">
    ₩1M start → ₩{cum_25:,.0f} ({(cum_25/1_000_000-1)*100:+.0f}%)
  </text>
</svg>
"""
    else:
        svg_curve = ""

    years_html = "<tr><th>Year</th><th>Trades</th><th>Win%</th><th>Mean</th><th>Sum</th><th>₩1M (25%)</th></tr>"
    for year in sorted(trades_df["year"].unique()):
        yr = trades_df[trades_df["year"] == year]
        rets = yr["ret"].values
        cash = 1_000_000
        for r in rets:
            pos = cash * 0.25
            cash = cash - pos + pos * (1 + r)
        cls = "win" if rets.mean() > 0 else "lose"
        years_html += f"""<tr>
          <td>{year}</td>
          <td class="num">{len(rets)}</td>
          <td class="num">{(rets>0).mean()*100:.0f}%</td>
          <td class="num {cls}">{rets.mean()*100:+.2f}%</td>
          <td class="num {cls}">{rets.sum()*100:+.1f}%</td>
          <td class="num">₩{cash:,.0f}</td>
        </tr>"""

    log_html = "<tr><th>Month</th><th>Chosen Rule</th><th>Train N</th><th>Train Win%</th><th>Test N</th><th>Test Mean</th></tr>"
    for _, r in log_df.iterrows():
        ts_mean_s = f"{r['test_mean']*100:+.1f}%" if r["test_mean"] is not None and not pd.isna(r["test_mean"]) else "—"
        cls = ""
        if r["test_mean"] is not None and not pd.isna(r["test_mean"]):
            cls = "win" if r["test_mean"] > 0 else "lose"
        tr_win = f"{r['train_win']*100:.0f}%" if r["train_win"] is not None and not pd.isna(r["train_win"]) else "—"
        log_html += f"""<tr>
          <td>{r['month']}</td>
          <td><code>{html.escape(r['rule'])}</code></td>
          <td class="num">{int(r['train_n']) if r['train_n'] else 0}</td>
          <td class="num">{tr_win}</td>
          <td class="num">{int(r['test_n'])}</td>
          <td class="num {cls}">{ts_mean_s}</td>
        </tr>"""

    css = """
:root{--bg:#0f1115;--panel:#181b22;--panel-2:#1f232c;--border:#2a2f3a;--text:#e8e8ea;--muted:#8b93a7;--accent:#4f8cff;--green:#1fbf75;--red:#ff5b6c;}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.5}
.container{max-width:1080px;margin:0 auto;padding:32px 20px 80px}
header{padding-bottom:24px;border-bottom:1px solid var(--border);margin-bottom:28px}
h1{margin:0 0 6px;font-size:26px;font-weight:700}h2{margin:0 0 14px;font-size:16px;font-weight:600}
.sub{color:var(--muted);font-size:13px}.nav{margin-top:14px}.nav a{color:var(--accent);text-decoration:none;font-size:13px;margin-right:12px}
.card{background:var(--panel);border:1px solid var(--border);border-radius:10px;padding:20px;margin-bottom:20px}
.stats-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
.stat{background:var(--panel-2);border-radius:8px;padding:14px}
.stat .label{font-size:11px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.stat .value{font-size:22px;font-weight:700;margin-top:4px;font-variant-numeric:tabular-nums}
.stat .value.green{color:var(--green)}.stat .value.red{color:var(--red)}
table{width:100%;border-collapse:collapse}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--border);font-size:13px}
th{background:var(--panel-2);color:var(--muted);text-transform:uppercase;letter-spacing:.05em;font-size:11px;font-weight:600}
td.num{text-align:right;font-variant-numeric:tabular-nums}
td.win{color:var(--green);font-weight:600}td.lose{color:var(--red);font-weight:600}
footer{margin-top:40px;padding-top:20px;border-top:1px solid var(--border);color:var(--muted);font-size:11px}
.note{padding:12px 16px;background:rgba(245,179,66,.08);border-left:3px solid #f5b342;border-radius:4px;font-size:13px;margin:12px 0}
"""

    n = len(rets_arr)
    wr = (rets_arr > 0).mean()
    mean = rets_arr.mean()
    cum_pct = (cum_25 / 1_000_000 - 1) * 100

    body = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Wide-grid OOS — win_rate ≥80%</title><style>{css}</style></head>
<body><div class="container">
  <header>
    <h1>Wide-grid OOS — Win Rate ≥80% Filter</h1>
    <div class="sub">Monthly walk-forward 2018-01~2026-06. Wide entry-range grid (\$1.05~\$5).
    Selection rule: win_rate≥0.80, N≥{MIN_TRAIN_N}, then maximize win_rate × √N.</div>
    <div class="nav">
      <a href="./index.html">← All reports</a>
      <a href="https://github.com/stoneidev/pennysniper-validation">GitHub</a>
    </div>
  </header>

  <div class="card">
    <h2>Aggregate Stats</h2>
    <div class="stats-grid">
      <div class="stat"><div class="label">Total OOS trades</div><div class="value">{n}</div></div>
      <div class="stat"><div class="label">Realized win rate</div><div class="value green">{wr*100:.1f}%</div></div>
      <div class="stat"><div class="label">Mean per trade</div><div class="value {('green' if mean>0 else 'red')}">{mean*100:+.2f}%</div></div>
      <div class="stat"><div class="label">₩1M (25% alloc)</div><div class="value {('green' if cum_pct>0 else 'red')}">₩{cum_25:,.0f}<br><span style="font-size:11px;color:var(--muted)">{cum_pct:+.0f}%</span></div></div>
    </div>
  </div>

  <div class="card">
    <h2>Capital Curve (₩1M, 25% alloc, sequential)</h2>
    {svg_curve}
  </div>

  <div class="card">
    <h2>Per-year</h2>
    <table>{years_html}</table>
  </div>

  <div class="card">
    <h2>Monthly Log</h2>
    <table>{log_html}</table>
  </div>

  <footer>
    Wide grid: 3 cons × 3 sub_levels × 10 entry_ranges × 5 TPs × 3 holds.
    Selection: win_rate ≥ 80% AND N ≥ 5; tiebreaker = win_rate × √N.
    Stooq archive — yfinance not used.
  </footer>
</div></body></html>
"""
    out_html = REPORTS / "_widegrid_oos.html"
    out_html.write_text(body, encoding="utf-8")
    print(f"\nWrote: {out_html}")

    # ===== Markdown =====
    md = []
    md.append("# Wide-grid OOS — win_rate ≥ 80% Filter\n")
    md.append(f"_Generated: {pd.Timestamp.now().isoformat()}_\n\n")
    md.append("## Selection Rule\n")
    md.append(f"- Filter: train win_rate ≥ {MIN_WINRATE*100:.0f}% AND N ≥ {MIN_TRAIN_N}\n")
    md.append("- Tiebreaker: maximize `win_rate × sqrt(N)`\n")
    md.append("- If no candidate passes → no trades that month\n\n")
    md.append("## Wide Grid\n")
    md.append(f"- Cons days: {CONS_DAYS_LIST}\n")
    md.append(f"- Sub-levels (consolidation top): {SUB_LEVELS}\n")
    md.append(f"- Entry ranges: {[r[2] for r in ENTRY_RANGES]}\n")
    md.append(f"- TP ratios: {TP_LEVELS}\n")
    md.append(f"- Holds: {HOLDS}\n\n")

    md.append("## Aggregate (8.5 years)\n")
    md.append("| Metric | Value |\n|---|---|\n")
    md.append(f"| Total OOS trades | {n} |\n")
    md.append(f"| Realized win rate | {wr*100:.1f}% |\n")
    md.append(f"| Mean per trade | {mean*100:+.2f}% |\n")
    md.append(f"| Median | {np.median(rets_arr)*100:+.2f}% |\n")
    md.append(f"| p10 | {np.percentile(rets_arr,10)*100:+.2f}% |\n")
    md.append(f"| p90 | {np.percentile(rets_arr,90)*100:+.2f}% |\n")
    md.append(f"| ₩1M (25% alloc) | ₩{cum_25:,.0f} ({cum_pct:+.0f}%) |\n\n")

    md.append("## Per-year\n")
    md.append("| Year | Trades | Win% | Mean | Sum | ₩1M (25%) |\n|---|---|---|---|---|---|\n")
    for year in sorted(trades_df["year"].unique()):
        yr = trades_df[trades_df["year"] == year]
        rets = yr["ret"].values
        cash = 1_000_000
        for r in rets:
            pos = cash * 0.25
            cash = cash - pos + pos * (1 + r)
        md.append(f"| {year} | {len(rets)} | {(rets>0).mean()*100:.0f}% | "
                  f"{rets.mean()*100:+.2f}% | {rets.sum()*100:+.1f}% | ₩{cash:,.0f} |\n")
    md.append("\n## Monthly Log\n")
    md.append("| Month | Rule | Train N | Train Win% | Test N | Test Mean |\n|---|---|---|---|---|---|\n")
    for _, r in log_df.iterrows():
        ts_m = f"{r['test_mean']*100:+.1f}%" if r["test_mean"] is not None and not pd.isna(r["test_mean"]) else "—"
        tr_w = f"{r['train_win']*100:.0f}%" if r["train_win"] is not None and not pd.isna(r["train_win"]) else "—"
        md.append(f"| {r['month']} | `{r['rule']}` | "
                  f"{int(r['train_n']) if r['train_n'] else 0} | {tr_w} | "
                  f"{int(r['test_n'])} | {ts_m} |\n")
    md.append("\n## Files\n")
    md.append("- `results/csv/widegrid_oos_log.csv`\n")
    md.append("- `results/csv/widegrid_oos_trades.csv`\n")
    md.append("- `reports/_widegrid_oos.html`\n")
    md.append("- `scripts/breakout/breakout_21_widegrid_winrate.py`\n")

    out_md = DOCS / "widegrid_oos_findings.md"
    out_md.write_text("".join(md), encoding="utf-8")
    print(f"Wrote: {out_md}")


if __name__ == "__main__":
    main()
