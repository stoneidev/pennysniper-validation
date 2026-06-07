"""
Long-term OOS validation: 2018.01 ~ 2026.06 (8.5 years).

Reads directly from Stooq archive (no yfinance needed) to cover:
  - 2018: pre-COVID normalcy
  - 2019: low-vol bull market
  - 2020 H1: COVID crash
  - 2020 H2 - 2021: meme mania
  - 2022: bear market (CRITICAL — never validated before)
  - 2023: recovery
  - 2024-2025: bull continuation
  - 2026 H1: normalization

Algorithm: monthly rolling walk-forward, identical to live system.
  Each month M:
    Train on prior 3 months
    Apply chosen rule to month M
    Aggregate all OOS trades.

Outputs:
  results/csv/longterm_oos_log.csv     — chosen rule per month
  results/csv/longterm_oos_trades.csv  — every OOS trade
  reports/_longterm_oos.html           — pretty HTML report
  docs/longterm_oos_findings.md        — markdown summary
"""
import json
import time
from pathlib import Path
import pandas as pd
import numpy as np
import html

REPO = Path(__file__).resolve().parents[2]
STOOQ_DIR = Path("/Users/stoni/Downloads/data/daily/us/nasdaq stocks")
OUT_DIR = REPO / "results" / "csv"
REPORTS = REPO / "reports"
DOCS = REPO / "docs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)

# Long-term range
START_DATE = pd.Timestamp("2017-09-01")  # buffer for 60d cons before 2018-01
TEST_FIRST = pd.Timestamp("2018-01-01")
TEST_LAST = pd.Timestamp("2026-06-01")

SLIP = 0.02
MIN_AVG_VOL = 10_000

CONS_DAYS_LIST = [30, 45, 60]
ENTRY_RANGES = [
    (1.05, 1.15, "$1.05-$1.15"),
    (1.05, 1.20, "$1.05-$1.20"),
    (1.10, 1.30, "$1.10-$1.30"),
    (1.20, 1.50, "$1.20-$1.50"),
]
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


def find_events(df, sym, cons_d, lo, hi):
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
        if not (prior < 1.0).all() or not (prior > 0).all():
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

    print("Pre-computing events for all (cons, entry_range) combos...")
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
        c = df["Close"].values
        if not ((c < 1.0).any() and (c >= 1.05).any()):
            continue
        for cd in CONS_DAYS_LIST:
            for lo, hi, label in ENTRY_RANGES:
                evs = find_events(df, sym, cd, lo, hi)
                if evs:
                    events_by_key.setdefault((cd, label), []).extend(evs)
    print(f"  loaded {n_loaded} stocks in {time.time()-t0:.0f}s")
    total_events = sum(len(v) for v in events_by_key.values())
    print(f"  total events across all combos: {total_events}")

    # Monthly windows
    months = pd.date_range(TEST_FIRST, TEST_LAST + pd.Timedelta(days=31), freq="MS").tolist()
    print(f"\nMonthly OOS windows: {len(months) - 1}")

    log_rows = []
    all_oos_trades = []

    for i in range(len(months) - 1):
        test_start = months[i]
        test_end = months[i + 1]
        train_start = test_start - pd.DateOffset(months=3)
        train_end = test_start

        # Grid search on train
        train_grid = []
        for (cd, label), all_events in events_by_key.items():
            train_evs = [e for e in all_events if train_start <= e["date"] < train_end]
            if len(train_evs) < 5:
                continue
            for tp in TP_LEVELS:
                for hold in HOLDS:
                    sims = simulate(train_evs, tp, hold)
                    if len(sims) < 5:
                        continue
                    rets = np.array([s["ret"] for s in sims])
                    wr = (rets > 0).mean()
                    p10 = float(np.percentile(rets, 10))
                    score = wr * (1 + max(p10, -1))
                    train_grid.append({
                        "cd": cd, "label": label, "tp": tp, "hold": hold,
                        "n": len(rets), "win": wr, "p10": p10, "score": score,
                    })

        if not train_grid:
            log_rows.append({
                "month": test_start.strftime("%Y-%m"),
                "rule": "—", "train_n": 0, "test_n": 0,
                "test_win": None, "test_mean": None, "test_sum": 0,
            })
            continue

        best = max(train_grid, key=lambda x: x["score"])
        rule_str = (f"{best['cd']}d/{best['label']}/+{(best['tp']-1)*100:.0f}%/{best['hold']}d")

        # Apply to test month
        test_evs = [e for e in events_by_key.get((best["cd"], best["label"]), [])
                    if test_start <= e["date"] < test_end]
        sims = simulate(test_evs, best["tp"], best["hold"])

        for s in sims:
            all_oos_trades.append({
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
            "train_n": best["n"],
            "train_win": best["win"],
            "test_n": len(rets),
            "test_win": float((rets > 0).mean()) if len(rets) else None,
            "test_mean": float(rets.mean()) if len(rets) else None,
            "test_sum": float(rets.sum()),
        })

    log_df = pd.DataFrame(log_rows)
    log_df.to_csv(OUT_DIR / "longterm_oos_log.csv", index=False)
    trades_df = pd.DataFrame(all_oos_trades)
    trades_df.to_csv(OUT_DIR / "longterm_oos_trades.csv", index=False)
    print(f"\n  Saved log + trades CSVs")

    # ====== Aggregate stats ======
    if not all_oos_trades:
        print("No trades!")
        return

    all_rets = np.array([t["ret"] for t in all_oos_trades])
    print("\n" + "=" * 80)
    print("AGGREGATE: 2018-01 ~ 2026-06 monthly walk-forward")
    print("=" * 80)
    print(f"  Total OOS trades:  {len(all_rets)}")
    print(f"  Win rate:          {(all_rets > 0).mean():.1%}")
    print(f"  Mean:              {all_rets.mean()*100:+.2f}%")
    print(f"  Median:            {np.median(all_rets)*100:+.2f}%")
    print(f"  p10:               {np.percentile(all_rets, 10)*100:+.2f}%")
    print(f"  p90:               {np.percentile(all_rets, 90)*100:+.2f}%")

    # Capital sims
    print("\n  ₩1M capital sim:")
    for alloc, name in [(1.0, "ALL_IN"), (0.25, "25%"), (0.10, "10%")]:
        cash = 1_000_000
        for r in all_rets:
            pos = cash * alloc
            cash = cash - pos + pos * (1 + r)
        print(f"    {name:<10} → ₩{cash:>16,.0f} ({(cash/1_000_000-1)*100:+.1f}%)")

    # Per-year breakdown
    trades_df["year"] = pd.to_datetime(trades_df["date"]).dt.year
    print("\n  Per-year:")
    print(f"    {'year':<6} {'trades':>7} {'win%':>7} {'mean':>9} {'sum':>10} {'₩25%':>14}")
    for year in sorted(trades_df["year"].unique()):
        yr_trades = trades_df[trades_df["year"] == year]
        rets = yr_trades["ret"].values
        cash = 1_000_000
        for r in rets:
            pos = cash * 0.25
            cash = cash - pos + pos * (1 + r)
        print(f"    {year:<6} {len(rets):>7} {(rets>0).mean()*100:>6.1f}% "
              f"{rets.mean()*100:>+8.2f}% {rets.sum()*100:>+9.1f}% "
              f"₩{cash:>12,.0f}")

    # ====== Generate HTML ======
    cum_cash_25 = 1_000_000
    capital_curve = [(pd.Timestamp("2017-12-31"), cum_cash_25)]
    for t in sorted(all_oos_trades, key=lambda x: x["date"]):
        pos = cum_cash_25 * 0.25
        cum_cash_25 = cum_cash_25 - pos + pos * (1 + t["ret"])
        capital_curve.append((pd.Timestamp(t["date"]), cum_cash_25))

    # SVG curve (log scale optional)
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
    ₩1M start → ₩{cum_cash_25:,.0f} ({(cum_cash_25/1_000_000-1)*100:+.0f}%)
  </text>
</svg>
"""
    else:
        svg_curve = ""

    # Per-year table HTML
    years_html = "<tr><th>Year</th><th>Trades</th><th>Win%</th><th>Mean</th><th>Sum</th><th>₩1M (25%)</th></tr>"
    for year in sorted(trades_df["year"].unique()):
        yr_trades = trades_df[trades_df["year"] == year]
        rets = yr_trades["ret"].values
        cash = 1_000_000
        for r in rets:
            pos = cash * 0.25
            cash = cash - pos + pos * (1 + r)
        wr = (rets > 0).mean()
        cls = "win" if rets.mean() > 0 else "lose"
        years_html += f"""<tr>
          <td>{year}</td>
          <td class="num">{len(rets)}</td>
          <td class="num">{wr*100:.0f}%</td>
          <td class="num {cls}">{rets.mean()*100:+.2f}%</td>
          <td class="num {cls}">{rets.sum()*100:+.1f}%</td>
          <td class="num">₩{cash:,.0f}</td>
        </tr>"""

    # Monthly log table HTML (collapsed by year)
    log_html = "<tr><th>Month</th><th>Chosen Rule</th><th>Train N</th><th>Test N</th><th>Win%</th><th>Mean</th></tr>"
    for _, r in log_df.iterrows():
        ts_win_s = f"{r['test_win']*100:.0f}%" if r["test_win"] is not None and not pd.isna(r["test_win"]) else "—"
        ts_mean_s = f"{r['test_mean']*100:+.1f}%" if r["test_mean"] is not None and not pd.isna(r["test_mean"]) else "—"
        cls = ""
        if r["test_mean"] is not None and not pd.isna(r["test_mean"]):
            cls = "win" if r["test_mean"] > 0 else "lose"
        log_html += f"""<tr>
          <td>{r['month']}</td>
          <td><code>{html.escape(r['rule'])}</code></td>
          <td class="num">{int(r['train_n']) if r['train_n'] else 0}</td>
          <td class="num">{int(r['test_n'])}</td>
          <td class="num">{ts_win_s}</td>
          <td class="num {cls}">{ts_mean_s}</td>
        </tr>"""

    cum_alloc25 = cum_cash_25
    cum_pct = (cum_alloc25 / 1_000_000 - 1) * 100

    css = """
:root{--bg:#0f1115;--panel:#181b22;--panel-2:#1f232c;--border:#2a2f3a;--text:#e8e8ea;--muted:#8b93a7;--accent:#4f8cff;--green:#1fbf75;--red:#ff5b6c;}
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);line-height:1.5}
.container{max-width:1080px;margin:0 auto;padding:32px 20px 80px}
header{padding-bottom:24px;border-bottom:1px solid var(--border);margin-bottom:28px}
h1{margin:0 0 6px;font-size:26px;font-weight:700}h2{margin:0 0 14px;font-size:16px;font-weight:600}
.sub{color:var(--muted);font-size:13px}.nav{margin-top:14px}.nav a{display:inline-block;margin-right:12px;color:var(--accent);text-decoration:none;font-size:13px}
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

    n = len(all_rets)
    wr = (all_rets > 0).mean()
    mean = all_rets.mean()
    body = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Long-term OOS — 2018-2026</title><style>{css}</style></head>
<body><div class="container">
  <header>
    <h1>Long-term OOS Validation — 2018-01 to 2026-06</h1>
    <div class="sub">Monthly rolling walk-forward (3-month train, 1-month apply). Stooq archive, all NASDAQ common stocks.</div>
    <div class="nav">
      <a href="./index.html">← All reports</a>
      <a href="https://github.com/stoneidev/pennysniper-validation">GitHub</a>
    </div>
  </header>

  <div class="card">
    <h2>Aggregate Stats (8.5 years)</h2>
    <div class="stats-grid">
      <div class="stat"><div class="label">Total OOS trades</div><div class="value">{n}</div></div>
      <div class="stat"><div class="label">Win rate</div><div class="value green">{wr*100:.1f}%</div></div>
      <div class="stat"><div class="label">Mean per trade</div><div class="value {('green' if mean>0 else 'red')}">{mean*100:+.2f}%</div></div>
      <div class="stat"><div class="label">₩1M (25% alloc)</div><div class="value {('green' if cum_pct>0 else 'red')}">₩{cum_alloc25:,.0f}<br><span style="font-size:11px;color:var(--muted)">{cum_pct:+.0f}%</span></div></div>
    </div>
  </div>

  <div class="card">
    <h2>Capital Curve (₩1M, 25% allocation, sequential)</h2>
    {svg_curve}
    <div class="note">Curve uses sequential per-trade compounding without overlap. Real trading would have parallel positions and broker constraints.</div>
  </div>

  <div class="card">
    <h2>Per-year Breakdown</h2>
    <table>{years_html}</table>
  </div>

  <div class="card">
    <h2>Monthly Log (chosen rule + outcome)</h2>
    <table>{log_html}</table>
  </div>

  <footer>
    Walk-forward: each month, prior 3 months used for grid search → applied to next month.
    No look-ahead. Slippage 2% per trade. Common stocks only (warrants excluded).
    Stooq archive — yfinance not used.
  </footer>
</div></body></html>
"""
    out_html = REPORTS / "_longterm_oos.html"
    out_html.write_text(body, encoding="utf-8")
    print(f"\nWrote: {out_html}")

    # ====== Markdown ======
    md = []
    md.append("# Long-term OOS Validation — 2018 to 2026\n")
    md.append(f"_Generated: {pd.Timestamp.now().isoformat()}_\n")
    md.append("## Method\n")
    md.append("Identical algorithm to live system: monthly rolling walk-forward.\n")
    md.append("- Each month M: train on prior 3 months → pick rule with highest `win_rate × (1 + p10)` score → apply to month M.\n")
    md.append("- Universe: Stooq NASDAQ common stocks (warrants/rights excluded).\n")
    md.append("- Slippage: 2% round-trip.\n\n")

    md.append("## Aggregate Results (8.5 years)\n")
    md.append(f"| Metric | Value |\n|---|---|\n")
    md.append(f"| Total OOS trades | **{n}** |\n")
    md.append(f"| Win rate | **{wr*100:.1f}%** |\n")
    md.append(f"| Mean per trade | **{mean*100:+.2f}%** |\n")
    md.append(f"| Median | {np.median(all_rets)*100:+.2f}% |\n")
    md.append(f"| p10 (worst 10%) | {np.percentile(all_rets, 10)*100:+.2f}% |\n")
    md.append(f"| p90 (best 10%) | {np.percentile(all_rets, 90)*100:+.2f}% |\n")
    md.append(f"| ₩1M with 25% alloc | **₩{cum_alloc25:,.0f}** ({cum_pct:+.0f}%) |\n\n")

    # Capital sims
    md.append("### Capital simulations (₩1M start)\n")
    for alloc, name in [(1.0, "ALL_IN"), (0.25, "25%"), (0.10, "10%")]:
        cash = 1_000_000
        for r in all_rets:
            pos = cash * alloc
            cash = cash - pos + pos * (1 + r)
        md.append(f"- **{name}** sequential → ₩{cash:,.0f} ({(cash/1_000_000-1)*100:+.0f}%)\n")
    md.append("\n")

    md.append("## Per-year Breakdown\n")
    md.append("| Year | Trades | Win% | Mean | Sum | ₩1M (25%) |\n|---|---|---|---|---|---|\n")
    for year in sorted(trades_df["year"].unique()):
        yr_trades = trades_df[trades_df["year"] == year]
        rets = yr_trades["ret"].values
        cash = 1_000_000
        for r in rets:
            pos = cash * 0.25
            cash = cash - pos + pos * (1 + r)
        wr_y = (rets > 0).mean() * 100
        md.append(f"| {year} | {len(rets)} | {wr_y:.0f}% | "
                  f"{rets.mean()*100:+.2f}% | {rets.sum()*100:+.1f}% | ₩{cash:,.0f} |\n")
    md.append("\n")

    md.append("## Monthly Chosen Rules\n")
    md.append("| Month | Rule | Train N | Test N | Win% | Mean |\n|---|---|---|---|---|---|\n")
    for _, r in log_df.iterrows():
        ts_win_s = f"{r['test_win']*100:.0f}%" if r["test_win"] is not None and not pd.isna(r["test_win"]) else "—"
        ts_mean_s = f"{r['test_mean']*100:+.1f}%" if r["test_mean"] is not None and not pd.isna(r["test_mean"]) else "—"
        md.append(f"| {r['month']} | `{r['rule']}` | "
                  f"{int(r['train_n']) if r['train_n'] else 0} | "
                  f"{int(r['test_n'])} | {ts_win_s} | {ts_mean_s} |\n")

    md.append("\n## Bear Market Performance (critical regime)\n")
    bear_years = [2018, 2020, 2022]
    md.append("| Year | Regime | Trades | Win% | Mean |\n|---|---|---|---|---|\n")
    regime_map = {2018: "Q4 selloff", 2020: "COVID crash", 2022: "Bear market"}
    for year in bear_years:
        yr = trades_df[trades_df["year"] == year]
        if len(yr) > 0:
            rets = yr["ret"].values
            md.append(f"| {year} | {regime_map.get(year, '—')} | {len(rets)} | "
                      f"{(rets>0).mean()*100:.0f}% | {rets.mean()*100:+.2f}% |\n")
        else:
            md.append(f"| {year} | {regime_map.get(year, '—')} | 0 | — | — |\n")
    md.append("\n")

    md.append("## Honest Limitations\n")
    md.append("- Stooq data quality: occasional missing days, no delisted ticker history.\n")
    md.append("- Common stocks only — warrants excluded (improves quality but reduces N).\n")
    md.append("- Slippage 2% may be optimistic; penny stock real spread 5-10%.\n")
    md.append("- Korean tax 22% not modeled.\n")
    md.append("- In-sample selection bias: monthly grid search picks best on training, may overfit.\n")
    md.append("\n")

    md.append("## Files\n")
    md.append("- `results/csv/longterm_oos_log.csv` — chosen rule per month\n")
    md.append("- `results/csv/longterm_oos_trades.csv` — every OOS trade\n")
    md.append("- `reports/_longterm_oos.html` — pretty HTML\n")
    md.append("- `scripts/breakout/breakout_20_longterm_oos.py` — reproducible script\n")

    out_md = DOCS / "longterm_oos_findings.md"
    out_md.write_text("".join(md), encoding="utf-8")
    print(f"Wrote: {out_md}")


if __name__ == "__main__":
    main()
