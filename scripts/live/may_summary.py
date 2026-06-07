"""
Generate May 2025 summary report — show what each signal would have produced.

Reads each signal from May reports, looks at subsequent price action.
"""
from pathlib import Path
import re
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
REPORTS = REPO / "reports"
CACHE = REPO / "data" / "daily_cache"

TP_RATIO = 1.50  # rule_2025_q2.json
HOLD = 60
SLIP = 0.02

# Collect all signals from May reports
signals = []
for f in sorted(REPORTS.glob("2025-05-*.md")):
    text = f.read_text()
    if "No new breakout signals" in text:
        continue
    # Parse table rows
    rows = re.findall(
        r"\|\s*\*\*([A-Z]+)\*\*\s*\|\s*\$([0-9.]+)\s*\|\s*\$([0-9.]+)\s*\|\s*\$([0-9.]+)\s*\|\s*\$([0-9.]+)",
        text,
    )
    for sym, today, prev, cons_avg, tp_target in rows:
        signals.append({
            "signal_date": f.stem,
            "symbol": sym,
            "today_close": float(today),
            "tp_target": float(tp_target),
        })

print(f"Found {len(signals)} signals across May reports\n")

# Resolve each: read price file, find next-day open, then TP/SL/time exit
results = []
for s in signals:
    sym = s["symbol"]
    sig_date = pd.Timestamp(s["signal_date"])
    csv = CACHE / f"{sym}.csv"
    if not csv.exists():
        print(f"  {sym}: no cache")
        continue
    df = pd.read_csv(csv, parse_dates=["Date"]).sort_values("Date").reset_index(drop=True)
    idx = df.index[df["Date"] == sig_date]
    if len(idx) == 0:
        print(f"  {sym}: signal date {sig_date.date()} not in data")
        continue
    sig_idx = int(idx[0])
    if sig_idx + 1 >= len(df):
        print(f"  {sym}: no next-day data")
        continue

    entry_idx = sig_idx + 1
    entry = float(df["Open"].iloc[entry_idx])
    tp_price = entry * TP_RATIO
    end_idx = min(entry_idx + HOLD, len(df) - 1)
    exit_idx = end_idx
    exit_price = float(df["Close"].iloc[end_idx])
    tp_hit = False
    days_to_tp = None
    for j in range(entry_idx, end_idx + 1):
        if float(df["High"].iloc[j]) >= tp_price:
            exit_price = tp_price
            exit_idx = j
            tp_hit = True
            days_to_tp = j - entry_idx + 1
            break
    days_held = exit_idx - entry_idx + 1
    gross_ret = exit_price / entry - 1.0
    net_ret = gross_ret - SLIP
    results.append({
        "signal_date": s["signal_date"],
        "symbol": sym,
        "entry_date": df["Date"].iloc[entry_idx].strftime("%Y-%m-%d"),
        "entry": entry,
        "exit_date": df["Date"].iloc[exit_idx].strftime("%Y-%m-%d"),
        "exit_price": exit_price,
        "tp_hit": tp_hit,
        "days_held": days_held,
        "gross_ret": gross_ret,
        "net_ret": net_ret,
    })

# Render summary report
out = REPORTS / "_may_2025_summary.md"
lines = []
lines.append("# May 2025 — Daily Report Summary")
lines.append("")
lines.append("This file aggregates all signals from May 1-30, 2025 daily reports and shows the realized outcome.")
lines.append("")
lines.append("## Active Rule (trained on 2025.01-03)")
lines.append("")
lines.append("- Consolidation: prior 30 trading days all closed < $1.00")
lines.append("- Entry range: $1.05 - $1.20")
lines.append("- Take profit: +50% (entry × 1.50)")
lines.append("- Max hold: 60 trading days")
lines.append("- Slippage: 2% round-trip")
lines.append("")

if not results:
    lines.append("**No signals during May 2025.**")
else:
    lines.append(f"## Signals Generated — {len(results)} Total")
    lines.append("")
    lines.append("| Signal Date | Symbol | Entry Date | Entry | Exit Date | Exit | TP Hit | Days Held | Net Return |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in results:
        tp_s = "✓" if r["tp_hit"] else "✗"
        lines.append(f"| {r['signal_date']} | **{r['symbol']}** | {r['entry_date']} | "
                     f"${r['entry']:.2f} | {r['exit_date']} | ${r['exit_price']:.2f} | "
                     f"{tp_s} | {r['days_held']} | **{r['net_ret']*100:+.1f}%** |")
    lines.append("")

    # Stats
    rets = [r["net_ret"] for r in results]
    win_rate = sum(1 for r in rets if r > 0) / len(rets)
    tp_rate = sum(1 for r in results if r["tp_hit"]) / len(results)
    lines.append("## Aggregate Stats")
    lines.append("")
    lines.append(f"- **Total signals**: {len(results)}")
    lines.append(f"- **TP +50% hit rate**: {tp_rate:.1%}")
    lines.append(f"- **Win rate (any positive)**: {win_rate:.1%}")
    lines.append(f"- **Mean net return**: {sum(rets)/len(rets)*100:+.2f}%")
    lines.append(f"- **Sum of returns**: {sum(rets)*100:+.2f}%")
    lines.append("")

    # Capital sim
    cash = 1_000_000
    for r in rets:
        position = cash * 0.25
        cash = cash - position + position * (1 + r)
    lines.append(f"## ₩1,000,000 Simulation (25% allocation)")
    lines.append("")
    lines.append(f"- Final value: **₩{cash:,.0f}**")
    lines.append(f"- Total return: **{(cash/1_000_000-1)*100:+.1f}%**")
    lines.append("")

lines.append("## All May 2025 Reports")
lines.append("")
for f in sorted(REPORTS.glob("2025-05-*.md")):
    lines.append(f"- [{f.stem}](./{f.name})")
lines.append("")

out.write_text("\n".join(lines), encoding="utf-8")
print(f"Wrote: {out}")
print()
print("\n".join(lines[-15:]))
